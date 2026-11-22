# Upgrading Lorekeeper

Notes for self-hosters on what an upgrade changes in your data. Every
upgrade runs `alembic upgrade head` when the web container starts; there is
nothing to run by hand.

## A backup before every migration (E0-Platform.9)

The web container now starts with `scripts/boot_migrate.py` before gunicorn.
When the database holds data and this release has a migration it doesn't,
the web container first writes `pg_dump -Fc` to the new `backups` volume as
`pre-upgrade_<UTC stamp>_<old revision>.dump`, then upgrades. If the dump
can't be written (no space, an unwritable volume), the container stops with
`boot-migrate: pre-upgrade backup failed (...); not migrating` and your
database stays at its old revision. Free the space and start it again. A
Postgres advisory lock makes a second web replica wait; it then finds the
schema at head and skips both steps. The newest `PRE_UPGRADE_BACKUPS_KEEP`
(default 5) dumps are kept. If you upgrade by hand rather than with
`scripts/deploy-oci.sh`, stop the worker first
(`docker compose -f docker-compose.prod.yml stop worker`): compose replaces
it only after the new web is healthy, and anything it writes in between is
not in the dump.

To undo an upgrade, restore that dump with
`scripts/restore-db.sh --no-restart <dump>` and run the previous release
(docs/OCI_DEPLOYMENT.md, "Rolling back"). Starting an older image against a
database a newer one has upgraded stops with a `boot-migrate:` line naming
the revision it doesn't know, instead of running on a schema it wasn't built
for.

The images are also tagged now: `lorekeeper-web` (web and worker),
`lorekeeper-ml`, `lorekeeper-stt` and `lorekeeper-nginx`, all at
`${LOREKEEPER_TAG:-latest}`. `scripts/deploy-oci.sh` builds them from source
with `docker buildx bake -f docker-bake.hcl`; Lorekeeper publishes no images.
The web image now includes the PostgreSQL 17 client (`pg_dump`,
`pg_restore`, `psql`), which reads the bundled PostgreSQL 16 server.

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
