"""
Generates synthetic shorthand→narrative training pairs across genres, game systems,
and scenario types. Narratives can be filled by KoboldCpp (local) or any cloud LLM.

Usage examples:
  # Generate shorthands only, all genres, save to JSONL
  python generate_training_data.py --count 5

  # Generate + fill narratives via local KoboldCpp
  python generate_training_data.py --count 10 --generate-narratives

  # Fill narratives via Anthropic Claude
  python generate_training_data.py --count 5 --generate-narratives \\
    --provider anthropic --api-key sk-ant-... --model claude-haiku-4-5-20251001

  # Fill narratives via OpenAI
  python generate_training_data.py --count 5 --generate-narratives \\
    --provider openai --api-key sk-... --model gpt-4o-mini

  # Fill narratives via Gemini
  python generate_training_data.py --count 5 --generate-narratives \\
    --provider gemini --api-key AIza...

  # Save to Postgres instead of (or in addition to) JSONL
  python generate_training_data.py --count 10 --generate-narratives --save-to-db

  # Narrow to one genre/system/scenario
  python generate_training_data.py --genre fantasy --system dnd_5e --scenario combat --count 20
"""

import argparse
import asyncio
import json
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# System prompts — one per genre/system
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS: dict[tuple[str, str], str] = {
    ("fantasy", "dnd_5e"): (
        "You are Lorekeeper, an expert D&D 5e scribe. Expand the following shorthand D&D 5e session "
        "notes into a rich, immersive journal entry. Write in past tense, first-person perspective. "
        "Use D&D 5e terminology naturally (saving throws, spell slots, action economy, hit points). "
        "Be atmospheric and adventurous. 2-4 paragraphs."
    ),
    ("fantasy", "pathfinder_2e"): (
        "You are Lorekeeper, a Pathfinder 2e chronicler. Expand the following shorthand notes into a "
        "detailed journal entry. Write in past tense, first-person. Reference PF2e mechanics naturally "
        "(hero points, three-action system, recall knowledge, critical specializations). 2-4 paragraphs."
    ),
    ("fantasy", "warhammer_fantasy"): (
        "You are Lorekeeper, a Warhammer Fantasy Roleplay scribe. Expand the following shorthand notes "
        "into a grim, atmospheric journal entry. Write in past tense, first-person. The tone is dark "
        "and perilous — the Old World is a brutal place. Reference careers, corruption, and fate points "
        "where appropriate. 2-4 paragraphs."
    ),
    ("fantasy", "generic"): (
        "You are Lorekeeper, an expert fantasy scribe. Expand the following shorthand gaming notes "
        "into a rich, immersive journal entry. Write in past tense, first-person perspective. "
        "Be atmospheric and use fantasy vocabulary naturally. 2-4 paragraphs."
    ),
    ("scifi", "starfinder"): (
        "You are Lorekeeper, a Starfinder Society field recorder. Expand the following shorthand notes "
        "into a formal field report written as a personal log. Past tense, first-person crew member. "
        "Reference Starfinder mechanics (resolve points, stamina, starships, drift travel) where "
        "relevant. Technical but readable. 2-4 paragraphs."
    ),
    ("scifi", "cyberpunk_red"): (
        "You are Lorekeeper, a fixer's street journal AI. Expand the following shorthand Cyberpunk RED "
        "notes into a gritty, personal log entry. Past tense, first-person. Use Night City slang and "
        "reference Cyberpunk RED mechanics (humanity, netrunning, street cred) naturally. 2-4 paragraphs."
    ),
    ("scifi", "shadowrun"): (
        "You are Lorekeeper, a shadowrunner's encrypted log. Expand the following shorthand Shadowrun "
        "notes into a detailed run debrief written as a personal journal. Past tense, first-person. "
        "Mix street slang with corporate-speak. Reference magic, tech, and metatypes naturally. "
        "2-4 paragraphs."
    ),
    ("scifi", "generic"): (
        "You are Lorekeeper, a ship's log AI. Expand the following shorthand notes into a formal "
        "crew log entry. Past tense, first-person (crew member). Technical but readable. 2-4 paragraphs."
    ),
    ("horror", "call_of_cthulhu"): (
        "You are Lorekeeper, a Call of Cthulhu case recorder. Expand the following shorthand notes "
        "into an unsettling investigation journal entry. Past tense, first-person. The tone is dread "
        "and creeping madness — reference Sanity, skill checks (Library Use, Spot Hidden, Firearms), "
        "and Lovecraftian entities naturally. 2-4 paragraphs."
    ),
    ("horror", "world_of_darkness"): (
        "You are Lorekeeper, a World of Darkness chronicler. Expand the following shorthand notes "
        "into a gothic, atmospheric journal entry. Past tense, first-person. Reference Kindred politics, "
        "Disciplines, Humanity, Blood Potency, and Masquerade concerns where relevant. Tone: dark, "
        "introspective, and politically charged. 2-4 paragraphs."
    ),
    ("horror", "generic"): (
        "You are Lorekeeper, a gothic chronicler. Expand the following shorthand into an unsettling, "
        "atmospheric journal entry. Past tense, first-person. Dread is appropriate. 2-4 paragraphs."
    ),
    ("videogame", "elden_ring"): (
        "You are Lorekeeper, a Tarnished's companion. Expand the following shorthand Elden Ring notes "
        "into an evocative personal journal entry about a session in the Lands Between. Past tense, "
        "first-person. Reference lore, boss fights, builds, and exploration in a weighty, introspective "
        "tone that matches Elden Ring's atmosphere. 2-4 paragraphs."
    ),
    ("videogame", "final_fantasy"): (
        "You are Lorekeeper, a Final Fantasy adventurer's journal. Expand the following shorthand notes "
        "into an engaging personal log entry. Past tense, first-person. Reference party mechanics, "
        "job systems, and FFXIV/FF raid terminology where appropriate. Tone: earnest and epic. "
        "2-4 paragraphs."
    ),
    ("videogame", "world_of_warcraft"): (
        "You are Lorekeeper, a World of Warcraft raid chronicler. Expand the following shorthand notes "
        "into a personal gaming journal entry. Past tense, first-person. Use WoW terminology naturally "
        "(raids, mythic+, pulls, wipes, ilvl, logs). Tone: competitive but personal. 2-4 paragraphs."
    ),
    ("videogame", "baldurs_gate"): (
        "You are Lorekeeper, a Baldur's Gate 3 companion journal. Expand the following shorthand notes "
        "into an immersive personal log. Past tense, first-person. Mix BG3/D&D mechanics with "
        "character relationships and story beats. Reference camp interactions, dialogue choices, "
        "and companion approval where relevant. 2-4 paragraphs."
    ),
    ("videogame", "generic"): (
        "You are Lorekeeper, an adventurer's companion. Expand the following shorthand gaming notes "
        "into an engaging personal journal entry about a gaming session. Past tense, first-person. "
        "Reference game mechanics naturally (boss fights, loot, quests). 2-4 paragraphs."
    ),
    ("other", "generic"): (
        "You are Lorekeeper, an intelligent scribe. Expand the following shorthand notes into a "
        "well-written journal entry. Past tense, first-person. 2-4 paragraphs."
    ),
}

# ---------------------------------------------------------------------------
# Vocabulary pools
# ---------------------------------------------------------------------------

# --- Shared ---
_OUTCOMES_WIN = ["won decisively", "barely survived", "succeeded at great cost", "emerged victorious"]
_OUTCOMES_LOSE = ["retreated with casualties", "failed and regrouped", "narrowly escaped", "suffered a setback"]
_OUTCOMES_MIX = _OUTCOMES_WIN + _OUTCOMES_LOSE

# --- D&D 5e ---
_DND_MONSTERS = ["goblin warband", "orc raiders", "skeleton horde", "vampire spawn", "mind flayer",
                  "adult red dragon", "beholder", "troll", "wyvern", "manticore", "yuan-ti cultists"]
_DND_NPCS = ["Aldric the cleric", "Zevara the rogue", "Magnusson the wizard", "Brother Torrin",
              "Lady Vashara", "Grim the ranger", "Silas the merchant"]
_DND_LOCATIONS = ["the Underdark", "Waterdeep", "the Iron Citadel", "Baldur's Gate", "an ancient temple",
                   "a cursed swamp", "the Sunken Keep", "Neverwinter", "the Feywild crossing"]
_DND_LOOT = ["+2 longsword", "spell scroll of fireball", "200 gold pieces", "amulet of health",
              "cloak of elvenkind", "Bag of Holding", "rod of the pact keeper", "+1 shield"]
_DND_DAMAGE = ["2d6 fire damage", "12 hit points", "the paladin dropped to 0 HP", "3d8 necrotic damage"]
_DND_SPELLS = ["Fireball", "Hold Person", "Counterspell", "Healing Word", "Banishment", "Wall of Force"]
_DND_CONDITIONS = ["restrained", "poisoned", "frightened", "paralyzed", "unconscious"]
_DND_LEVELS = [str(i) for i in range(2, 21)]

# --- Pathfinder 2e ---
_PF_MONSTERS = ["frost giant", "owlbear", "chimera", "drow assassin", "young blue dragon",
                 "xulgath warriors", "fetchling rogue", "gnoll marauders"]
_PF_MECHANICS = ["Hero Point spent", "Recall Knowledge succeeded", "Critical Success on Deception",
                  "Shield Block triggered", "Incapacitation condition applied", "Exploration mode shift",
                  "Aid action succeeded", "Treat Wounds roll passed"]
_PF_LOCATIONS = ["Absalom", "Egorian", "Magnimar", "the Darklands", "Varisian countryside",
                  "Cheliax embassy", "the Pathfinder lodge", "Riddleport docks"]
_PF_LOOT = ["aeon stone (scarlet and green)", "scroll of chain lightning", "ring of the ram",
             "wand of crackling lightning", "Aroden's Hearthstone", "Bag of Weasels (cursed)"]

# --- Warhammer Fantasy ---
_WHF_ENEMIES = ["Chaos marauders", "Skaven assassins", "Beastmen warband", "undead retinue",
                 "Greenskin ambush", "witch hunter inquisitors", "daemon of Nurgle"]
_WHF_LOCATIONS = ["Altdorf", "the Reikwald forest", "Nuln", "the Chaos Wastes border",
                   "a Skaven warren", "an abandoned temple of Sigmar", "Bögenhafen"]
_WHF_MECHANICS = ["Fate Point burned", "Corruption point gained", "Critical Hit: arm mangled",
                   "Insanity check failed", "Toughness save vs poison", "Career advance spent"]

# --- Starfinder ---
_SF_ENEMIES = ["Vesk soldiers", "space pirates", "Aeon Guard troopers", "Eoxian undead crew",
                "Azlanti strike team", "Swarm soldiers", "android assassins"]
_SF_LOCATIONS = ["Absalom Station", "Castrovel", "Verces", "Drift space anomaly",
                  "a derelict Eoxian vessel", "Triaxus trading post", "Golarion memorial"]
_SF_LOOT = ["prototype plasma cannon", "mk3 healing serum", "encrypted Azlanti data core",
             "Drift beacon fragment", "holodisc with star charts", "5000 credits"]
_SF_MECHANICS = ["Resolve Point spent", "Drift navigation check passed", "Engineering check vs ship damage",
                  "Stamina restored at rest", "crew action: Snap Shot fired"]

# --- Cyberpunk RED ---
_CP_ENEMIES = ["Arasaka security", "Militech squad", "Maelstrom gang", "rogue netrunner",
                "Trauma Team extraction unit", "corpo hit squad", "MaxTac officers"]
_CP_LOCATIONS = ["Night City", "Watson district", "Arasaka tower", "the Badlands",
                  "Pacifica combat zone", "Heywood", "the sewer tunnels beneath City Center"]
_CP_LOOT = ["military-grade cyberware", "Arasaka ICE breaker program", "8000 eurobucks",
             "encrypted corpo datashard", "prototype Smart Gun Link", "black market trauma patch"]
