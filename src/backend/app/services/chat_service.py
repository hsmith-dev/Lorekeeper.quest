import asyncio
import httpx
from fastapi import HTTPException
from app.core.config import get_settings
from app.services.llm_provider import LLMConfig, complete_messages

settings = get_settings()

_SYSTEM_PROMPT = (
    "You are Lorekeeper, an ancient and wise chronicler bound to serve adventurers across the realms. "
    "You assist dungeon masters and players with their campaigns — answering lore questions, helping plan "
    "sessions, suggesting NPC dialogue, tracking events, and offering dramatic narrative advice. "
    "Be atmospheric, knowledgeable, and in-character. Speak as a learned sage who has witnessed countless "
    "heroic deeds. Keep responses focused and useful, 1-4 paragraphs unless asked for more."
)


async def check_kobold_health() -> bool:
    """Return True if the configured local LLM backend is reachable and has
    a model available. Despite the name/setting (KOBOLD_URL), this also
    needs to work when KOBOLD_URL actually points at Ollama (the backend
    used on GPU-less hosts like OCI's Always Free tier — see
    docker-compose.prod.yml's `ollama` service) — but `/api/v1/model` is a
    KoboldCpp-native path Ollama doesn't implement at all, so that alone
    always 404s and falsely reports the model as offline there. Try
    KoboldCpp's native path first, then fall back to Ollama's native
    `/api/tags` (lists locally available models) before giving up.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.kobold_url}/api/v1/model")
            if r.status_code == 200 and bool(r.json().get("result")):
                return True
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.kobold_url}/api/tags")
            return r.status_code == 200 and bool(r.json().get("models"))
    except Exception:
        return False


async def generate_chat_reply(
    message: str,
    history: list[dict],
    campaign_name: str | None,
    genre: str | None,
    journal_context: list[dict],
    config: LLMConfig | None = None,
    canon_context: str | None = None,
    shorthand_glossary: list[dict] | None = None,
) -> str:
    system_parts = [_SYSTEM_PROMPT]

    if campaign_name:
        system_parts.append(f"\nActive Campaign: {campaign_name} (genre: {genre or 'fantasy'})")

    if canon_context:
        system_parts.append(
            "\n[Canonical campaign source material — treat these facts as authoritative. "
            "Do not contradict names, places, or events described here:]\n" + canon_context
        )

    if shorthand_glossary:
        # See app/services/shorthand_service.py::get_glossary — same
        # treatment as canon_context above, so the player can use this
        # campaign's own shorthand/abbreviations mid-conversation and the
        # assistant understands them.
        lines = "\n".join(
            f"- {g['term']}: {g['meaning']}" + (f" (usage: {g['usage']})" if g.get("usage") else "")
            for g in shorthand_glossary
        )
        system_parts.append("\n[This campaign's shorthand glossary:]\n" + lines)

    if journal_context:
        entries = []
        for j in journal_context:
            date_str = f" [{j['session_date']}]" if j.get("session_date") else ""
            entries.append(f"- Notes{date_str}: {j['shorthand']}\n  Chronicle: {j['narrative'][:350]}")
        system_parts.append(
            "\n[Relevant journal entries — use these to ground your answer in the player's actual story:]\n"
            + "\n".join(entries)
        )
    # A campaign is selected but retrieval found nothing relevant (either the
    # journal is empty or nothing passed the relevance threshold). Without a
    # guard, the model answers factual questions about the campaign by
    # inventing lore wholesale — the exact failure grounding exists to
    # prevent. The note rides WITH the user message rather than in the system
    # prompt: a 7B instruct model reliably ignores a no-inventing instruction
    # buried at the end of a long system block (verified live — it named a
    # whole fictional "Queen Araenor" past a system-level version of this),
    # but attends to the message it's directly replying to. Only the model
    # sees this framing; the persisted chat history keeps the user's original
    # message (see the chat route, which stores body.message).
    user_content = message
    if campaign_name and not journal_context and not canon_context:
        user_content = (
            "[Note from the app: the campaign journal has no entries relevant "
            "to this question. If it asks what happened, or about specific "
            "people, places, or events in this campaign, answer that the "
            "journal has no record of that — do not invent campaign lore. "
            "Brainstorming or creating new material is fine if asked for.]\n\n"
            + message
        )

    messages: list[dict] = [{"role": "system", "content": "\n".join(system_parts)}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_content})

    return await complete_messages(messages, config, max_tokens=600, timeout=settings.kobold_timeout_seconds)


async def autocomplete_notes(
    text: str,
    campaign_name: str | None,
    genre: str | None,
    config: LLMConfig | None = None,
) -> str:
    system = (
        "You are an autocomplete assistant for a tabletop RPG session notes app. "
        "Given partial session notes, suggest a natural continuation of 5-15 words that fits the style. "
        "Match the user's shorthand: brief phrases, NPC names, items, locations. "
        "Return ONLY the completion text — no quotes, no explanation, no punctuation at the start."
    )
    if campaign_name:
        system += f"\nCampaign: {campaign_name} ({genre or 'fantasy'})"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Complete: {text}"},
    ]

    try:
        raw = await complete_messages(messages, config, max_tokens=25, temperature=0.8, timeout=8)
        for line in raw.splitlines():
            line = line.strip().lstrip(".,- ")
            if line and not line.lower().startswith("complete:"):
                return line[:80]
        return ""
    except Exception:
        return ""


async def suggest_quests(
    entries: list[dict],
    campaign_name: str | None,
    genre: str | None,
    config: LLMConfig | None = None,
) -> list[str]:
    system = (
        "You are a tabletop RPG game master assistant. Given journal entries from a campaign, "
        "suggest 3-5 quest hooks or objectives the party could pursue next. "
        "Each suggestion must be a single concise line (under 12 words). "
        "Return ONLY a numbered list, nothing else. Example: 1. Find the stolen artifact in the ruins."
    )
    if campaign_name:
        system += f"\nCampaign: {campaign_name} ({genre or 'fantasy'})"

    entries_text = "\n".join(f"- {e['shorthand']}" for e in entries)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Based on these notes, suggest quests:\n{entries_text}"},
    ]

    try:
        raw = await complete_messages(messages, config, max_tokens=150, temperature=0.85, timeout=settings.kobold_timeout_seconds)
        suggestions = []
        for line in raw.splitlines():
            line = line.strip()
            import re
            clean = re.sub(r"^\d+[.)]\s*", "", line).strip()
            if clean:
                suggestions.append(clean)
        return suggestions[:5]
    except Exception:
        return []


async def generate_session_recap(
    entries: list[dict],
    campaign_name: str | None,
    genre: str | None,
    config: LLMConfig | None = None,
) -> str:
    system = (
        "You are Lorekeeper, an ancient chronicler of heroic deeds. "
        "Given journal entries from a tabletop RPG campaign, write a gripping narrative recap in 2-4 paragraphs. "
        "Use dramatic, in-world language. Preserve every NPC, location, item, and event mentioned. "
        "Write in third person, past tense. Help players remember what happened last session."
    )
    if campaign_name:
        system += f"\nCampaign: {campaign_name} ({genre or 'fantasy'})"

    entries_text = "\n\n".join(
        f"Entry {i + 1}:\nNotes: {e['shorthand']}\nChronicle: {e['narrative']}"
        for i, e in enumerate(entries)
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Write a session recap from these journal entries:\n\n{entries_text}"},
    ]

    return await complete_messages(messages, config, max_tokens=800, timeout=settings.kobold_timeout_seconds)


async def summarize_session_transcript(
    transcript: str,
    campaign_name: str | None,
    genre: str | None,
    config: LLMConfig | None = None,
) -> str:
    system = (
        "You are Lorekeeper, a scribe's assistant. You are given a raw, messy voice transcript of an "
        "entire tabletop RPG session (it may include filler words, cross-talk, and transcription errors). "
        "Condense it into concise shorthand session notes: 5-12 short bullet points capturing character "
        "names, key events, decisions, combat outcomes, items found, and quest progress. "
        "Write plainly, the way a player would jot quick notes — not a polished narrative. "
        "Return ONLY the bullet points, one per line, no headers or commentary."
    )
    if campaign_name:
        system += f"\nCampaign: {campaign_name} ({genre or 'fantasy'})"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Session transcript:\n\n{transcript[:12000]}"},
    ]

    return await complete_messages(messages, config, max_tokens=500, timeout=settings.kobold_timeout_seconds)


async def generate_npc_bio(
    name: str,
    role: str,
    entries: list[dict],
    campaign_name: str | None,
    genre: str | None,
    config: LLMConfig | None = None,
) -> str:
    system = (
        f"You are Lorekeeper, an ancient chronicler. "
        f"Write a concise biography for {name} (role: {role}) based on their mentions in campaign journals. "
        "Include their role in the story, personality traits, and key interactions. "
        "Write 2-3 paragraphs in dramatic in-world narrative style."
    )
    if campaign_name:
        system += f"\nCampaign: {campaign_name} ({genre or 'fantasy'})"

    entries_text = (
        "\n".join(f"- {e['shorthand']}" for e in entries)
        if entries else "(No journal entries mention this character yet.)"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Journal entries mentioning {name}:\n{entries_text}\n\nWrite a biography for {name}."},
    ]

    return await complete_messages(messages, config, max_tokens=400, timeout=settings.kobold_timeout_seconds)


async def generate_quest_description(
    title: str,
    entries: list[dict],
    campaign_name: str | None,
    genre: str | None,
    config: LLMConfig | None = None,
) -> str:
    system = (
        "You are Lorekeeper, an ancient chronicler of heroic deeds. "
        f"Write a compelling quest description for: '{title}', drawing on relevant journal entries. "
        "Include background, stakes, and known details. "
        "Write 2-3 paragraphs in dramatic in-world style."
    )
    if campaign_name:
        system += f"\nCampaign: {campaign_name} ({genre or 'fantasy'})"

    entries_text = (
        "\n".join(f"- {e['shorthand']}" for e in entries)
        if entries else "(No journal entries reference this quest yet.)"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Journal entries related to '{title}':\n{entries_text}\n\nWrite a quest description."},
    ]

    return await complete_messages(messages, config, max_tokens=400, timeout=settings.kobold_timeout_seconds)


async def generate_session_plan(
    campaign_name: str,
    genre: str,
    recent_entries: list[dict],
    open_quests: list[str],
    npcs: list[str],
    focus: str | None,
    config: LLMConfig | None = None,
) -> str:
    """Draft an outline for the GM's *next* session — grounded in what's
    actually happened and what's still open, not a generic template. Like
    every other AI-generated piece of content in this app, this is a draft:
    the caller (POST /api/session-plans/generate) never persists it, the
    frontend shows it in an editable review panel, and only an explicit save
    writes it to the session_plans table."""
    system = (
        "You are Lorekeeper, a veteran game master's co-planner. Draft a session plan for the "
        f"upcoming session of a {genre} tabletop campaign called '{campaign_name}'. Base it on the "
        "recent session recap, open quests, and known NPCs given below — don't invent major plot "
        "points that contradict them. Structure your answer with these headers, each 2-4 sentences "
        "or a short bullet list:\n\n"
        "RECAP: Where things stand right now.\n"
        "LIKELY OBJECTIVES: What the party will probably try to do next.\n"
        "POTENTIAL ENCOUNTERS: 2-3 concrete encounters (combat, social, or exploration) that could "
        "come up.\n"
        "NPCS TO FEATURE: Which existing NPCs are relevant and what they might do.\n"
        "COMPLICATIONS: A twist or two the GM could introduce if the session needs a spark.\n\n"
        "Keep it usable at the table — concrete and concise, not a novel."
    )
    if focus:
        system += f"\n\nThe GM specifically wants this session to focus on: {focus}"

    entries_text = (
        "\n".join(f"- {e['shorthand']}" for e in recent_entries)
        if recent_entries else "(No journal entries yet — this may be an early or first session.)"
    )
    quests_text = "\n".join(f"- {q}" for q in open_quests) if open_quests else "(No open quests logged.)"
    npcs_text = ", ".join(npcs) if npcs else "(No NPCs logged yet.)"

    user_content = (
        f"Recent sessions:\n{entries_text}\n\nOpen quests:\n{quests_text}\n\nKnown NPCs: {npcs_text}\n\n"
        "Draft the session plan."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    return await complete_messages(messages, config, max_tokens=700, timeout=settings.kobold_timeout_seconds)


async def generate_campaign_concept(genre: str, prompt: str | None, config: LLMConfig | None = None) -> tuple[str, str]:
    """Draft a homebrew campaign concept — a name and a premise — from a
    genre and an optional freeform idea/theme. Returns (name, description);
    never persists anything, the campaign is only created if/when the user
    submits the (possibly edited) New Campaign form themselves."""
    system = (
        "You are Lorekeeper, a creative tabletop campaign designer. Invent an original "
        f"homebrew {genre} campaign concept. Respond in EXACTLY this two-line format, nothing else:\n"
        "TITLE: <a short, evocative campaign name>\n"
        "PREMISE: <a 2-4 paragraph campaign premise — setting, central conflict, and hook that "
        "gets the party involved. Written for the GM, not the players — it's fine to reveal "
        "secrets the party wouldn't know yet.>"
    )
    user_content = (
        f"Idea/theme to build from: {prompt}" if prompt and prompt.strip()
        else "Surprise me — invent something original for this genre."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    raw = await complete_messages(messages, config, max_tokens=500, timeout=settings.kobold_timeout_seconds)
    return _parse_concept(raw)


def _parse_concept(raw: str) -> tuple[str, str]:
    """Pull TITLE:/PREMISE: out of the model's response. Models don't always
    follow a requested format exactly, so this degrades gracefully instead of
    raising — worst case, the user gets a generic title and the full response
    as the description, both of which they can edit before creating anything."""
    title = "Untitled Campaign"
    premise_lines: list[str] = []
    in_premise = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("TITLE:"):
            title = stripped.split(":", 1)[1].strip() or title
            in_premise = False
        elif stripped.upper().startswith("PREMISE:"):
            premise_lines.append(stripped.split(":", 1)[1].strip())
            in_premise = True
        elif in_premise:
            premise_lines.append(line)
        elif stripped:
            # No recognized header yet — the model ignored the format; treat
            # everything as premise text rather than silently dropping it.
            premise_lines.append(line)

    description = "\n".join(premise_lines).strip() or raw.strip()
    return title[:200], description
