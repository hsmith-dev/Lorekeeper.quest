"""A small nginx config parser and location matcher for EV-4 (AD-20).

EV-4 resolves every API route against the real nginx matching order, so a
route that nginx would serve from the static ``/`` location (or that an AI
location shadows by mistake) is caught in CI. Only what the repo's config
uses is supported; anything the parser cannot read raises NginxParseError
naming the file and line, so a config change can never be skipped silently.

Matching mirrors ``ngx_http_core_find_location``. At each level:
  1. an exact (``=``) location equal to the URI wins outright;
  2. else the longest prefix location (plain or ``^~``) is remembered and its
     nested locations are searched the same way (a nested exact or regex hit
     wins);
  3. then this level's regex locations (``~``, ``~*``) are tried in file
     order, unless the remembered prefix was ``^~``; a hit wins (and its own
     nested locations are searched);
  4. else the remembered prefix (or a deeper nested prefix) is used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from tests.ev4 import repo_root


class NginxParseError(Exception):
    """The config holds syntax this parser cannot (or nginx would not) read."""


@dataclass(frozen=True)
class Token:
    value: str
    quoted: bool
    file: str
    line: int

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class Directive:
    name: str
    args: list[str]
    block: list["Directive"] | None
    file: str
    line: int

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


_SPECIAL = ";{}"
_PUNCT_AFTER_QUOTE = set(" \t\r\n;{})")


def tokenize(text: str, file: str = "<string>") -> list[Token]:
    """Split nginx config text into tokens, as nginx's own tokenizer does:
    ``#`` starts a comment only at the start of a token, quoted strings
    (single or double) are one token and may hold ``;``, ``{`` or ``}``, and
    ``${var}`` stays inside its word."""
    tokens: list[Token] = []
    i, n, line = 0, len(text), 1
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            continue
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch in _SPECIAL:
            tokens.append(Token(ch, False, file, line))
            i += 1
            continue
        if ch in "\"'":
            quote, start_line = ch, line
            i += 1
            buf: list[str] = []
            while True:
                if i >= n:
                    raise NginxParseError(f"{file}:{start_line}: unterminated {quote}quoted string")
                c = text[i]
                if c == "\\" and i + 1 < n and text[i + 1] in (quote, "\\"):
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                if c == "\n":
                    line += 1
                buf.append(c)
                i += 1
            if i < n and text[i] not in _PUNCT_AFTER_QUOTE:
                raise NginxParseError(f"{file}:{line}: unexpected {text[i]!r} after quoted string")
            tokens.append(Token("".join(buf), True, file, start_line))
            continue
        start, start_line = i, line
        while i < n:
            c = text[i]
            if c in " \t\r\n;":
                break
            if c == "{" and i > start and text[i - 1] == "$":
                close = text.find("}", i)
                if close == -1 or "\n" in text[i:close]:
                    raise NginxParseError(f"{file}:{line}: unterminated ${{variable}}")
                i = close + 1
                continue
            if c in "{}":
                break
            i += 1
        tokens.append(Token(text[start:i], False, file, start_line))
    return tokens


def _is_punct(tok: Token, ch: str) -> bool:
    return not tok.quoted and tok.value == ch


class _Parser:
    def __init__(self, include_dir: Path | None):
        self.include_dir = include_dir
        self.skipped_includes: list[str] = []
        self._stack: list[Path] = []

    def parse_file(self, path: Path) -> list[Directive]:
        path = path.resolve()
        if path in self._stack:
            raise NginxParseError(f"{path}: include cycle ({' -> '.join(map(str, self._stack))})")
        self._stack.append(path)
        try:
            tokens = tokenize(path.read_text(), str(path))
            directives, pos = self._parse_block(tokens, 0, opener=None)
            return directives
        finally:
            self._stack.pop()

    def parse_text(self, text: str, file: str) -> list[Directive]:
        directives, _ = self._parse_block(tokenize(text, file), 0, opener=None)
        return directives

    def _parse_block(self, tokens: list[Token], pos: int, opener: Token | None) -> tuple[list[Directive], int]:
        out: list[Directive] = []
        words: list[Token] = []
        while pos < len(tokens):
            tok = tokens[pos]
            if _is_punct(tok, ";"):
                if not words:
                    raise NginxParseError(f"{tok.where}: unexpected ';'")
                d = Directive(words[0].value, [w.value for w in words[1:]], None, words[0].file, words[0].line)
                out.extend(self._splice(d))
                words = []
                pos += 1
            elif _is_punct(tok, "{"):
                if not words:
                    raise NginxParseError(f"{tok.where}: unexpected '{{'")
                block, pos = self._parse_block(tokens, pos + 1, opener=tok)
                out.append(Directive(words[0].value, [w.value for w in words[1:]], block,
                                     words[0].file, words[0].line))
                words = []
            elif _is_punct(tok, "}"):
                if words:
                    raise NginxParseError(
                        f"{tok.where}: unexpected '}}' (directive {words[0].value!r} at "
                        f"{words[0].where} has no ';')"
                    )
                if opener is None:
                    raise NginxParseError(f"{tok.where}: unbalanced braces: '}}' with no open block")
                return out, pos + 1
            else:
                words.append(tok)
                pos += 1
        if words:
            raise NginxParseError(f"{words[0].where}: unexpected end of file (directive {words[0].value!r} has no ';')")
        if opener is not None:
            raise NginxParseError(f"{opener.where}: unbalanced braces: block opened here is never closed")
        return out, pos

    def _splice(self, d: Directive) -> list[Directive]:
        """``include <file>;`` is replaced by the file's directives when the
        file lives in the repo's nginx/ directory (the image copies those to
        /etc/nginx/). Other includes (mime.types) are recorded and skipped."""
        if d.name != "include":
            return [d]
        if len(d.args) != 1:
            raise NginxParseError(f"{d.where}: include takes exactly one argument")
        target = d.args[0]
        if any(ch in target for ch in "*?["):
            raise NginxParseError(f"{d.where}: glob includes are not supported ({target!r})")
        if self.include_dir is not None:
            local = self.include_dir / Path(target).name
            if local.is_file():
                return self.parse_file(local)
        self.skipped_includes.append(target)
        return []


def parse(path: Path, include_dir: Path | None = None) -> list[Directive]:
    """Parse a config file, splicing includes found in ``include_dir``
    (default: the file's own directory). Every ``location`` is validated, and
    every ``http > server`` location tree is built, so bad location syntax
    raises here."""
    return _validate(_Parser(include_dir or path.parent).parse_file(path))


def parse_text(text: str, file: str = "<string>", include_dir: Path | None = None) -> list[Directive]:
    return _validate(_Parser(include_dir).parse_text(text, file))


def _validate(config: list[Directive]) -> list[Directive]:
    def walk(directives: list[Directive]) -> None:
        for d in directives:
            if d.name == "location":
                _location_args(d)
            if d.block is not None:
                walk(d.block)
    walk(config)
    for server in servers(config):
        server_root(server)
    return config


# ── Locations ───────────────────────────────────────────────────────────────

EXACT, PREFIX, NOREGEX, REGEX, REGEX_CI, NAMED = "=", "", "^~", "~", "~*", "@"
_MODIFIERS = {EXACT, NOREGEX, REGEX, REGEX_CI}


def _pcre_to_python(pattern: str) -> str:
    # PCRE named groups (?<name>...) are Python's (?P<name>...); leave the
    # lookbehinds (?<= and (?<! alone.
    return re.sub(r"\(\?<(?![=!])", "(?P<", pattern)


@dataclass(eq=False)
class Location:
    modifier: str
    uri: str
    file: str
    line: int
    directives: list[Directive] = field(default_factory=list)
    children: list["Location"] = field(default_factory=list)
    parent: "Location | None" = None
    regex: re.Pattern | None = None

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"

    @property
    def label(self) -> str:
        if self.modifier == "server":
            return "server"
        return f"location {self.modifier + ' ' if self.modifier else ''}{self.uri}"

    def __repr__(self) -> str:
        return f"<{self.label} @ {self.where}>"

    def walk(self):
        for child in self.children:
            yield child
            yield from child.walk()

    def resolve(self, uri: str) -> "Location | None":
        """The location nginx would pick for ``uri`` (None: no location)."""
        state: list[Location | None] = [None]
        _find(self, uri, state)
        return state[0]


def _find(level: Location, uri: str, state: list) -> bool:
    """One level of ngx_http_core_find_location; True means a final hit."""
    statics = [c for c in level.children if c.modifier in (EXACT, PREFIX, NOREGEX)]
    for c in statics:
        if c.modifier == EXACT and c.uri == uri:
            state[0] = c
            return True
    prefixes = [c for c in statics if c.modifier in (PREFIX, NOREGEX) and uri.startswith(c.uri)]
    noregex = False
    if prefixes:
        best = max(prefixes, key=lambda c: len(c.uri))
        state[0] = best
        noregex = best.modifier == NOREGEX
        if _find(best, uri, state):
            return True
    if not noregex:
        for c in level.children:
            if c.modifier in (REGEX, REGEX_CI) and c.regex.search(uri):
                state[0] = c
                _find(c, uri, state)
                return True
    return False


def _location_args(d: Directive) -> tuple[str, str, re.Pattern | None]:
    """(modifier, uri, compiled regex) of a ``location`` directive."""
    args = d.args
    if d.block is None:
        raise NginxParseError(f"{d.where}: location without a block")
    if len(args) == 2:
        mod, uri = args
        if mod not in _MODIFIERS:
            raise NginxParseError(f"{d.where}: unknown location modifier {mod!r}")
    elif len(args) == 1:
        raw = args[0]
        if raw.startswith("@"):
            mod, uri = NAMED, raw
        elif raw.startswith("~*"):
            mod, uri = REGEX_CI, raw[2:]
        elif raw.startswith("~"):
            mod, uri = REGEX, raw[1:]
        elif raw.startswith("=") and len(raw) > 1:
            mod, uri = EXACT, raw[1:]
        elif raw in _MODIFIERS:
            raise NginxParseError(f"{d.where}: location modifier {raw!r} with no URI")
        else:
            mod, uri = PREFIX, raw
    else:
        raise NginxParseError(f"{d.where}: location takes 1 or 2 arguments, got {len(args)}: {args}")
    if not uri:
        raise NginxParseError(f"{d.where}: location with an empty URI")
    regex = None
    if mod in (REGEX, REGEX_CI):
        try:
            regex = re.compile(_pcre_to_python(uri), re.IGNORECASE if mod == REGEX_CI else 0)
        except re.error as exc:
            raise NginxParseError(f"{d.where}: bad regex {uri!r}: {exc}") from None
    return mod, uri, regex


def _location_from(d: Directive, parent: Location) -> Location:
    mod, uri, regex = _location_args(d)
    loc = Location(mod, uri, d.file, d.line, parent=parent, regex=regex)
    if parent.modifier == EXACT:
        raise NginxParseError(f"{d.where}: {loc.label} is inside an exact location ({parent.where})")
    if parent.modifier == NAMED:
        raise NginxParseError(f"{d.where}: {loc.label} is inside a named location ({parent.where})")
    if mod == NAMED and parent.modifier != "server":
        raise NginxParseError(f"{d.where}: named {loc.label} must be at server level")
    if mod in (EXACT, PREFIX, NOREGEX) and parent.modifier in (PREFIX, NOREGEX) and not uri.startswith(parent.uri):
        raise NginxParseError(f"{d.where}: {loc.label} is outside {parent.label} ({parent.where})")
    return loc


def build_locations(directives: list[Directive], parent: Location) -> Location:
    seen: dict[tuple[str, str], Location] = {}
    for d in directives:
        if d.name == "location":
            loc = _location_from(d, parent)
            key = ("static" if loc.modifier in (PREFIX, NOREGEX) else loc.modifier, loc.uri)
            if key in seen:
                raise NginxParseError(
                    f"{d.where}: duplicate {loc.label} (first at {seen[key].where})"
                )
            seen[key] = loc
            build_locations(d.block, loc)
            parent.children.append(loc)
        else:
            parent.directives.append(d)
            if d.block is not None and d.name in ("if", "limit_except"):
                for inner in d.block:
                    if inner.name == "location":
                        raise NginxParseError(f"{inner.where}: location inside {d.name!r} block")
    return parent


def servers(config: list[Directive]) -> list[Directive]:
    out: list[Directive] = []
    for d in config:
        if d.name == "http" and d.block is not None:
            out.extend(s for s in d.block if s.name == "server" and s.block is not None)
    return out


def server_root(server: Directive) -> Location:
    return build_locations(server.block, Location("server", "", server.file, server.line))


def server_for_port(config: list[Directive], port: str) -> Directive:
    hits = [s for s in servers(config)
            if any(d.name == "listen" and d.args and d.args[0].split(":")[-1] == port for d in s.block)]
    if len(hits) != 1:
        raise NginxParseError(f"expected exactly one server listening on {port}, found {len(hits)}")
    return hits[0]


def nginx_dir() -> Path:
    path = repo_root() / "nginx"
    if not (path / "nginx.conf").is_file():
        raise RuntimeError(f"EV-4: {path / 'nginx.conf'} is missing")
    return path


@lru_cache(maxsize=1)
def load_config() -> tuple[Directive, ...]:
    return tuple(parse(nginx_dir() / "nginx.conf"))


@lru_cache(maxsize=1)
def https_locations() -> Location:
    """The location tree of the 443 server in the repo's nginx/nginx.conf
    (includes from nginx/ spliced in)."""
    return server_root(server_for_port(list(load_config()), "443"))