_CP_MECHANICS = ["humanity check passed", "netrunner hacked enemy cyberware",
                  "street cred raised to {cred}", "body armor absorbed {dmg} damage",
                  "REP roll vs fixer contact"]
_CP_CRED = [str(i) for i in range(3, 11)]
_CP_DMG = ["5", "8", "12", "14"]

# --- Shadowrun ---
_SR_ENEMIES = ["Lone Star patrol", "Aztechnology extraction team", "yakuza enforcers",
                "rogue mage", "corporate spider", "technomancer gone hot"]
_SR_LOCATIONS = ["Seattle Sprawl", "the Barrens", "Renraku arcology sub-level",
                  "Aztlan border crossing", "a downtown Stuffer Shack turned safehouse",
                  "Tir Tairngire forest edge"]
_SR_LOOT = ["military-spec SmartLinked assault rifle", "800 nuyen", "Aztech datachip",
             "force 6 power focus", "slap patches x3", "fake SIN rating 4"]
_SR_MECHANICS = ["Edge spent", "reagent burned for ritual", "matrix search: 4 hits",
                  "contact: Fixer rating 3 called", "spirits: bound fire spirit F6"]

# --- Call of Cthulhu ---
_COC_ENTITIES = ["Deep One", "Shoggoth", "Mi-Go", "the Crawling Chaos", "an Elder Thing",
                  "a Dimensional Shambler", "Star Vampire", "Formless Spawn of Tsathoggua"]
_COC_LOCATIONS = ["Innsmouth", "Arkham", "Dunwich", "the Miskatonic library",
                   "a fog-shrouded wharf", "the old Whateley farmhouse", "a cyclopean ruin"]
_COC_SKILLS = ["Library Use: success", "Spot Hidden: passed", "Firearms: hit", "Persuade: failed",
                "Psychology: rolled under", "Stealth: success", "Cthulhu Mythos: +3%"]
_COC_SANITY = ["lost 1d6 SAN", "failed Sanity check — temporary insanity", "SAN now at {san}",
                "indefinite insanity triggered", "regained 1d3 SAN from therapy"]
_COC_SAN_VAL = [str(i) for i in range(12, 68, 3)]
_COC_CLUES = ["cryptic journal with partial star map", "silver bracelet with Deep One markings",
               "an encrypted telegram in R'lyehian", "wax cylinder recording of chanting",
               "partial map to sunken city coordinates"]

# --- World of Darkness ---
_WOD_ENEMIES = ["Sabbat pack", "hunter cell", "rival coterie", "Tremere elder",
                 "Lupine on the prowl", "rogue Malkavian", "Second Inquisition agent"]
_WOD_LOCATIONS = ["Chicago", "New York", "the Elysium salon", "a Sabbat safehouse",
                   "the prince's court", "a mortal university feeding ground", "sewers beneath the city"]
_WOD_MECHANICS = ["Frenzy check: failed", "Humanity check: passed", "Blood Potency triggered",
                   "Discipline: Dominate used", "Masquerade breach narrowly avoided",
                   "Boon granted to prince", "Humanity dropped to {hum}"]
_WOD_HUM = [str(i) for i in range(3, 8)]
_WOD_LOOT = ["elder's personal journal", "sealed blood oath document", "encrypted haven location",
              "Tremere formula scroll", "a Discipline tutor willing to teach"]

# --- Elden Ring ---
_ER_BOSSES = ["Margit the Fell Omen", "Godrick the Grafted", "Starscourge Radahn",
               "Malenia Blade of Miquella", "Maliketh the Black Blade", "Fire Giant",
               "Rennala Queen of the Full Moon", "Mohg Lord of Blood"]
_ER_LOCATIONS = ["Stormveil Castle", "Limgrave", "Caelid", "Mountaintops of the Giants",
                  "Nokron Eternal City", "Elphael Brace of the Haligtree", "Leyndell Royal Capital",
                  "Farum Azula", "Lake of Rot"]
_ER_LOOT = ["Bloodhound's Fang", "Bull-Goat armor set", "Sacred Relic Sword", "Mimic Tear ashes",
             "Golden Scarab talisman", "Rune Arc", "Somber Smithing Stone (8)", "Nox Flowing Sword"]
_ER_ATTEMPTS = ["3", "5", "7", "12", "23", "31", "countless"]
_ER_BUILDS = ["bleed build", "strength/faith build", "dex/arcane build", "sorcerer build", "colossal weapon build"]
_ER_LEVELS = [str(i) for i in range(40, 200, 10)]

# --- Final Fantasy (FFXIV focus) ---
_FF_BOSSES = ["Sephiroth", "the Weapons", "Bahamut Prime", "Alexander Prime", "Ultimecia",
               "Zeromus", "Cloud of Darkness", "Kefka", "Eden's Promise", "The Endsinger"]
_FF_ROLES = ["tank", "healer", "DPS", "off-tank", "ranged physical", "melee DPS"]
_FF_MECHANICS = ["cleared after {pulls} pulls", "enrage at {pct}% — fixed rotation next time",
                  "healer DC'd during progression", "party chest dropped {item}",
                  "weekly lockout reset — lost loot", "savage cleared — reclears only now"]
_FF_PULLS = [str(i) for i in range(3, 80, 3)]
_FF_PCT = ["1", "2", "4", "8"]
_FF_ITEMS = ["i640 chest piece", "Alexandrian weapon coffer", "10 totems", "crafted accessories"]

# --- World of Warcraft ---
_WOW_BOSSES = ["The Lich King", "Sylvanas Windrunner", "Sire Denathrius", "Fyrakk", "Raszageth",
                "Kil'jaeden", "Archimonde", "N'Zoth", "Jailer Zovaal"]
_WOW_KEYS = [f"+{i}" for i in range(10, 26, 2)]
_WOW_LOOT = ["heroic tier set piece", "425 ilvl trinket", "mount drop (1%)", "crafted ring upgrade",
              "valor capped for the week", "catalyst charge used", "vault slot filled"]
_WOW_MECHANICS = ["{wipes} wipes on progression", "world first race position: {rank}",
                   "mythic+ timed by {sec} seconds", "log: {pct}% purple parse"]
_WOW_WIPES = [str(i) for i in range(5, 200, 10)]
_WOW_RANK = ["top 50 NA", "top 200 world", "guild first"]
_WOW_SEC = ["4", "12", "30", "47"]
_WOW_PCT = [str(i) for i in range(70, 100, 3)]

# --- Baldur's Gate 3 ---
_BG3_COMPANIONS = ["Shadowheart", "Astarion", "Gale", "Lae'zel", "Karlach", "Wyll", "Halsin", "Jaheira"]
_BG3_LOCATIONS = ["the Underdark", "Moonrise Towers", "Baldur's Gate lower city",
                   "the Creche", "Gauntlet of Shar", "the Shadow-Cursed Lands", "Cazador's palace"]
_BG3_CHOICES = ["sided with the tieflings", "let Astarion bite", "passed Persuasion DC 20",
                 "failed Insight check", "used Illithid power (resistance lowered)",
                 "romance dialogue triggered", "party approval: {comp} +{pts}"]
_BG3_APPROVAL = _BG3_COMPANIONS
_BG3_PTS = ["5", "10", "15", "20"]

# ---------------------------------------------------------------------------
# Template bank: (genre, game_system, scenario_type) -> list of (template, vocab)
# ---------------------------------------------------------------------------

