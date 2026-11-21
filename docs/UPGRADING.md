# Upgrading Lorekeeper

Notes for self-hosters on what an upgrade changes in your data. Every
upgrade runs `alembic upgrade head` when the web container starts; there is
nothing to run by hand.

## Requirement: PostgreSQL 15 or newer

PostgreSQL 15+ (16 recommended; bundled). The compose stack ships
`pgvector/pgvector:pg16`, so a standard install needs nothing. If you point
`DATABASE_URL` at your own server, it must be PostgreSQL 15 or newer with the
`vector` extension: the F3-world upgrade (revision `03c0b504f1d1`) uses a
PostgreSQL 15 feature. On an older server the upgrade stops before changing
anything, with "Lorekeeper requires PostgreSQL 15 or newer (found X)". Upgrade
the server (for example with `pg_upgrade`, or a dump and restore into a 16
server), then start Lorekeeper again.

## NPCs and Quests become Entities (F3-world, E0-WorldCore.2)

Your NPCs and Quests are now Entities. They start GM-only. Your Players, who were Members before this release, see none of them until you publish them from World.

What the upgrade does:

- Every NPC becomes a Character (kind PC, NPC or Creature, from its old
  role), and every NPC with the role Faction becomes a Faction. Statuses map
  to the new vocabulary: alive stays alive, dead becomes deceased, unknown
  stays unknown. For a Faction, alive becomes active, dead becomes
  disbanded, and unknown stays unknown.
- Every Quest becomes a Quest Entity with its status unchanged. A completed
  Quest records when it was completed (its last update).
- Names, descriptions, creation and update times carry over. Your private
  notes become the Entity's GM notes, which Players never see.
- Each Entity's history starts with one entry, "Came over from your NPC
  list" (or Quest list).
- Every existing Campaign gets the default relationship types (Ally of,
  Enemy of, Member of, Located in, Owns, Related to).

Your old NPC and Quest rows are kept as they were. The copy is safe to run
again: it never duplicates an Entity. A value it does not recognise takes
the default status (or kind NPC) and is written to the upgrade log instead
of stopping the upgrade.

## One 16 GB profile: `backend` is now `web` (E0-Platform.7)

`docker-compose.prod.yml` now gives every container a memory limit from
`.env.example`, and together they add up to 14.5 GiB (see README, "Why 16 GB").
Two things to do when you upgrade:

1. **Copy the new limits into your `.env`.** Add the "Memory budget" block from
   `.env.example` (`OLLAMA_MEM_LIMIT` through `NGINX_MEM_LIMIT`). Without it the
   compose file uses the same values as defaults, so this only matters if you
   want to change one: lower another by the same amount.
2. **Remove the old `backend` container.** The API service is renamed `web`.
   Start the upgraded stack with
   `docker compose -f docker-compose.prod.yml up -d --build --remove-orphans`;
   without `--remove-orphans` the old `backend` container (with its old 14 GB
   limit) keeps running beside `web` and writing to the same database. Your
   logs volume keeps its name, and `web` still answers to the `backend`
   hostname, so a custom nginx config or `.env` pointing at
   `http://backend:8000` keeps working. Commands change from
   `docker compose ... exec backend` to `docker compose ... exec web`.

The bundled Ollama now keeps one model loaded (`OLLAMA_MAX_LOADED_MODELS=1`,
was 2) and unloads it after 30 idle minutes (was 60), so it fits its 5.25 GiB
limit. If you installed both `lorekeeper` and `lorekeeper-base` (as
`scripts/deploy-oci.sh` does), switching between them in Settings or Model
Evaluation now reloads the model, which takes about a minute on CPU.
