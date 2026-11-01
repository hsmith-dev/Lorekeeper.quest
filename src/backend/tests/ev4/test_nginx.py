"""The EV-4 nginx parser and matcher (tests/ev4/nginx.py). DB- and app-free:
this module imports only tests.ev4.nginx."""
from __future__ import annotations

import pytest

from tests.ev4 import nginx
from tests.ev4.nginx import NginxParseError, parse_text, tokenize


def tree(body: str, include_dir=None) -> nginx.Location:
    cfg = parse_text("http { server { listen 443; " + body + " } }", "test.conf", include_dir)
    return nginx.server_root(nginx.server_for_port(cfg, "443"))


def pick(body: str, uri: str) -> str | None:
    loc = tree(body).resolve(uri)
    return None if loc is None else loc.label


# ── Tokenizer ──────────────────────────────────────────────────────────────

def test_quotes_keep_special_characters_in_one_token():
    toks = tokenize('map $a $b { "~*^Bearer\\s+(?<sig>[^;{}]+)$" $sig; default \'x;y\'; }')
    values = [t.value for t in toks]
    assert "~*^Bearer\\s+(?<sig>[^;{}]+)$" in values
    assert "x;y" in values
    assert [t.value for t in toks if not t.quoted and t.value in "{};"] == ["{", ";", ";", "}"]


def test_comments_are_stripped_and_hash_inside_word_is_kept():
    toks = tokenize("a b#c; # location ~ ^/x/[0-9]{36}$ {\nd;")
    assert [t.value for t in toks] == ["a", "b#c", ";", "d", ";"]
    assert toks[-1].line == 2


def test_variable_braces_stay_in_the_word():
    assert [t.value for t in tokenize("set $x ${host}y;")] == ["set", "$x", "${host}y", ";"]


def test_unterminated_quote_fails():
    with pytest.raises(NginxParseError, match="unterminated"):
        tokenize('a "b;\n')


# ── Matching order (I/O matrix) ────────────────────────────────────────────

def test_exact_beats_regex():
    assert pick("location = /a { } location ~ ^/a { }", "/a") == "location = /a"


def test_noregex_prefix_beats_regex():
    assert pick("location ^~ /a/ { } location ~ /a/b { }", "/a/b") == "location ^~ /a/"


def test_regex_beats_prefix_in_file_order():
    body = "location /a/ { } location ~ /a/b { } location ~ /a { }"
    assert pick(body, "/a/b") == "location ~ /a/b"
    assert pick(body, "/a/c") == "location ~ /a"


def test_longest_prefix_wins_when_no_regex_matches():
    body = "location / { } location /api/ { } location /api/auth/ { } location ~ \\.png$ { }"
    assert pick(body, "/api/auth/login") == "location /api/auth/"
    assert pick(body, "/api/x") == "location /api/"
    assert pick(body, "/index.html") == "location /"
    assert pick(body, "/api/x.png") == "location ~ \\.png$"


def test_exact_only_matches_the_whole_uri():
    body = "location = /api/chat/ { } location /api/ { }"
    assert pick(body, "/api/chat/") == "location = /api/chat/"
    assert pick(body, "/api/chat/stream") == "location /api/"


def test_nested_regex_applies_only_inside_its_prefix():
    body = "location / { location ~* \\.(js|css)$ { } } location /api/ { }"
    assert pick(body, "/app.JS") == "location ~* \\.(js|css)$"
    assert pick(body, "/api/x.js") == "location /api/"


def test_case_sensitive_vs_insensitive_regex():
    assert pick("location ~ ^/A$ { }", "/a") is None
    assert pick("location ~* ^/A$ { }", "/a") == "location ~* ^/A$"


def test_named_locations_never_match():
    assert pick("location @fallback { } location / { }", "/@fallback") == "location /"


def test_pcre_named_group_compiles():
    # A regex holding `{n}` must be quoted in nginx (else `{` opens a block).
    assert pick('location ~ "^/api/(?<id>[0-9a-f-]{36})$" { }', "/api/" + "a" * 36) is not None
    assert pick('location ~ "^/api/(?<id>[0-9a-f-]{36})$" { }', "/api/abc") is None


# ── Parse errors (I/O matrix) ──────────────────────────────────────────────

@pytest.mark.parametrize("body, match", [
    ("location a b c { }", "1 or 2 arguments"),
    ("location ~~ /a { }", "unknown location modifier"),
    ("location ~ ^/a( { }", "bad regex"),
    ("location / { ", "unbalanced braces"),
    ("location / { } }", "unbalanced braces"),
    ("location /a { } location /a { }", "duplicate location /a"),
    ("location /a { } location ^~ /a { }", "duplicate"),
    ("location ~ ^/api/x/[0-9a-f-]{36}/y$ { proxy_pass http://b; }", "unexpected"),
    ("location /a;", "location without a block"),
    ("location = /a { location /a/b { } }", "inside an exact location"),
    ("location /a/ { location /b/ { } }", "outside"),
    ("location = { }", "with no URI"),
])
def test_unparseable_location_syntax_fails_loudly(body, match):
    with pytest.raises(NginxParseError, match=match) as exc:
        tree(body)
    assert "test.conf:" in str(exc.value)


def test_error_names_the_file_and_line():
    with pytest.raises(NginxParseError, match=r"x\.conf:3:"):
        parse_text("http {\n  server {\n    location a b c { }\n  }\n}\n", "x.conf")


def test_include_splices_files_from_the_nginx_dir(tmp_path):
    (tmp_path / "locs.conf").write_text("location /api/ { include /etc/nginx/common.conf; }\n")
    (tmp_path / "common.conf").write_text("proxy_pass http://backend;\n")
    root = tree("include /etc/nginx/locs.conf; include /etc/nginx/mime.types;", include_dir=tmp_path)
    (api,) = root.children
    assert api.label == "location /api/"
    assert [d.name for d in api.directives] == ["proxy_pass"]
    assert api.file.endswith("locs.conf")


def test_errors_in_an_included_file_name_that_file(tmp_path):
    (tmp_path / "bad.conf").write_text("\n\nlocation ~~ /a { }\n")
    with pytest.raises(NginxParseError, match=r"bad\.conf:3:"):
        tree("include /etc/nginx/bad.conf;", include_dir=tmp_path)


# ── The repo's real config ─────────────────────────────────────────────────

def test_real_config_parses_and_selects_the_https_server():
    root = nginx.https_locations()
    labels = [loc.label for loc in root.walk()]
    assert "location /api/" in labels
    assert "location /api/auth/" in labels
    assert "location /" in labels
    assert "location = /api/chat/stream" in labels
    # The commented-out template (unquoted {36}) is a comment, not a location.
    assert not any("{36}" in label for label in labels)


def test_real_config_http_server_has_no_locations():
    cfg = list(nginx.load_config())
    http80 = nginx.server_for_port(cfg, "80")
    assert nginx.server_root(http80).children == []


def test_real_config_matching():
    root = nginx.https_locations()
    assert root.resolve("/api/journals/generate").label == "location = /api/journals/generate"
    assert root.resolve("/api/journals/").label == "location /api/"
    assert root.resolve("/api/auth/login").label == "location /api/auth/"
    assert root.resolve("/assets/app.js").label.startswith("location ~* ")
    assert root.resolve("/campaigns/123").label == "location /"