TEMPLATES: dict[tuple[str, str, str], list[tuple[str, dict]]] = {

    # ── Fantasy / D&D 5e ──────────────────────────────────────────────────
    ("fantasy", "dnd_5e", "combat"): [
        ("fought {monster} in {location}. {outcome}. {npc} took {damage}.",
         {"monster": _DND_MONSTERS, "location": _DND_LOCATIONS, "outcome": _OUTCOMES_MIX,
          "npc": _DND_NPCS, "damage": _DND_DAMAGE}),
        ("{npc} ambushed by {monster}. {spell} turned the tide. {outcome}.",
         {"npc": _DND_NPCS, "monster": _DND_MONSTERS, "spell": _DND_SPELLS, "outcome": _OUTCOMES_MIX}),
        ("{monster} encounter in {location}. {npc} went {condition}. {outcome}. looted {loot}.",
         {"monster": _DND_MONSTERS, "location": _DND_LOCATIONS, "npc": _DND_NPCS,
          "condition": _DND_CONDITIONS, "outcome": _OUTCOMES_WIN, "loot": _DND_LOOT}),
    ],
    ("fantasy", "dnd_5e", "exploration"): [
        ("explored {location}. found secret passage behind {feature}. {npc} scouted ahead.",
         {"location": _DND_LOCATIONS, "feature": ["throne", "altar", "bookshelf", "waterfall"],
          "npc": _DND_NPCS}),
        ("investigated {location}. {event}. party debated whether to press deeper.",
         {"location": _DND_LOCATIONS,
          "event": ["discovered a hidden cache", "triggered a glyph of warding",
                    "found maps of lower levels", "heard chanting below"]}),
        ("delved into {location}. {npc} rolled Perception 19, spotted {find}.",
         {"location": _DND_LOCATIONS, "npc": _DND_NPCS,
          "find": ["a trapped chest", "movement in the shadows", "a collapsed tunnel with light beyond",
                   "runes along the floor"]}),
    ],
    ("fantasy", "dnd_5e", "social"): [
        ("{npc} revealed {secret}. persuasion check DC 18 — passed. party gained {reward}.",
         {"npc": _DND_NPCS,
          "secret": ["the location of the lich's phylactery", "a traitor in the city guard",
                     "the cult's true master", "a hidden safe house"],
          "reward": ["a letter of passage", "an audience with the duke", "information on the artifact"]}),
        ("met {npc} at {location}. intimidation failed. deception succeeded. got {reward}.",
         {"npc": _DND_NPCS, "location": _DND_LOCATIONS,
          "reward": ["the cipher key", "directions to the cult's hideout", "a black market contact"]}),
        ("negotiated with {npc}. terms: {terms}. party agreed. alliance formed.",
         {"npc": _DND_NPCS,
          "terms": ["we clear the dungeon, they supply healing potions",
                    "party guards the merchant convoy in exchange for 500gp",
                    "we hand over the artifact, they share intelligence on the enemy"]}),
    ],
    ("fantasy", "dnd_5e", "loot"): [
        ("looted {location}. found {loot1} and {loot2}. {npc} claimed the {loot1}.",
         {"location": _DND_LOCATIONS, "loot1": _DND_LOOT, "loot2": _DND_LOOT, "npc": _DND_NPCS}),
        ("chest in {location}: {loot1}, {loot2}, 340gp. {npc} identified {loot1} — {effect}.",
         {"location": _DND_LOCATIONS, "loot1": _DND_LOOT, "loot2": _DND_LOOT, "npc": _DND_NPCS,
          "effect": ["requires attunement", "cursed — can't remove until Remove Curse cast",
                     "worth 1200gp to the right buyer"]}),
    ],
    ("fantasy", "dnd_5e", "rest"): [
        ("long rest at {location}. {npc} kept watch. {event} during the night.",
         {"location": _DND_LOCATIONS, "npc": _DND_NPCS,
          "event": ["wolf pack circled camp but didn't attack", "mysterious light passed overhead",
                    "dream about the ancient evil beneath", "messenger arrived with urgent news"]}),
        ("short rest. {npc} used Hit Dice — recovered {hp} HP. party debated next move.",
         {"npc": _DND_NPCS, "hp": ["12", "18", "24", "9", "15"]}),
    ],
    ("fantasy", "dnd_5e", "quest_update"): [
        ("received quest from {npc}: {quest}. reward: {reward}. deadline: {deadline}.",
         {"npc": _DND_NPCS,
          "quest": ["find the missing artifact before the cult does",
                    "escort the prisoner to Waterdeep",
                    "clear out the bandits in the pass",
                    "retrieve the Orb of Dominion from the vault"],
          "reward": ["500gp", "a magic item of our choice", "a title and land grant", "information on our enemy"],
          "deadline": ["before the next full moon", "within three days", "before the army arrives"]}),
        ("{npc} updated the quest: {update}. new objective: {objective}.",
         {"npc": _DND_NPCS,
          "update": ["the artifact has been moved", "the cult knows we're coming",
                     "the real villain is the duke himself"],
          "objective": ["infiltrate the palace", "intercept the shipment at the docks",
                        "find the cult's second hideout"]}),
    ],
    ("fantasy", "dnd_5e", "boss_fight"): [
        ("final confrontation with {boss}. {attempts} attempts. {strategy} worked. {outcome}.",
         {"boss": ["the vampire lord", "the lich Morvain", "the adult red dragon", "the mind flayer elder brain",
                   "the beholder tyrant", "the demon prince"],
          "attempts": ["2", "3", "5", "first try"],
          "strategy": ["tanking with the paladin while wizard casted from range",
                       "the rogue's Sneak Attack with flanking",
                       "used the artifact to weaken its defenses", "split the party to cover both phases"],
          "outcome": _OUTCOMES_WIN}),
        ("{boss} fight at {location}. phase 2 triggered at 50% HP. {event}. {outcome}.",
         {"boss": ["the corrupted dragon", "the lich", "the vampire lord"],
          "location": _DND_LOCATIONS,
          "event": ["summoned undead reinforcements", "shields went up — had to shatter them first",
                    "NPC ally arrived to help"],
          "outcome": _OUTCOMES_WIN}),
    ],
    ("fantasy", "dnd_5e", "character_development"): [
        ("leveled up to {level}. {npc} chose {feature}. {reflection}.",
         {"level": _DND_LEVELS, "npc": _DND_NPCS,
          "feature": ["Polearm Master feat", "3rd level spell slots",
                      "Extra Attack", "Bardic Inspiration d10", "Paladin aura at 7"],
          "reflection": ["feels like a turning point for the character",
                         "finally have the tools to face what's ahead",
                         "the party is starting to feel unstoppable"]}),
        ("ASI taken: +2 STR. now at {stat}. subclass feature unlocked: {feature}.",
         {"stat": ["18", "20", "16"], "feature": ["Aura of Protection", "Assassinate",
                                                    "Portent dice", "Wild Shape (CR 1)"]}),
    ],
    ("fantasy", "dnd_5e", "world_event"): [
        ("{npc} betrayed the party. {revelation}. everything we knew was wrong.",
         {"npc": _DND_NPCS,
          "revelation": ["was a cultist the whole time", "sold us out to the lord",
                          "the artifact was a trap — it's a beacon for the demon prince",
                          "the king is already dead — replaced by a doppelganger"]}),
        ("city of {location} under attack. {attacker}. party must choose: fight or flee.",
         {"location": ["Waterdeep", "Neverwinter", "Baldur's Gate"],
          "attacker": ["Zhentarim mercenaries storming the gates",
                       "a dragon circling overhead setting buildings ablaze",
                       "undead pouring from the cemetery district"]}),
    ],
    ("fantasy", "dnd_5e", "travel"): [
        ("traveled from {from_loc} to {to_loc}. {event} on the road. {outcome}.",
         {"from_loc": _DND_LOCATIONS, "to_loc": _DND_LOCATIONS,
          "event": ["ambushed by bandits", "came across a refugee camp",
                    "discovered a burned village", "strange lights in the forest"],
          "outcome": ["arrived safely but shaken", "detoured — added two days to the journey",
                      "made good time despite the detour"]}),
        ("{days}-day journey to {to_loc}. uneventful until {event}.",
         {"days": ["2", "3", "5", "7"], "to_loc": _DND_LOCATIONS,
          "event": ["a wounded traveler flagged us down", "the road disappeared into fog",
                    "we heard drums from the hills", "a merchant caravan needed escort"]}),
    ],
    ("fantasy", "dnd_5e", "puzzle"): [
        ("trap in {location}: {trap}. {npc} {method}. {result}.",
         {"location": _DND_LOCATIONS,
          "trap": ["pressure plate grid", "rune-covered lock", "magical mirror maze",
                   "collapsing floor over a spike pit"],
          "npc": _DND_NPCS,
          "method": ["rolled Thieves' Tools 17 — disarmed it",
                     "cast Dispel Magic", "used Detect Magic first then disarmed",
                     "failed the check — everyone took 2d6 damage"],
          "result": ["safe passage", "chest revealed behind false wall",
                     "door opened — stairs going down", "alarm triggered — guards incoming"]}),
    ],
    ("fantasy", "dnd_5e", "downtime"): [
        ("3 days in {location}. {activities}.",
         {"location": _DND_LOCATIONS,
          "activities": ["Zevara crafted poison (DC 15 Constitution), Magnusson researched the cult",
                          "party sold loot for 800gp, upgraded armor",
                          "Aldric led religious rites, party recovered from wounds",
                          "gathered rumors at the inn, identified two informants"]}),
        ("{npc} spent downtime {activity}. result: {result}.",
         {"npc": _DND_NPCS,
          "activity": ["training with a master swordsman", "researching the artifact in the library",
                       "working contacts for information", "crafting a potion of healing"],
          "result": ["gained proficiency in Historia", "found a lead on the cult's financier",
                     "learned the artifact's true name", "potion complete (1d4+2 HP)"]}),
    ],

    # ── Fantasy / Pathfinder 2e ───────────────────────────────────────────
    ("fantasy", "pathfinder_2e", "combat"): [
        ("fought {monster} near {location}. {mechanic}. {outcome}.",
         {"monster": _PF_MONSTERS, "location": _PF_LOCATIONS, "mechanic": _PF_MECHANICS,
          "outcome": _OUTCOMES_MIX}),
        ("{monster} ambush. {mechanic1} and {mechanic2}. {outcome}.",
         {"monster": _PF_MONSTERS, "mechanic1": _PF_MECHANICS, "mechanic2": _PF_MECHANICS,
          "outcome": _OUTCOMES_MIX}),
    ],
    ("fantasy", "pathfinder_2e", "boss_fight"): [
        ("{boss} fight. {mechanic}. {outcome}.",
         {"boss": ["the Whispering Tyrant's champion", "Tar-Baphon's lieutenant",
                   "the Runelord's construct guardian", "a Greater Barghest warlord"],
          "mechanic": _PF_MECHANICS, "outcome": _OUTCOMES_WIN}),
    ],
    ("fantasy", "pathfinder_2e", "loot"): [
        ("recovered {loot} from {location}. {mechanic} to identify.",
         {"loot": _PF_LOOT, "location": _PF_LOCATIONS, "mechanic": ["Recall Knowledge succeeded",
                                                                       "Identify Magic: 3 hits"]}),
    ],
    ("fantasy", "pathfinder_2e", "social"): [
        ("Recall Knowledge: {target}. used info to {action}.",
         {"target": ["Drow Assassin tactics", "Cheliax noble hierarchy", "Pathfinder Society protocols"],
          "action": ["negotiate passage", "expose the spy", "earn an invitation to the salon"]}),
    ],
    ("fantasy", "pathfinder_2e", "character_development"): [
        ("reached level {level}. chose {advance}. {mechanic}.",
         {"level": [str(i) for i in range(2, 21)], "mechanic": _PF_MECHANICS,
          "advance": ["Investigator Dedication", "Magical Striker feat", "Legendary Medicine",
                      "Medic archetype entry", "Spell repertoire expanded to 4th level"]}),
    ],
    ("fantasy", "pathfinder_2e", "exploration"): [
        ("scouted {location}. {mechanic}. found {discovery}.",
         {"location": _PF_LOCATIONS, "mechanic": _PF_MECHANICS,
          "discovery": ["a hidden Darklands passage", "evidence of Aspis Consortium activity",
                        "a collapsed shrine with readable inscriptions", "a trapped chest"]}),
    ],
    ("fantasy", "pathfinder_2e", "quest_update"): [
        ("Pathfinder Society contract updated: {update}. new deadline: {deadline}.",
         {"update": ["the artifact is en route to the vault — intercept it",
                     "the Aspis Consortium knows our route",
                     "primary target escaped to Egorian"],
          "deadline": ["before the Absalom Festival", "within 48 hours", "before the tides shift"]}),
    ],
    ("fantasy", "pathfinder_2e", "rest"): [
        ("daily preparations. {npc} Treated Wounds: {result}. spell repertoire refreshed.",
         {"npc": ["Vaelira the cleric", "Brother Osman", "the party medic"],
          "result": ["healed 18 HP", "critical success — healed 30 HP", "failed — no HP recovered"]}),
    ],
    ("fantasy", "pathfinder_2e", "travel"): [
        ("travel to {location}. Exploration mode: {mode}. {event}.",
         {"location": _PF_LOCATIONS,
          "mode": ["Detect Magic active", "Scout role assigned", "Hustle — twice the distance"],
          "event": ["random encounter avoided via Stealth", "found a cache at the crossroads",
                    "crossed Darklands territory safely"]}),
    ],
    ("fantasy", "pathfinder_2e", "puzzle"): [
        ("hazard: {hazard}. {mechanic}. result: {result}.",
         {"hazard": ["arcane lock puzzle", "pressure-rune flooring", "summoning glyph hazard"],
          "mechanic": _PF_MECHANICS,
          "result": ["disabled successfully", "triggered — all took 3d6 damage",
                     "bypassed via teleportation"]}),
    ],
    ("fantasy", "pathfinder_2e", "downtime"): [
        ("{days} days downtime in {location}. {activity}.",
         {"days": ["3", "5", "7"], "location": _PF_LOCATIONS,
          "activity": ["crafted alchemical bombs", "researched Whispering Tyrant connection",
                       "earned 12 GP from task: labor", "trained with Society contacts"]}),
    ],
    ("fantasy", "pathfinder_2e", "world_event"): [
        ("{event}. Pathfinder Society mobilizing. party dispatched immediately.",
         {"event": ["Aspis Consortium seized the Vault of the Seers",
                    "Tar-Baphon sighted near the Isle of Terror",
                    "planar tear opened over Absalom harbor"]}),
    ],

    # ── Fantasy / Warhammer Fantasy ───────────────────────────────────────
    ("fantasy", "warhammer_fantasy", "combat"): [
        ("attacked by {enemy} in {location}. {mechanic}. {outcome}. grim business.",
         {"enemy": _WHF_ENEMIES, "location": _WHF_LOCATIONS, "mechanic": _WHF_MECHANICS,
          "outcome": _OUTCOMES_MIX}),
    ],
    ("fantasy", "warhammer_fantasy", "boss_fight"): [
        ("faced {boss} in {location}. {mechanic}. {outcome}. the Old World does not forgive weakness.",
         {"boss": ["a Chaos Champion of Khorne", "a vampire count", "the Skaven Grey Seer",
                   "a Greater Daemon of Tzeentch"],
          "location": _WHF_LOCATIONS, "mechanic": _WHF_MECHANICS, "outcome": _OUTCOMES_WIN}),
    ],
    ("fantasy", "warhammer_fantasy", "exploration"): [
        ("investigated {location}. {find}. corruption everywhere.",
         {"location": _WHF_LOCATIONS,
          "find": ["signs of Chaos worship", "a hidden Skaven tunnel", "an abandoned Imperial shrine",
                   "a sealed vault with Chaos markings"]}),
    ],
    ("fantasy", "warhammer_fantasy", "world_event"): [
        ("{event}. the authorities look the other way. as usual.",
         {"event": ["Skaven sighted in Altdorf sewers", "Witch Hunter arrested three members of the party",
                    "Chaos star appeared in the sky above Nuln",
                    "the Count was found dead — foul play certain"]}),
    ],
    ("fantasy", "warhammer_fantasy", "character_development"): [
        ("career advance: {advance}. {mechanic}. cost: {xp} XP.",
         {"advance": ["Weapon Skill +5", "Dodge +10", "Perception +5", "second career: Soldier"],
          "mechanic": _WHF_MECHANICS, "xp": ["100", "150", "200"]}),
    ],
    ("fantasy", "warhammer_fantasy", "social"): [
        ("met {npc} in {location}. fellowship test: {result}. {outcome}.",
         {"npc": ["the Burgomeister", "a Chaos informant", "a travelling witch hunter",
                  "a Tilean merchant with contacts"],
          "location": _WHF_LOCATIONS,
          "result": ["passed — gained trust", "failed — suspicious of us now"],
          "outcome": ["gained a lead on the cult", "warned away from further investigation",
                      "offered a contract for dangerous work"]}),
    ],
    ("fantasy", "warhammer_fantasy", "rest"): [
        ("rested at {location}. {mechanic}. wounds tend slowly in the Old World.",
         {"location": _WHF_LOCATIONS, "mechanic": ["Critical Wound: -1 STR for 1 week",
                                                     "Healing poultice applied — recovered 3 Wounds",
                                                     "Insanity Point removed via 1-week rest"]}),
    ],
    ("fantasy", "warhammer_fantasy", "travel"): [
        ("road from {from_loc} to {to_loc}. {event}. fortune was with us.",
         {"from_loc": _WHF_LOCATIONS, "to_loc": _WHF_LOCATIONS,
          "event": ["roadside ambush by mutants", "roadwardens checkpoint — bribe paid",
                    "found a burned wagon and one survivor", "Chaos warband tracks parallel to road"]}),
    ],
    ("fantasy", "warhammer_fantasy", "loot"): [
        ("searched the battlefield. found {loot}. {mechanic}.",
         {"loot": ["a chaos icon (dangerous to carry)", "silver coins stamped with strange runes",
                   "a fine sword — Dwarf-made", "a sealed letter addressed to the Count"],
          "mechanic": _WHF_MECHANICS}),
    ],
    ("fantasy", "warhammer_fantasy", "quest_update"): [
        ("the mission: {quest}. reward: {reward}. refuse and face consequences.",
         {"quest": ["find evidence of Chaos cult in the merchant guild",
                    "escort the scholar to the ruins",
                    "retrieve the stolen relic before it reaches the Chaos Wastes"],
          "reward": ["100 gold crowns", "a letter of pardon", "protection from the Witch Hunters"]}),
    ],
    ("fantasy", "warhammer_fantasy", "puzzle"): [
        ("ancient {feature} blocked the way. {method}. {result}.",
         {"feature": ["dwarf lock mechanism", "chaos ward", "Imperial cipher door"],
          "method": ["Intelligence test passed", "Academic Knowledge: Ancient Dwarf success",
                     "forced it — triggering a trap"],
          "result": ["vault opened", "alarm triggered", "passage revealed"]}),
    ],
    ("fantasy", "warhammer_fantasy", "downtime"): [
        ("spent {days} days in {location}. {activity}. the Empire never truly rests.",
         {"days": ["2", "3", "5"], "location": _WHF_LOCATIONS,
          "activity": ["recovered from wounds at the hospice",
                       "gathered intel at the tavern — two new leads",
                       "sold loot at the market — 45 gold crowns earned"]}),
    ],

    # ── Sci-Fi / Starfinder ───────────────────────────────────────────────
    ("scifi", "starfinder", "combat"): [
        ("engaged {enemy} near {location}. {mechanic}. {outcome}.",
         {"enemy": _SF_ENEMIES, "location": _SF_LOCATIONS, "mechanic": _SF_MECHANICS,
          "outcome": _OUTCOMES_MIX}),
        ("{enemy} ambush during drift approach to {location}. {mechanic}. {outcome}.",
         {"enemy": _SF_ENEMIES, "location": _SF_LOCATIONS, "mechanic": _SF_MECHANICS,
          "outcome": _OUTCOMES_MIX}),
    ],
    ("scifi", "starfinder", "boss_fight"): [
        ("confronted {boss} aboard {location}. {mechanic}. {outcome}.",
         {"boss": ["the Drift pirate admiral", "the Azlanti Strike Commander",
                   "the Eoxian bone sage", "the Swarm node-queen"],
          "location": _SF_LOCATIONS, "mechanic": _SF_MECHANICS, "outcome": _OUTCOMES_WIN}),
    ],
    ("scifi", "starfinder", "exploration"): [
        ("surveyed {location}. {mechanic}. found {discovery}.",
         {"location": _SF_LOCATIONS, "mechanic": _SF_MECHANICS,
          "discovery": ["abandoned research station with intact logs",
                        "Drift anomaly — reality unstable in 200m radius",
                        "Azlanti weapons cache", "new star chart data worth 3000 credits"]}),
    ],
    ("scifi", "starfinder", "social"): [
        ("diplomacy with {faction} officials at {location}. {outcome}. docking rights secured.",
         {"faction": ["Veskarium", "Pact Worlds Council", "Stewards", "Idari crew"],
          "location": _SF_LOCATIONS, "outcome": _OUTCOMES_WIN}),
    ],
    ("scifi", "starfinder", "loot"): [
        ("recovered {loot} from {location}. black market value: {value}.",
         {"loot": _SF_LOOT, "location": _SF_LOCATIONS,
          "value": ["12,000 credits", "5,500 credits", "8,000 credits"]}),
    ],
    ("scifi", "starfinder", "rest"): [
        ("repaired ship at {location}. {mechanic}. crew rotations adjusted.",
         {"location": _SF_LOCATIONS, "mechanic": _SF_MECHANICS}),
    ],
    ("scifi", "starfinder", "quest_update"): [
        ("Starfinder Society contract: {quest}. rendezvous: {location}.",
         {"quest": ["retrieve encrypted data core from derelict Eoxian vessel",
                    "protect Pact Worlds ambassador en route to Veskarium",
                    "investigate disappearances in the Drift near Caravanserai"],
          "location": _SF_LOCATIONS}),
    ],
    ("scifi", "starfinder", "character_development"): [
        ("reached level {level}. unlocked {feature}. {mechanic}.",
         {"level": [str(i) for i in range(2, 21)],
          "feature": ["Mechanic Trick: Energy Shield", "Solarian Weapon Manifestation: +2 damage",
                      "Operative Edge +3", "Biohacker Breakthrough: Toxicology"],
          "mechanic": _SF_MECHANICS}),
    ],
    ("scifi", "starfinder", "travel"): [
        ("{days}-day drift journey to {location}. {event}.",
         {"days": ["2", "4", "7", "14"], "location": _SF_LOCATIONS,
          "event": ["navigation check: 22 — no drift encounters",
                    "ghost ship drifted past — hailed, no response",
                    "micro-meteorite impact — hull breach, repaired in 3 hours"]}),
    ],
    ("scifi", "starfinder", "puzzle"): [
        ("cracked {system} encryption. {mechanic}. found {data}.",
         {"system": ["Azlanti military-grade", "Drift Beacon", "Eoxian biometric"],
          "mechanic": _SF_MECHANICS,
          "data": ["coordinates for the artifact cache", "distress signal from missing crew",
                   "evidence of Veskarium espionage"]}),
    ],
    ("scifi", "starfinder", "world_event"): [
        ("{event}. Pact Worlds on high alert. orders incoming from Absalom Station.",
         {"event": ["Drift Beacon network failure — FTL disrupted system-wide",
                    "Swarm hive ship spotted entering the Vast",
                    "Azlanti stealth fleet detected near Triaxus"]}),
    ],
    ("scifi", "starfinder", "downtime"): [
        ("docked at {location}. {days} days. {activity}.",
         {"location": _SF_LOCATIONS, "days": ["2", "3", "5"],
          "activity": ["upgraded ship weapons: laser array mk2",
                       "crew downtime: Shirren engineer repaired sensor array",
                       "purchased mk3 serums and combat implants"]}),
    ],

    # ── Sci-Fi / Cyberpunk RED ────────────────────────────────────────────
    ("scifi", "cyberpunk_red", "combat"): [
        ("firefight with {enemy} in {location}. {mechanic}. {outcome}.",
         {"enemy": _CP_ENEMIES, "location": _CP_LOCATIONS,
          "mechanic": [m.format(cred=random.choice(_CP_CRED), dmg=random.choice(_CP_DMG))
                       for m in _CP_MECHANICS],
          "outcome": _OUTCOMES_MIX}),
        ("{enemy} ambush in {location}. {outcome}. one casualty.",
         {"enemy": _CP_ENEMIES, "location": _CP_LOCATIONS, "outcome": _OUTCOMES_LOSE}),
    ],
    ("scifi", "cyberpunk_red", "boss_fight"): [
        ("final showdown with {boss} in {location}. {outcome}. corpo cleanup inbound.",
         {"boss": ["Arasaka division chief", "Militech black-ops commander",
                   "rogue Trauma Team Alpha leader", "MaxTac captain"],
          "location": _CP_LOCATIONS, "outcome": _OUTCOMES_WIN}),
    ],
    ("scifi", "cyberpunk_red", "exploration"): [
        ("ran the NET in {location}. {event}. extracted before trace completed.",
         {"location": ["Arasaka tower architecture", "Militech corporate ICE", "Pacifica black market node"],
          "event": ["found hidden data cache worth 15,000 eurobucks",
                    "tripped Black ICE — jacked out in time",
                    "located secret R&D files on new cyberware line"]}),
    ],
    ("scifi", "cyberpunk_red", "social"): [
        ("meeting with {contact} in {location}. {outcome}. street cred matters.",
         {"contact": ["fixer Rogue", "Wakako Okada", "a Maelstrom gang captain", "a Trauma Team dispatcher"],
          "location": _CP_LOCATIONS, "outcome": ["deal struck: 3000 eurobucks for the job",
                                                   "burned the contact — too dangerous",
                                                   "new job lined up: corporate extraction"]}),
    ],
    ("scifi", "cyberpunk_red", "loot"): [
        ("grabbed {loot} from {location}. fencer value: {value}.",
         {"loot": _CP_LOOT, "location": _CP_LOCATIONS,
          "value": ["12,000 eurobucks", "5,000 eurobucks", "8,500 eurobucks"]}),
    ],
    ("scifi", "cyberpunk_red", "rest"): [
        ("patched up at {location}. {mechanic}. {days} days downtime.",
         {"location": ["Viktor's ripper doc", "a No-Tell Motel in Watson", "the safehouse"],
          "mechanic": ["critical wound treated: -2 REF for 2 weeks",
                       "armor repaired — cost 500 eurobucks", "humanity regained: +2 EMP"],
          "days": ["1", "2", "3"]}),
    ],
    ("scifi", "cyberpunk_red", "quest_update"): [
        ("{contact} has a new gig: {quest}. payout: {payout}. risk: high.",
         {"contact": ["fixer Rogue", "Wakako", "the mysterious V"],
          "quest": ["extract scientist from Militech R&D",
                    "recover stolen Arasaka prototype from Maelstrom",
                    "plant evidence in NCPD precinct without getting caught"],
          "payout": ["5,000 eb", "8,000 eb", "12,000 eb + cyberware"]}),
    ],
    ("scifi", "cyberpunk_red", "character_development"): [
        ("raised {stat} to {val}. installed {cyberware}. humanity now {hum}.",
         {"stat": ["Interface", "Body", "Reflexes", "Cool"],
          "val": ["7", "8", "9", "10"],
          "cyberware": ["subdermal armor SP12", "Kiroshi Optics mk3",
                        "Smart Gun Link", "Neural Processor upgrade"],
          "hum": [str(i) for i in range(20, 80, 5)]}),
    ],
    ("scifi", "cyberpunk_red", "travel"): [
        ("drove {route}. {event}. {outcome}.",
         {"route": ["highway 17 through the Badlands", "Pacifica underpass",
                    "Watson to City Center via the freeway"],
          "event": ["NCPD checkpoint — talked our way through",
                    "ambushed by Wraiths on the highway",
                    "car broke down near the combat zone"],
          "outcome": _OUTCOMES_MIX}),
    ],
    ("scifi", "cyberpunk_red", "puzzle"): [
        ("bypassed {security} at {location}. {mechanic}. found {data}.",
         {"security": ["Arasaka biometric gate", "Militech ICE wall", "NCPD encrypted terminal"],
          "location": _CP_LOCATIONS,
          "mechanic": ["Interface 8 vs DV 16: success", "netrunner slaved the system remotely",
                       "forged credentials worked"],
          "data": ["evidence on NETwatch agent", "corporate hit list with our names on it",
                   "location of the hostage"]}),
    ],
    ("scifi", "cyberpunk_red", "world_event"): [
        ("{event}. Night City never sleeps but tonight it bled.",
         {"event": ["NUSA troops spotted massing outside city limits",
                    "Arasaka declared corporate war on Militech — again",
                    "major power outage hit Watson and Heywood",
                    "NETwatch shut down a rogue AI in the old Pacifica backbone"]}),
    ],
    ("scifi", "cyberpunk_red", "downtime"): [
        ("{days} days between jobs. {activity}. night city waits for no one.",
         {"days": ["2", "3", "5"],
          "activity": ["maintained cyberware and practiced quick-draw",
                       "ran minor NET jobs for street cred",
                       "laid low after the Arasaka incident"]}),
    ],

    # ── Sci-Fi / Shadowrun ────────────────────────────────────────────────
    ("scifi", "shadowrun", "combat"): [
        ("firefight with {enemy} at {location}. {mechanic}. {outcome}.",
         {"enemy": _SR_ENEMIES, "location": _SR_LOCATIONS, "mechanic": _SR_MECHANICS,
          "outcome": _OUTCOMES_MIX}),
    ],
    ("scifi", "shadowrun", "boss_fight"): [
        ("final run objective: {boss}. {mechanic}. {outcome}. Johnson paid in full.",
         {"boss": ["Aztechnology HTR commander", "the Renraku spider AI",
                   "a Blood Mage controlling the host"],
          "mechanic": _SR_MECHANICS, "outcome": _OUTCOMES_WIN}),
    ],
    ("scifi", "shadowrun", "exploration"): [
        ("scouted {location}. {mechanic}. astral recon showed {find}.",
         {"location": _SR_LOCATIONS, "mechanic": _SR_MECHANICS,
          "find": ["four spirits bound to the perimeter",
                   "a blood magic circle on the third floor",
                   "clean — no magical defenses"]}),
    ],
    ("scifi", "shadowrun", "social"): [
        ("met Johnson at {location}. negotiated terms. {mechanic}. run accepted.",
         {"location": ["a downtown bar", "a private Matrix host", "an anonymous commlink call"],
          "mechanic": _SR_MECHANICS}),
    ],
    ("scifi", "shadowrun", "loot"): [
        ("looted {loot} from {location}. fenced through {fence} for {value}.",
         {"loot": _SR_LOOT, "location": _SR_LOCATIONS,
          "fence": ["the Ork underground contact", "a Tir smuggler", "a Yakuza broker"],
          "value": ["8,000 nuyen", "15,000 nuyen", "22,000 nuyen"]}),
    ],
    ("scifi", "shadowrun", "rest"): [
        ("safehouse at {location}. {days} days. {mechanic}.",
         {"location": _SR_LOCATIONS, "days": ["2", "3"], "mechanic": _SR_MECHANICS}),
    ],
    ("scifi", "shadowrun", "quest_update"): [
        ("Johnson updated mission: {update}. deadline moved to {deadline}.",
         {"update": ["primary target has additional HTR backup",
                     "extract the data before the monthly audit",
                     "secondary target: eliminate the Renraku spider"],
          "deadline": ["48 hours", "dawn tomorrow", "before the quarterly board meeting"]}),
    ],
    ("scifi", "shadowrun", "character_development"): [
        ("karma spent: {advance}. {mechanic}. pushing toward {goal}.",
         {"advance": ["Strength 5 → 6", "Pilot Ground Craft +1", "Initiation Grade 2"],
          "mechanic": _SR_MECHANICS,
          "goal": ["Physical Adept mastery", "Elite Decker status", "Street Samurai peak"]}),
    ],
    ("scifi", "shadowrun", "travel"): [
        ("moved through {route}. {mechanic}. arrived at {destination} clean.",
         {"route": ["Ork underground tunnels", "the Barrens on foot", "a smuggler's ferry"],
          "mechanic": _SR_MECHANICS, "destination": _SR_LOCATIONS}),
    ],
    ("scifi", "shadowrun", "puzzle"): [
        ("host: {host}. {mechanic}. extracted {data} before the trace fired.",
         {"host": ["Renraku R5 corporate host", "Aztechnology encrypted node",
                   "UCAS government backbone"],
          "mechanic": _SR_MECHANICS,
          "data": ["personnel files on the target", "paydata worth 10,000 nuyen",
                   "evidence of illegal BTL manufacturing"]}),
    ],
    ("scifi", "shadowrun", "world_event"): [
        ("{event}. the corps don't blink. shadows just got darker.",
         {"event": ["Aztlan closed the Seattle border for 72 hours",
                    "a dragon was spotted circling the Renraku arcology",
                    "UCAS declared martial law in Redmond Barrens"]}),
    ],
    ("scifi", "shadowrun", "downtime"): [
        ("{days} days quiet. {activity}. {mechanic}.",
         {"days": ["3", "5"], "mechanic": _SR_MECHANICS,
          "activity": ["maintained contacts and gear", "ran matrix searches for the next Johnson"]}),
    ],

    # ── Horror / Call of Cthulhu ──────────────────────────────────────────
    ("horror", "call_of_cthulhu", "combat"): [
        ("confronted {entity} at {location}. {skill}. {outcome}. {sanity}.",
         {"entity": _COC_ENTITIES, "location": _COC_LOCATIONS, "skill": _COC_SKILLS,
          "outcome": _OUTCOMES_MIX, "sanity": _COC_SANITY}),
        ("fired on {entity}. {skill}. retreated to {location}. {sanity}.",
         {"entity": _COC_ENTITIES, "skill": _COC_SKILLS, "location": _COC_LOCATIONS,
          "sanity": _COC_SANITY}),
    ],
    ("horror", "call_of_cthulhu", "boss_fight"): [
        ("faced {entity} in the ritual chamber. {skill}. {sanity}. {outcome}.",
         {"entity": _COC_ENTITIES, "skill": _COC_SKILLS,
          "sanity": _COC_SANITY, "outcome": _OUTCOMES_MIX}),
    ],
    ("horror", "call_of_cthulhu", "exploration"): [
        ("investigated {location}. {skill}. found {clue}.",
         {"location": _COC_LOCATIONS, "skill": _COC_SKILLS, "clue": _COC_CLUES}),
        ("searched {location} for {clue}. {skill}. {sanity}.",
         {"location": _COC_LOCATIONS, "clue": _COC_CLUES, "skill": _COC_SKILLS,
          "sanity": _COC_SANITY}),
    ],
    ("horror", "call_of_cthulhu", "social"): [
        ("{skill} at the {location}. gained trust of {npc}. learned {info}.",
         {"skill": _COC_SKILLS, "location": _COC_LOCATIONS,
          "npc": ["the Innsmouth Selectman", "Professor Armitage", "the curator at Miskatonic",
                  "the old fisherman who knew too much"],
          "info": ["the layout of the ritual site", "the cult's schedule",
                   "the entity's weakness"]}),
    ],
    ("horror", "call_of_cthulhu", "loot"): [
        ("recovered {clue} from {location}. {sanity} just looking at it.",
         {"clue": _COC_CLUES, "location": _COC_LOCATIONS, "sanity": _COC_SANITY}),
    ],
    ("horror", "call_of_cthulhu", "rest"): [
        ("rested at {location}. {sanity} from the dream. woke {condition}.",
         {"location": _COC_LOCATIONS,
          "sanity": _COC_SANITY,
          "condition": ["drenched in sweat", "screaming", "catatonic for an hour",
                        "with a memory that wasn't there before"]}),
    ],
    ("horror", "call_of_cthulhu", "quest_update"): [
        ("telegram from {source}: {update}. must reach {location} before {deadline}.",
         {"source": ["Arkham Historical Society", "Professor Armitage", "an anonymous contact",
                     "the Miskatonic Rare Books division"],
          "update": ["the idol has been moved to Innsmouth",
                     "the ritual begins at the next lunar eclipse",
                     "the cult has identified our investigator"],
          "location": _COC_LOCATIONS,
          "deadline": ["sunrise", "the tide", "the new moon"]}),
    ],
    ("horror", "call_of_cthulhu", "character_development"): [
        ("skill improved: {skill_name} to {val}%. SAN now {san}. {reflection}.",
         {"skill_name": ["Firearms", "Library Use", "Cthulhu Mythos", "Psychology", "Occult"],
          "val": [str(i) for i in range(40, 90, 5)],
          "san": _COC_SAN_VAL,
          "reflection": ["starting to understand things I wish I didn't",
                         "the knowledge costs more than I expected",
                         "one more piece of the terrible puzzle"]}),
    ],
    ("horror", "call_of_cthulhu", "travel"): [
        ("drove to {location}. {event}. arrived unsettled.",
         {"location": _COC_LOCATIONS,
          "event": ["fog all the way — shapes in the mist",
                    "car stalled near the old cemetery",
                    "followed the whole route — grey sedan, never close",
                    "road washed out — had to walk the last mile"]}),
    ],
    ("horror", "call_of_cthulhu", "puzzle"): [
        ("deciphered {clue}. {skill}. revealed {revelation}. {sanity}.",
         {"clue": _COC_CLUES, "skill": _COC_SKILLS,
          "revelation": ["coordinates for the sunken city",
                          "the true name of the entity",
                          "the ritual to seal the rift",
                          "evidence that three local officials are cultists"],
          "sanity": _COC_SANITY}),
    ],
    ("horror", "call_of_cthulhu", "world_event"): [
        ("{event}. the newspapers say nothing. they never do.",
         {"event": ["seventeen people vanished from Innsmouth overnight",
                    "the university library's restricted section was ransacked",
                    "a fishing vessel found adrift — crew gone — strange markings on the hull",
                    "aurora borealis over Arkham — wrong time of year"]}),
    ],
    ("horror", "call_of_cthulhu", "downtime"): [
        ("library research for {days} days. {skill}. found {clue}. {sanity}.",
         {"days": ["2", "3", "5"], "skill": _COC_SKILLS,
          "clue": _COC_CLUES, "sanity": _COC_SANITY}),
    ],

    # ── Horror / World of Darkness ────────────────────────────────────────
    ("horror", "world_of_darkness", "combat"): [
        ("confronted {enemy} at {location}. {mechanic}. {outcome}.",
         {"enemy": _WOD_ENEMIES, "location": _WOD_LOCATIONS, "mechanic": _WOD_MECHANICS,
          "outcome": _OUTCOMES_MIX}),
    ],
    ("horror", "world_of_darkness", "boss_fight"): [
        ("faced {boss} in {location}. {mechanic}. barely escaped with our immortality.",
         {"boss": ["the Tremere primogen", "a werewolf pack alpha", "the Sabbat archbishop"],
          "location": _WOD_LOCATIONS, "mechanic": _WOD_MECHANICS}),
    ],
    ("horror", "world_of_darkness", "exploration"): [
        ("investigated {location}. found {find}. {mechanic}.",
         {"location": _WOD_LOCATIONS,
          "find": ["evidence of Sabbat ritual activity", "a mortal hunter's surveillance log",
                   "letters from the Second Inquisition", "a bound ghost haunting the premises"],
          "mechanic": _WOD_MECHANICS}),
    ],
    ("horror", "world_of_darkness", "social"): [
        ("audience with {npc} at {location}. {mechanic}. {outcome}.",
         {"npc": ["the Prince", "the Sheriff", "a Nosferatu information broker",
                  "a Tremere regent", "the Anarch baron"],
          "location": _WOD_LOCATIONS, "mechanic": _WOD_MECHANICS,
          "outcome": ["boon granted", "blood hunt rescinded", "domain access denied",
                      "alliance forged with the Anarchs"]}),
    ],
    ("horror", "world_of_darkness", "loot"): [
        ("acquired {loot} from {location}. {mechanic}.",
         {"loot": _WOD_LOOT, "location": _WOD_LOCATIONS, "mechanic": _WOD_MECHANICS}),
    ],
    ("horror", "world_of_darkness", "rest"): [
        ("daysleep at {location}. {event}. rose with {feeling}.",
         {"location": _WOD_LOCATIONS,
          "event": ["hunters probing the building — held still", "a dream of the First City",
                    "ghoul guard reported no incidents"],
          "feeling": ["the hunger", "purpose", "dread of what comes next"]}),
    ],
    ("horror", "world_of_darkness", "quest_update"): [
        ("{npc} issued directive: {quest}. timeline: {deadline}. non-compliance: {consequence}.",
         {"npc": ["the Prince", "the Primogen Council", "the Anarchs"],
          "quest": ["blood hunt — rogue Nosferatu operating without domain rights",
                    "identify the Second Inquisition mole in the court",
                    "recover the stolen Tremere formula before rivals weaponize it"],
          "deadline": ["before the next Elysium", "within one moon cycle"],
          "consequence": ["final death", "loss of domain", "exile from the city"]}),
    ],
    ("horror", "world_of_darkness", "character_development"): [
        ("raised {discipline} to {val}. {mechanic}. humanity sits at {hum}.",
         {"discipline": ["Presence", "Dominate", "Obfuscate", "Protean", "Blood Sorcery"],
          "val": ["3", "4", "5"],
          "mechanic": _WOD_MECHANICS,
          "hum": _WOD_HUM}),
    ],
    ("horror", "world_of_darkness", "travel"): [
        ("traveled by night from {from_loc} to {to_loc}. {event}.",
         {"from_loc": _WOD_LOCATIONS, "to_loc": _WOD_LOCATIONS,
          "event": ["Lupine territory on the highway — detoured through sewers",
                    "hunter vehicle tailed us for twelve blocks — lost them",
                    "arrived with only an hour before dawn"]}),
    ],
    ("horror", "world_of_darkness", "puzzle"): [
        ("traced {breach} to {culprit}. {mechanic}. reported to {authority}.",
         {"breach": ["Masquerade violation", "blood hunt leak", "Second Inquisition tip-off"],
          "culprit": ["a careless neonate", "a mortal pawn turned double agent",
                      "a rival coterie covering their tracks"],
          "mechanic": _WOD_MECHANICS,
          "authority": ["the Sheriff", "the Prince", "the Anarchs"]}),
    ],
    ("horror", "world_of_darkness", "world_event"): [
        ("{event}. the Masquerade strains. gehenna whispers grow louder.",
         {"event": ["Second Inquisition raided an Elysium in Berlin — our city on notice",
                    "an elder went into torpor without explanation",
                    "Anarch uprising brewing in the outer boroughs",
                    "a Sabbat pack executed three Camarilla ancillae"]}),
    ],
    ("horror", "world_of_darkness", "downtime"): [
        ("{days} nights of quiet. {activity}. the city breathes. we don't.",
         {"days": ["3", "5", "7"],
          "activity": ["cultivated mortal herd of willing vessels",
                       "maintained haven security upgrades",
                       "worked contacts for intelligence on the rival coterie"]}),
    ],

    # ── Video Game / Elden Ring ───────────────────────────────────────────
    ("videogame", "elden_ring", "boss_fight"): [
        ("{boss} defeated. {attempts} attempts. {build} + {summon}. {feeling}.",
         {"boss": _ER_BOSSES, "attempts": _ER_ATTEMPTS, "build": _ER_BUILDS,
          "summon": ["Mimic Tear", "Black Knife Tiche", "Lhutel the Headless", "no summon — honor run"],
          "feeling": ["best feeling in gaming", "finally free of this torment",
                      "absolutely destroyed me then I destroyed it back",
                      "can't believe it's over"]}),
        ("{boss} at {location}. {attempts} tries. {build}. {notes}.",
         {"boss": _ER_BOSSES, "location": _ER_LOCATIONS, "attempts": _ER_ATTEMPTS,
          "build": _ER_BUILDS,
          "notes": ["second phase wall is brutal", "stay aggressive — don't let it breathe",
                    "jump attack on the wind-up telegraphs everything"]}),
    ],
    ("videogame", "elden_ring", "exploration"): [
        ("explored {location}. found {loot}. {event}.",
         {"location": _ER_LOCATIONS, "loot": _ER_LOOT,
          "event": ["invaded by a red phantom — won", "grace site discovered — rested",
                    "fell off a ledge — lost 40,000 runes",
                    "questline NPC found here unexpectedly"]}),
        ("discovered {location} via {method}. {loot} at the end.",
         {"location": _ER_LOCATIONS,
          "method": ["a sending gate", "a hidden cave entrance", "Torrent jumping the gap"],
          "loot": _ER_LOOT}),
    ],
    ("videogame", "elden_ring", "social"): [
        ("met {npc} at {location}. {event}. questline progressed.",
         {"npc": ["Ranni the Witch", "Blaidd the Half-Wolf", "Millicent", "Nepheli Loux",
                  "Patches", "Alexander the Jar", "Fia"],
          "location": _ER_LOCATIONS,
          "event": ["received item", "heard lore about the Shattering",
                    "unlocked new merchant inventory", "triggered invasion warning"]}),
    ],
    ("videogame", "elden_ring", "loot"): [
        ("obtained {loot} in {location}. upgraded to +{level}. {effect}.",
         {"loot": _ER_LOOT, "location": _ER_LOCATIONS,
          "level": ["15", "20", "25", "+10 standard"],
          "effect": ["build-defining", "changed the entire approach",
                     "immediate swap — never going back"]}),
    ],
    ("videogame", "elden_ring", "rest"): [
        ("rested at grace near {location}. {event}.",
         {"location": _ER_LOCATIONS,
          "event": ["Melina appeared — offered to level up",
                    "respec'd using Larval Tear",
                    "site of grace added to fast travel",
                    "teleported by sending gate — surprise"]}),
    ],
    ("videogame", "elden_ring", "quest_update"): [
        ("{npc} questline update: {update}. must complete before {deadline}.",
         {"npc": ["Ranni", "Millicent", "Nepheli", "Alexander", "Fia"],
          "update": ["moved to the Haligtree", "waiting at the volcano manor",
                     "item needed: Unalloyed Gold Needle", "boss must die first"],
          "deadline": ["killing Morgott", "completing Ranni's quest", "reaching Farum Azula"]}),
    ],
    ("videogame", "elden_ring", "character_development"): [
        ("reached level {level}. {build} fully online. {achievement}.",
         {"level": _ER_LEVELS, "build": _ER_BUILDS,
          "achievement": ["RL1 run is actually viable now",
                          "first time breaking 80 poise — feels amazing",
                          "sorcery build peak: 3000 damage per comet"]}),
    ],
    ("videogame", "elden_ring", "travel"): [
        ("rode Torrent from {from_loc} to {to_loc}. {event}.",
         {"from_loc": _ER_LOCATIONS, "to_loc": _ER_LOCATIONS,
          "event": ["ambushed by three crucible knights — ran",
                    "Erdtree Avatar blocked the path",
                    "rot scarabs everywhere in Caelid",
                    "spectral jellyfish descent found"]}),
    ],
    ("videogame", "elden_ring", "puzzle"): [
        ("puzzle at {location}: {puzzle}. solution: {solution}.",
         {"location": _ER_LOCATIONS,
          "puzzle": ["Carian Study Hall inversion", "painting phantom location",
                     "stonesword key seal", "Siofra River well puzzle"],
          "solution": ["Celestial Dew used", "Imbued Stonesword Key",
                       "found the phantom in Heretical Rise",
                       "lit all flames in sequence"]}),
    ],
    ("videogame", "elden_ring", "world_event"): [
        ("{event}. the Lands Between shift.",
         {"event": ["Radahn defeated — stars falling again, Nokron accessible",
                    "Age of Fracture ending unlocked",
                    "Ranni's questline complete — Age of Stars triggered",
                    "the Erdtree burned — Farum Azula accessible"]}),
    ],
    ("videogame", "elden_ring", "downtime"): [
        ("farming at {location}. {yield} runes per run. upgraded {weapon} to +{level}.",
         {"location": ["Mohgwyn Palace", "the Palace Approach Ledge Road", "Caelid Bird"],
          "yield": ["80,000", "160,000", "400,000", "30,000"],
          "weapon": ["Rivers of Blood", "Moonveil", "Giant-Crusher", "Bloodhound's Fang"],
          "level": ["20", "25", "+10"]}),
    ],

    # ── Video Game / Final Fantasy ────────────────────────────────────────
    ("videogame", "final_fantasy", "boss_fight"): [
        ("{boss} cleared. {mechanic}.",
         {"boss": _FF_BOSSES, "mechanic": [m.format(pulls=random.choice(_FF_PULLS),
                                                      pct=random.choice(_FF_PCT),
                                                      item=random.choice(_FF_ITEMS))
                                            for m in _FF_MECHANICS]}),
    ],
    ("videogame", "final_fantasy", "combat"): [
        ("savage floor {floor}. {mechanic}. {role} was the bottleneck.",
         {"floor": ["1", "2", "3", "4"],
          "mechanic": [m.format(pulls=random.choice(_FF_PULLS), pct=random.choice(_FF_PCT),
                                item=random.choice(_FF_ITEMS)) for m in _FF_MECHANICS],
          "role": _FF_ROLES}),
    ],
    ("videogame", "final_fantasy", "exploration"): [
        ("explored {area}. found {discovery}. aether current unlocked.",
         {"area": ["Mor Dhona", "the Dravanian Hinterlands", "Azys Lla", "the Azim Steppe",
                   "Il Mheg", "Amaurot"],
          "discovery": ["new side quest", "lore scroll", "FATE chain", "hidden aether current"]}),
    ],
    ("videogame", "final_fantasy", "social"): [
        ("story cutscene: {event}. {character} moment. no spoilers but {reaction}.",
         {"event": ["major MSQ reveal", "alliance raid story conclusion", "trust NPC moment"],
          "character": ["Alphinaud", "Y'shtola", "Emet-Selch", "Venat", "Estinien"],
          "reaction": ["cried", "didn't breathe for five minutes",
                       "had to step away", "immediately called a friend"]}),
    ],
    ("videogame", "final_fantasy", "loot"): [
        ("obtained {loot} from {source}. BiS for {slot}.",
         {"loot": _FF_ITEMS, "source": ["savage chest", "tome exchange", "crafted"],
          "slot": ["weapon", "chest", "accessories", "ring"]}),
    ],
    ("videogame", "final_fantasy", "character_development"): [
        ("crafted full {tier} set. melded {materia}. ilvl now {ilvl}.",
         {"tier": ["i640", "i650", "i660", "i670"],
          "materia": ["Tier 8 crit", "Tier 8 direct hit", "Tier 8 det"],
          "ilvl": ["640", "650", "660", "670"]}),
    ],
    ("videogame", "final_fantasy", "rest"): [
        ("logged at {location}. turned in {content}.",
         {"location": ["Revenant's toll", "Limsa Lominsa", "Rising Stones", "Ishgard"],
          "content": ["challenge log", "weekly capped tomes", "daily roulettes"]}),
    ],
    ("videogame", "final_fantasy", "quest_update"): [
        ("MSQ update: {update}. met {npc} at {location}.",
         {"update": ["the forum accepts our aid", "the enemy's plan revealed",
                     "Ishgard's gates open", "Scions split up"],
          "npc": ["Alphinaud", "Ysayle", "Aymeric", "Minfilia"],
          "location": ["the Solar", "Ishgard", "the Rising Stones", "Camp Dragonhead"]}),
    ],
    ("videogame", "final_fantasy", "travel"): [
        ("aetheryte to {location}. gil cost: {gil}. {event}.",
         {"location": ["Ishgard", "Idyllshire", "Azys Lla aether", "Rhalgr's Reach"],
          "gil": ["150", "225", "180"],
          "event": ["FATE chain active nearby", "saw a 24-man raid forming in party finder",
                    "spotted a housing plot finally available"]}),
    ],
    ("videogame", "final_fantasy", "puzzle"): [
        ("all saints' wake puzzle: {puzzle}. {mechanic}. reward: {reward}.",
         {"puzzle": ["lantern riddle solved", "music box sequence figured out",
                     "maze navigation complete"],
          "mechanic": [m.format(pulls=random.choice(_FF_PULLS), pct=random.choice(_FF_PCT),
                                item=random.choice(_FF_ITEMS)) for m in _FF_MECHANICS],
          "reward": ["event minion", "seasonal mount", "orchestrion roll"]}),
    ],
    ("videogame", "final_fantasy", "world_event"): [
        ("{event}. the shard trembles. we march on.",
         {"event": ["Hydaelyn's blessing fading", "the Final Days begin in earnest",
                    "Zodiark unbound", "the Scions are separated across the First"]}),
    ],
    ("videogame", "final_fantasy", "downtime"): [
        ("retainer ventures sent. {crafting}. housing garden tended.",
         {"crafting": ["crafting rotation optimized for HQ i640 gear",
                       "gathered collectibles for scrip",
                       "fishing daily quota completed"]}),
    ],

    # ── Video Game / World of Warcraft ────────────────────────────────────
    ("videogame", "world_of_warcraft", "boss_fight"): [
        ("{boss} — mythic progression. {mechanic}. {outcome}.",
         {"boss": _WOW_BOSSES,
          "mechanic": [m.format(wipes=random.choice(_WOW_WIPES), rank=random.choice(_WOW_RANK),
                                sec=random.choice(_WOW_SEC), pct=random.choice(_WOW_PCT))
                       for m in _WOW_MECHANICS],
          "outcome": _OUTCOMES_MIX}),
    ],
    ("videogame", "world_of_warcraft", "combat"): [
        ("mythic+ {key} — {dungeon}. {mechanic}. {outcome}.",
         {"key": _WOW_KEYS, "dungeon": ["Halls of Valor", "Siege of Boralus", "Uldaman", "Neltharus",
                                          "The Nokhud Offensive", "Brackenhide Hollow"],
          "mechanic": [m.format(wipes=random.choice(_WOW_WIPES), rank=random.choice(_WOW_RANK),
                                sec=random.choice(_WOW_SEC), pct=random.choice(_WOW_PCT))
                       for m in _WOW_MECHANICS],
          "outcome": _OUTCOMES_MIX}),
    ],
    ("videogame", "world_of_warcraft", "loot"): [
        ("vault this week: {loot}. {mechanic}.",
         {"loot": _WOW_LOOT,
          "mechanic": [m.format(wipes=random.choice(_WOW_WIPES), rank=random.choice(_WOW_RANK),
                                sec=random.choice(_WOW_SEC), pct=random.choice(_WOW_PCT))
                       for m in _WOW_MECHANICS]}),
    ],
    ("videogame", "world_of_warcraft", "quest_update"): [
        ("campaign chapter {chapter}: {event}. {npc} sends us to {location}.",
         {"chapter": [str(i) for i in range(1, 12)],
          "event": ["the siege of Orgrimmar revealed", "the Jailer's plan exposed",
                    "Anduin falls to shadow"],
          "npc": ["Thrall", "Jaina", "Sylvanas", "Uther"],
          "location": ["Maldraxxus", "the Sanctum of Domination",
                       "the Sepulcher of the First Ones"]}),
    ],
    ("videogame", "world_of_warcraft", "character_development"): [
        ("ilvl hit {ilvl}. talent tree revised for {spec}. {mechanic}.",
         {"ilvl": [str(i) for i in range(390, 480, 10)],
          "spec": ["Fury Warrior", "Resto Druid", "Fire Mage", "Affliction Warlock"],
          "mechanic": [m.format(wipes=random.choice(_WOW_WIPES), rank=random.choice(_WOW_RANK),
                                sec=random.choice(_WOW_SEC), pct=random.choice(_WOW_PCT))
                       for m in _WOW_MECHANICS]}),
    ],
    ("videogame", "world_of_warcraft", "rest"): [
        ("logged after raid. {activity}.",
         {"activity": ["checked logs — purple parse on Fyrakk",
                       "sent followers on missions", "checked AH for cheap mats"]}),
    ],
    ("videogame", "world_of_warcraft", "exploration"): [
        ("explored {zone}. {event}.",
         {"zone": ["the Azure Span", "Ohn'ahran Plains", "Thaldraszus", "the Forbidden Reach"],
          "event": ["rare mount found", "hidden questline triggered",
                    "world quest chain discovered", "dragon glyph collected"]}),
    ],
    ("videogame", "world_of_warcraft", "social"): [
        ("guild meeting on Discord. {decision}. team morale {mood}.",
         {"decision": ["roster locked for tier race", "new loot rules voted in",
                       "alt runs scheduled for Sunday"],
          "mood": ["high after the kill", "tense after a bad raid week", "solid"]}),
    ],
    ("videogame", "world_of_warcraft", "travel"): [
        ("flew from {from_loc} to {to_loc}. {event}.",
         {"from_loc": ["Valdrakken", "Oribos", "Stormwind"],
          "to_loc": ["the Seat of the Aspects", "the Sepulcher", "Ny'alotha"],
          "event": ["mounted up on drake — finally", "flight path felt eternal",
                    "new flight path unlocked"]}),
    ],
    ("videogame", "world_of_warcraft", "puzzle"): [
        ("puzzle {name}: {mechanic}. reward: {loot}.",
         {"name": ["forbidden reach rune puzzle", "Zereth Mortis cipher", "dragonscale expedition lore"],
          "mechanic": [m.format(wipes="1", rank="guild first", sec="4", pct="85")
                       for m in _WOW_MECHANICS],
          "loot": _WOW_LOOT}),
    ],
    ("videogame", "world_of_warcraft", "world_event"): [
        ("{event}. servers crashed shortly after. classic.",
         {"event": ["patch 10.2 dropped — new raid tier live",
                    "faction leader died in cinematic — Twitter erupted",
                    "world boss killed by world first guild 47 minutes after servers opened"]}),
    ],
    ("videogame", "world_of_warcraft", "downtime"): [
        ("weekly chores done. {activities}.",
         {"activities": ["capped valor, sent followers, herb farming in the Azure Span",
                         "completed all 8 world quests and sold the loot",
                         "leveled alt tank to 70 for next tier"]}),
    ],

    # ── Video Game / Baldur's Gate 3 ──────────────────────────────────────
    ("videogame", "baldurs_gate", "boss_fight"): [
        ("{boss} fight at {location}. {choice}. {outcome}.",
         {"boss": ["Ketheric Thorm", "Orin the Red", "Gortash", "Cazador", "the Netherbrain"],
          "location": _BG3_LOCATIONS, "choice": _BG3_CHOICES, "outcome": _OUTCOMES_WIN}),
    ],
    ("videogame", "baldurs_gate", "combat"): [
        ("encounter in {location}. {choice}. {outcome}.",
         {"location": _BG3_LOCATIONS, "choice": _BG3_CHOICES, "outcome": _OUTCOMES_MIX}),
    ],
    ("videogame", "baldurs_gate", "social"): [
        ("dialogue with {companion}. {choice}. {companion} approval: +{pts}.",
         {"companion": _BG3_COMPANIONS, "choice": _BG3_CHOICES,
          "pts": _BG3_PTS}),
    ],
    ("videogame", "baldurs_gate", "loot"): [
        ("looted {location}. found {loot}. {companion} immediately equipped it.",
         {"location": _BG3_LOCATIONS,
          "loot": ["Amulet of Greater Health", "Nyrulna", "Helldusk Armor",
                   "Ring of Regeneration", "Gloves of Dexterity"],
          "companion": _BG3_COMPANIONS}),
    ],
    ("videogame", "baldurs_gate", "rest"): [
        ("camp rest. {companion} had dialogue. {event}.",
         {"companion": _BG3_COMPANIONS,
          "event": ["romance scene triggered", "nightmare sequence about the tadpole",
                    "Withers offered respec — took it", "Gale ate another artifact"]}),
    ],
    ("videogame", "baldurs_gate", "character_development"): [
        ("leveled up. {class_feature}. {choice}.",
         {"class_feature": ["Sorcerer: Quicken Spell metamagic", "Paladin: Aura of Protection",
                             "Rogue: Uncanny Dodge", "Fighter: Extra Attack (2)"],
          "choice": _BG3_CHOICES}),
    ],
    ("videogame", "baldurs_gate", "exploration"): [
        ("explored {location}. {event}. {choice}.",
         {"location": _BG3_LOCATIONS,
          "event": ["hidden room found", "Speak with Dead on a key NPC",
                    "side quest discovered", "illithid parasite puzzle"],
          "choice": _BG3_CHOICES}),
    ],
    ("videogame", "baldurs_gate", "quest_update"): [
        ("quest updated: {quest}. {companion} has input. {choice}.",
         {"quest": ["find the nightsong", "stop the absolute", "save the refugees",
                    "confront the elder brain"],
          "companion": _BG3_COMPANIONS, "choice": _BG3_CHOICES}),
    ],
    ("videogame", "baldurs_gate", "travel"): [
        ("traveled to {location} via {method}. {event}.",
         {"location": _BG3_LOCATIONS,
          "method": ["fast travel", "the Underdark path", "the mountain pass"],
          "event": ["ambush triggered", "random encounter with survivors",
                    "crossed into Act 2 — tone shifted immediately"]}),
    ],
    ("videogame", "baldurs_gate", "puzzle"): [
        ("puzzle at {location}: {puzzle}. {choice}. reward: {loot}.",
         {"location": _BG3_LOCATIONS,
          "puzzle": ["Defiled Temple moon dial", "Underdark elevator sequence",
                     "Arcane Tower generator puzzle"],
          "choice": _BG3_CHOICES,
          "loot": ["Spiderstep Boots", "Mourning Frost", "Phalar Aluve"]}),
    ],
    ("videogame", "baldurs_gate", "world_event"): [
        ("{event}. {companion} reacted to this immediately.",
         {"event": ["the Absolute revealed as the three chosen",
                    "Ketheric Thorm transformed — second phase",
                    "Moonrise Towers fell — tieflings freed",
                    "the Netherbrain spoke through the tadpole"],
          "companion": _BG3_COMPANIONS}),
    ],
    ("videogame", "baldurs_gate", "downtime"): [
        ("camp downtime. {activity}. {companion} had something to say about it.",
         {"activity": ["respecced the whole party", "sold loot in Baldur's Gate",
                       "crafted scrolls and potions for the final fight"],
          "companion": _BG3_COMPANIONS}),
    ],

    # ── Other / Generic ───────────────────────────────────────────────────
    ("other", "generic", "combat"): [
        ("fierce battle with {opponent}. {outcome}.",
         {"opponent": ["three armed opponents", "a rival faction", "an overwhelming force",
                       "a dangerous foe we'd been tracking"],
          "outcome": _OUTCOMES_MIX}),
    ],
    ("other", "generic", "exploration"): [
        ("discovered {place}. {event}.",
         {"place": ["a hidden area beyond the old gate", "an abandoned structure",
                    "an unmarked location on the map"],
          "event": ["evidence of prior occupants", "valuable resources found",
                    "clues about the larger mystery"]}),
    ],
    ("other", "generic", "social"): [
        ("difficult conversation with {person}. {outcome}.",
         {"person": ["the group leader", "an old ally turned suspicious", "a neutral party"],
          "outcome": ["reached an uneasy agreement", "burned a bridge", "gained new information"]}),
    ],
    ("other", "generic", "boss_fight"): [
        ("final confrontation with {opponent}. hard-fought victory. {cost}.",
         {"opponent": ["the main antagonist", "the faction leader", "the source of the problem"],
          "cost": ["not without losses", "everyone survived", "one ally seriously hurt"]}),
    ],
    ("other", "generic", "loot"): [
        ("found {item} at {place}. worth pursuing further.",
         {"item": ["valuable resources", "key information", "a critical tool"],
          "place": ["the abandoned location", "the enemy's base", "the hidden cache"]}),
    ],
    ("other", "generic", "rest"): [
        ("quiet period. {activity}. morale improved.",
         {"activity": ["assessed injuries", "planned next steps", "resupplied"]}),
    ],
    ("other", "generic", "quest_update"): [
        ("new objective: {objective}. deadline: {deadline}.",
         {"objective": ["reach the destination before nightfall",
                        "neutralize the threat before it escalates",
                        "gather intelligence on the opposing faction"],
          "deadline": ["48 hours", "before the next phase", "immediately"]}),
    ],
    ("other", "generic", "character_development"): [
        ("significant milestone: {achievement}. new capability: {ability}.",
         {"achievement": ["first major victory", "trust earned from key ally", "critical skill mastered"],
          "ability": ["new approach available", "unlocked new contacts", "increased effectiveness"]}),
    ],
    ("other", "generic", "world_event"): [
        ("major revelation: {event}. {impact}.",
         {"event": ["the true nature of the threat revealed",
                    "an ally exposed as working against us",
                    "the scale of the problem is larger than expected"],
          "impact": ["everything changes now", "nothing is what it seemed",
                     "the mission just got harder"]}),
    ],
    ("other", "generic", "travel"): [
        ("long journey to {destination}. {event}. arrived {condition}.",
         {"destination": ["the objective", "the next location", "unfamiliar territory"],
          "event": ["unexpected complication en route", "a chance encounter",
                    "uneventful but exhausting"],
          "condition": ["on time", "delayed", "with new information"]}),
    ],
    ("other", "generic", "puzzle"): [
        ("complex problem: {problem}. solution: {solution}. cost: {cost}.",
         {"problem": ["locked mechanism", "coded message", "multi-step security system"],
          "solution": ["worked around it", "brute forced after analysis", "found the pattern"],
          "cost": ["time lost", "resources spent", "minimal — clean solve"]}),
    ],
    ("other", "generic", "downtime"): [
        ("quiet interval. {activity}. prepared for what comes next.",
         {"activity": ["planned and resupplied", "gathered intelligence passively",
                       "maintained equipment and relationships"]}),
    ],
}

