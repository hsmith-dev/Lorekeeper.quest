import httpx
from app.core.config import get_settings
from app.services.llm_provider import LLMConfig, complete_messages

settings = get_settings()

GENRE_SYSTEM: dict[str, str] = {
    "fantasy": (
        "You are Lorekeeper, an expert fantasy scribe. Expand the following shorthand gaming notes "
        "into a rich, immersive journal entry. Write in past tense, first-person perspective. "
        "Be atmospheric. Use gaming and fantasy vocabulary naturally. 2-4 paragraphs."
    ),
    "scifi": (
        "You are Lorekeeper, a ship's log AI. Expand the following shorthand notes into a formal "
        "starship crew log entry. Past tense, first-person (crew member). Technical but readable."
    ),
    "horror": (
        "You are Lorekeeper, a gothic chronicler. Expand the following shorthand into an unsettling, "
        "atmospheric journal entry. Past tense, first-person. Dread is appropriate."
    ),
    "videogame": (
        "You are Lorekeeper, an adventurer's companion. Expand the following shorthand gaming notes "
        "into an engaging personal journal entry about a gaming session. Past tense, first-person. "
        "Reference game mechanics naturally (boss fights, loot, quests)."
    ),
    "other": (
        "You are Lorekeeper, an intelligent scribe. Expand the following shorthand notes into a "
        "well-written journal entry. Past tense, first-person. 2-4 paragraphs."
    ),
}

_NARRATIVE_EXAMPLE = (
    "\n\nExample:\n"
    "Input: fought bandits on road, mira got hit, found coin purse\n"
    "Output: The road to Ashenvale proved less safe than we had hoped. Three bandits emerged "
    "from the treeline just past the old mill — opportunistic, but skilled enough to be dangerous. "
    "Mira took a slash across the arm in the opening exchange, though she fought through it without "
    "losing her footing. When the dust settled and the last bandit fled into the woods, we searched "
    "their fallen companion and found a worn leather coin purse with enough silver to cover two nights at an inn."
)


def _length_block(paragraph_limit: int | None) -> str:
    """User-chosen narrative length for quick entry (Settings → AI). The
    genre prompts' own guidance ("2-4 paragraphs" — and some genres never
    specified at all) stays the default when unset; a set limit overrides it
    with an explicit, unambiguous instruction. Prompt-shaped rather than a
    token cutoff so the model plans a complete narrative at the requested
    length instead of getting truncated mid-sentence."""
    if not paragraph_limit:
        return ""
    label = "exactly 1 paragraph" if paragraph_limit == 1 else f"at most {paragraph_limit} paragraphs"
    return (
        f"\n\nLength requirement: write {label}. This overrides any other "
        "length guidance above. Cover the most important events within that "
        "limit rather than running long."
    )


def _canon_block(canon_context: str | None) -> str:
    if not canon_context:
        return ""
    return (
        "\n\n[Canonical campaign source material — treat these facts as authoritative. "
        "Do not contradict names, places, or events described here:]\n" + canon_context
    )


def _shorthand_block(shorthand_glossary: list[dict] | None) -> str:
    """See app/services/shorthand_service.py::get_glossary — campaign-defined
    abbreviations (e.g. "BBEG" -> "the big bad evil guy") the input notes may
    use. Told to the model as authoritative vocabulary, same treatment as
    the canon block above, so shorthand terms get expanded correctly instead
    of guessed at or left untouched in the output."""
    if not shorthand_glossary:
        return ""
    lines = "\n".join(
        f"- {g['term']}: {g['meaning']}" + (f" (usage: {g['usage']})" if g.get("usage") else "")
        for g in shorthand_glossary
    )
    return (
        "\n\n[This campaign's shorthand glossary — the input notes may use these "
        "abbreviations/terms with these specific meanings. Expand them accordingly:]\n" + lines
    )


async def generate_narrative(
    notes: str,
    genre: str = "fantasy",
    config: LLMConfig | None = None,
    canon_context: str | None = None,
    shorthand_glossary: list[dict] | None = None,
    paragraph_limit: int | None = None,
) -> str:
    system = GENRE_SYSTEM.get(genre, GENRE_SYSTEM["other"])
    if genre == "fantasy":
        system += _NARRATIVE_EXAMPLE
    system += _canon_block(canon_context)
    system += _shorthand_block(shorthand_glossary)
    system += _length_block(paragraph_limit)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Input: {notes}\nOutput:"},
    ]

    # For real KoboldCpp, prefer the native /api/v1/generate endpoint since it
    # supports stop_sequence and rep_pen. Ollama — the default hosted backend
    # on GPU-less deployments (see docker-compose.prod.yml's `ollama`
    # service) — doesn't implement that KoboldCpp-native path at all (404),
    # despite otherwise being OpenAI-compatible, so on failure fall through
    # to the generic chat-completions path below instead of raising. Same
    # reasoning as check_kobold_health's KoboldCpp-then-Ollama fallback.
    if config is None or config.provider == "kobold":
        try:
            return await _generate_kobold_native(notes, genre, config, canon_context, shorthand_glossary, paragraph_limit)
        except Exception:
            pass

    return await complete_messages(
        messages,
        config,
        max_tokens=settings.kobold_max_length,
        timeout=settings.kobold_timeout_seconds,
    )


async def _generate_kobold_native(
    notes: str,
    genre: str,
    config: LLMConfig | None,
    canon_context: str | None = None,
    shorthand_glossary: list[dict] | None = None,
    paragraph_limit: int | None = None,
) -> str:
    """Use KoboldCpp's native /api/v1/generate with stop_sequence support."""
    from app.services.llm_provider import get_default_config
    cfg = config or get_default_config()
    base = (cfg.api_url or settings.kobold_url).rstrip("/")

    system_prompt = GENRE_SYSTEM.get(genre, GENRE_SYSTEM["other"])
    if genre == "fantasy":
        system_prompt += _NARRATIVE_EXAMPLE
    system_prompt += _canon_block(canon_context)
    system_prompt += _shorthand_block(shorthand_glossary)
    system_prompt += _length_block(paragraph_limit)
    prompt = f"{system_prompt}\n\nInput: {notes}\nOutput:"

    payload = {
        "prompt": prompt,
        "max_length": settings.kobold_max_length,
        "temperature": cfg.temperature,
        "top_p": settings.kobold_top_p,
        "stop_sequence": ["\nInput:"],
        "rep_pen": 1.1,
    }

    async with httpx.AsyncClient(timeout=settings.kobold_timeout_seconds) as client:
        for attempt in range(3):
            try:
                r = await client.post(f"{base}/api/v1/generate", json=payload)
                r.raise_for_status()
                return r.json()["results"][0]["text"].strip()
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise RuntimeError(f"KoboldCpp unavailable after 3 attempts: {exc}") from exc
    raise RuntimeError("Unreachable")