# ---------------------------------------------------------------------------
# Genre/system metadata
# ---------------------------------------------------------------------------

GENRE_SYSTEMS: dict[str, list[str]] = {
    "fantasy": ["dnd_5e", "pathfinder_2e", "warhammer_fantasy", "generic"],
    "scifi": ["starfinder", "cyberpunk_red", "shadowrun", "generic"],
    "horror": ["call_of_cthulhu", "world_of_darkness", "generic"],
    "videogame": ["elden_ring", "final_fantasy", "world_of_warcraft", "baldurs_gate", "generic"],
    "other": ["generic"],
}

ALL_SCENARIO_TYPES = [
    "combat", "exploration", "social", "loot", "rest",
    "quest_update", "boss_fight", "character_development",
    "world_event", "travel", "puzzle", "downtime",
]

# ---------------------------------------------------------------------------
# Shorthand generation
# ---------------------------------------------------------------------------

def fill_template(template: str, vocab: dict) -> str:
    result = template
    for key, options in vocab.items():
        placeholder = f"{{{key}}}"
        while placeholder in result:
            result = result.replace(placeholder, random.choice(options), 1)
    return result


def generate_shorthand(genre: str, system: str, scenario: str) -> str | None:
    key = (genre, system, scenario)
    entries = TEMPLATES.get(key)
    if not entries:
        return None
    template, vocab = random.choice(entries)
    return fill_template(template, vocab)


def get_instruction(genre: str, system: str) -> str:
    return SYSTEM_PROMPTS.get(
        (genre, system),
        SYSTEM_PROMPTS.get((genre, "generic"), SYSTEM_PROMPTS[("other", "generic")])
    )

# ---------------------------------------------------------------------------
# LLM providers — all synchronous via httpx
# ---------------------------------------------------------------------------

def _narrative_kobold(shorthand: str, instruction: str, kobold_url: str,
                       temperature: float, max_tokens: int) -> str:
    prompt = f"{instruction}\n\nInput: {shorthand}\nOutput:"
    payload = {
        "prompt": prompt,
        "max_length": max_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        "stop_sequence": ["\nInput:"],
        "rep_pen": 1.1,
    }
    r = httpx.post(f"{kobold_url.rstrip('/')}/api/v1/generate", json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["results"][0]["text"].strip()


def _narrative_openai(shorthand: str, instruction: str, api_key: str, model: str,
                       temperature: float, max_tokens: int) -> str:
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": f"Input: {shorthand}\nOutput:"},
    ]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
    r = httpx.post("https://api.openai.com/v1/chat/completions",
                    json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _narrative_anthropic(shorthand: str, instruction: str, api_key: str, model: str,
                          temperature: float, max_tokens: int) -> str:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": instruction,
        "messages": [{"role": "user", "content": f"Input: {shorthand}\nOutput:"}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    r = httpx.post("https://api.anthropic.com/v1/messages",
                    json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def _narrative_gemini(shorthand: str, instruction: str, api_key: str, model: str,
                       temperature: float, max_tokens: int) -> str:
    payload = {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user",
                       "parts": [{"text": f"Input: {shorthand}\nOutput:"}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = httpx.post(url, json=payload, params={"key": api_key}, timeout=60)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_narrative(shorthand: str, instruction: str, args: argparse.Namespace) -> str:
    """Route to the appropriate provider and return the narrative text."""
    provider = args.provider
    temperature = args.temperature
    max_tokens = args.max_tokens

    if provider == "kobold":
        return _narrative_kobold(shorthand, instruction, args.kobold_url, temperature, max_tokens)
    if provider == "openai":
        return _narrative_openai(shorthand, instruction, args.api_key,
                                  args.model or "gpt-4o-mini", temperature, max_tokens)
    if provider == "anthropic":
        return _narrative_anthropic(shorthand, instruction, args.api_key,
                                     args.model or "claude-haiku-4-5-20251001", temperature, max_tokens)
    if provider == "gemini":
        return _narrative_gemini(shorthand, instruction, args.api_key,
                                  args.model or "gemini-1.5-flash", temperature, max_tokens)
    raise ValueError(f"Unknown provider: {provider}")

# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------

async def save_to_db(records: list[dict], db_url: str) -> None:
    import asyncpg
    pg_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(pg_url)
    try:
        await conn.executemany(
            """
            INSERT INTO training_samples
                (id, genre, game_system, scenario_type, instruction, shorthand, narrative,
                 is_validated, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, false, $8, $8)
            """,
            [
                (
                    str(uuid.uuid4()),
                    r["genre"],
                    r["game_system"],
                    r["scenario_type"],
                    r["instruction"],
                    r["shorthand"],
                    r.get("narrative") or None,
                    datetime.now(timezone.utc),
                )
                for r in records
            ],
        )
        print(f"  Saved {len(records)} records to database.")
    finally:
        await conn.close()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate shorthand→narrative training pairs.")
    p.add_argument("--genre", default="all",
                    choices=list(GENRE_SYSTEMS.keys()) + ["all"])
    p.add_argument("--system", default="all",
                    help="Game system slug or 'all' for all systems within the genre.")
    p.add_argument("--scenario", default="all",
                    choices=ALL_SCENARIO_TYPES + ["all"])
    p.add_argument("--count", type=int, default=5,
                    help="Samples per genre/system/scenario combination.")
    p.add_argument("--generate-narratives", action="store_true",
                    help="Call an LLM to fill the narrative (output) field.")
    p.add_argument("--provider", default="kobold",
                    choices=["kobold", "openai", "anthropic", "gemini"])
    p.add_argument("--api-key", default=None,
                    help="API key for cloud providers (openai/anthropic/gemini).")
    p.add_argument("--model", default=None,
                    help="Model override. Defaults: openai→gpt-4o-mini, "
                         "anthropic→claude-haiku-4-5-20251001, gemini→gemini-1.5-flash.")
    p.add_argument("--kobold-url", default="http://localhost:5001")
    p.add_argument("--temperature", type=float, default=0.72)
    p.add_argument("--max-tokens", type=int, default=600)
    p.add_argument("--output-dir", default="../data/raw",
                    help="Directory for JSONL output. Skipped if --no-jsonl is set.")
    p.add_argument("--no-jsonl", action="store_true",
                    help="Skip writing JSONL files.")
    p.add_argument("--save-to-db", action="store_true",
                    help="Persist records to PostgreSQL.")
    p.add_argument("--db-url", default=None,
                    help="PostgreSQL URL. Falls back to DATABASE_URL env var.")
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    if args.save_to_db and not (args.db_url or os.environ.get("DATABASE_URL")):
        print("ERROR: --save-to-db requires --db-url or DATABASE_URL env var.")
        return

    if args.generate_narratives and args.provider != "kobold" and not args.api_key:
        print(f"ERROR: --provider {args.provider} requires --api-key.")
        return

    genres = list(GENRE_SYSTEMS.keys()) if args.genre == "all" else [args.genre]
    scenarios = ALL_SCENARIO_TYPES if args.scenario == "all" else [args.scenario]

    out_dir = Path(args.output_dir) if not args.no_jsonl else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    db_url = args.db_url or os.environ.get("DATABASE_URL", "")

    total_generated = 0
    total_narrated = 0
    total_errors = 0

    for genre in genres:
        systems = GENRE_SYSTEMS[genre]
        if args.system != "all":
            systems = [s for s in systems if s == args.system]
            if not systems:
                print(f"  WARNING: system '{args.system}' not found under genre '{genre}'.")
                continue

        for system in systems:
            all_records: list[dict] = []

            for scenario in scenarios:
                key = (genre, system, scenario)
                if key not in TEMPLATES:
                    continue

                instruction = get_instruction(genre, system)
                combo_records: list[dict] = []

                for _ in range(args.count):
                    shorthand = generate_shorthand(genre, system, scenario)
                    if not shorthand:
                        continue

                    record: dict = {
                        "genre": genre,
                        "game_system": system,
                        "scenario_type": scenario,
                        "instruction": instruction,
                        "input": shorthand,
                        "output": "",
                    }

                    if args.generate_narratives:
                        try:
                            narrative = generate_narrative(shorthand, instruction, args)
                            record["output"] = narrative
                            total_narrated += 1
                        except Exception as exc:
                            print(f"    [WARN] narrative failed ({genre}/{system}/{scenario}): {exc}")
                            total_errors += 1

                    combo_records.append(record)
                    total_generated += 1

                all_records.extend(combo_records)
                print(f"  {genre}/{system}/{scenario}: {len(combo_records)} samples"
                      + (f" ({sum(1 for r in combo_records if r['output'])} narrated)"
                         if args.generate_narratives else ""))

            if not all_records:
                continue

            if out_dir:
                out_file = out_dir / f"{genre}_{system}.jsonl"
                mode = "a"  # append so multiple runs accumulate
                with open(out_file, mode) as f:
                    for r in all_records:
                        f.write(json.dumps({
                            "genre": r["genre"],
                            "game_system": r["game_system"],
                            "scenario_type": r["scenario_type"],
                            "instruction": r["instruction"],
                            "input": r["input"],
                            "output": r["output"],
                        }) + "\n")
                print(f"  → {out_file} (+{len(all_records)} records)")

            if args.save_to_db:
                db_records = [
                    {
                        "genre": r["genre"],
                        "game_system": r["game_system"],
                        "scenario_type": r["scenario_type"],
                        "instruction": r["instruction"],
                        "shorthand": r["input"],
                        "narrative": r["output"] or None,
                    }
                    for r in all_records
                ]
                await save_to_db(db_records, db_url)

    print(f"\nDone. Generated: {total_generated} | Narrated: {total_narrated} | Errors: {total_errors}")


if __name__ == "__main__":
    asyncio.run(main())
