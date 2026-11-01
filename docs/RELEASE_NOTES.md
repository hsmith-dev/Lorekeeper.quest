# Release notes

Changes that affect campaign Owners, newest first.

## Unreleased

### Self-hosters: Redis is replaced by Valkey

**What changed.** The Compose stack now runs Valkey (`valkey/valkey:8.1.11-alpine`, BSD-3-Clause), a Redis-compatible server, instead of `redis:7-alpine`. The service is now called `valkey`, its volume `valkey_data`, and the setting `VALKEY_URL`.

**What you need to do.** Rename `REDIS_URL` to `VALKEY_URL` in your `.env` when convenient. The old name and the old `redis` hostname keep working for now, with a warning in the backend log. Nothing else: Valkey starts with an empty volume, which is fine because it only holds short-lived caches and the AI queue. Your campaigns are in Postgres and are unaffected. See "Upgrading from Redis to Valkey" in the README.

## v1.1.0 — 2026-11-01

A fixes-and-hardening release. No database migrations; your campaigns, journals and settings carry over unchanged.

### Fixes

- **The in-app model installer works again.** *Admin → System → Model Library → Download & install* failed for the fine-tuned model because Ollama refuses to pull the Hugging Face repo directly (*"Repository is not GGUF or is not compatible with llama.cpp"*). The installer now downloads the GGUF file itself, checks it against Hugging Face's published checksum, and imports it into Ollama, with a live progress bar. It checks free disk space first (~5 GB; set `LLM_DOWNLOAD_DIR` to stage elsewhere), deletes the temporary file afterwards, and skips the download if the model file is already there. The README's command-line instructions were wrong in the same way and are fixed too.
- **Read-only Share Links no longer include GM-private notes.** Journal Shorthand and NPC/quest notes were sent to anyone holding a read-only link, even though the page didn't display them. Details below.
- **lorekeeper.quest shows the landing page again.** Duplicate GitHub Pages workflows were overwriting it with a "Page not found" or the rendered README.
- **CPU-only installs no longer time out on long answers.** The production compose file capped the model server at 3 CPU cores whatever your machine had, which made CPU generation very slow and pushed longer chat answers past the 10-minute timeout. The model server now uses all cores by default (set `OLLAMA_CPUS` to cap it), and the generation timeout is 20 minutes (`KOBOLD_TIMEOUT_SECONDS=1200`).
- **Error text is readable in every theme.** Red error text had contrast as low as 1.7:1 on some themes. It now uses a dedicated danger colour (6.8:1), and status colours across the app come from the theme instead of hardcoded greens, ambers and reds.

### Improvements

- **Campaign switcher.** Pick your current campaign once from the top navigation bar. Pages with a campaign picker follow that choice, and it's remembered per device.
- **Side panels behave properly with a keyboard.** Keyboard focus stays inside an open side panel, Esc closes only the topmost layer, and focus returns to where you were. Animations respect your system's reduced-motion setting.
- **Clearer AI errors.** When the model is missing, busy or unreachable, you get a specific message instead of a generic failure, and admins get a link straight to the Model Library.
- **The model server isn't swamped.** Requests to the bundled model now queue in priority order, one at a time, so interactive requests aren't stuck behind background work and Ollama never reloads models between tasks.
- New shared UI pieces (toasts, empty states, tabs, comboboxes) make these screens consistent; more of the app moves onto them in later releases.

### Security and licensing

- **AI rate limits are per user, not per network.** A GM and their players behind one home router used to share a single AI allowance. Limits now follow the signed-in account, in both the app and nginx, with a per-IP backstop.
- **Dev compose files only listen on localhost.** `docker-compose.yml` and `docker-compose.dev.yml` used to publish Postgres, Redis, the backend and Vite on every interface, and Docker-published ports bypass host firewalls. They now bind to `127.0.0.1` unless you set `BIND_IP`. `docker-compose.prod.yml` is unaffected.
- **Smaller backend image without NVIDIA's proprietary libraries.** The backend now installs CPU-only PyTorch. GPU acceleration for the model is unaffected, because that runs in the Ollama container.
- **Licence gates in CI.** Every Python and npm dependency, base image, model and font is inventoried with its licence, and CI fails on an unlisted or incompatible one, including inside the Docker images we ship.

### Upgrading an existing install

1. `git pull` (or check out `v1.1.0`).
2. Optional: compare your `.env` with `.env.example`.
   - `KOBOLD_TIMEOUT_SECONDS` now defaults to `1200` (20 minutes). If your `.env` still sets `600`, raise it, especially on CPU. nginx's proxy timeouts are now `1260s`, just above it, so a slow answer ends with the app's own timeout message rather than a bare 504. If you raise the timeout further, raise `proxy_read_timeout` and `proxy_send_timeout` in `nginx/proxy_common.conf` to match.
   - `OLLAMA_CPUS` is new and optional. Leave it unset (or `0`) to let the model server use every core; set a number such as `6` to cap it on a shared machine. Don't leave it empty (`OLLAMA_CPUS=`): compose rejects an empty CPU limit.
3. Rebuild and restart: `docker compose -f docker-compose.prod.yml up -d --build`. There are no database migrations in this release.
4. If the fine-tuned model never installed on your earlier version, open **Admin → System → Model Library** and click **Download & install**.

If you bind nginx to a specific IP or port with a `docker-compose.override.yml`, use `ports: !override` (see the README). A plain `ports:` list is *added* to the default 80/443 bindings, not substituted for them.

### Known issues

- **CPU generation is slow.** On CPU, expect a chat answer or journal entry to take one to several minutes. An NVIDIA GPU brings that down to seconds; see the README's GPU section.
- **One AI request at a time on the bundled model.** If a second AI request arrives while a long CPU generation is running, it waits up to 60 seconds for a slot (`LLM_GATE_WAIT_S`) and then fails with a "model busy" message. Retry once the first one finishes.
- **Plan for 16 GB of RAM.** The stack uses ~9 GB steady and can briefly peak around 17 GB during generation and startup. The README previously said 8 GB.
- **App-level rate limits are per backend worker.** The app's own per-user limits are counted separately in each of the 4 backend workers, so they're looser than stated. nginx's stricter per-user limit on AI endpoints applies first, so this doesn't change what users hit in practice.

### Share Links no longer show GM-private notes

**What changed.** Read-only Share Links now show only the player-facing parts of a campaign. Anyone viewing a read-only link no longer sees:

- the **Shorthand** behind each journal entry (your raw session notes). Viewers see the written-up narrative only.
- the **notes** on NPCs (shown on the Characters tab) and quests. Viewers still see each NPC's name, role, status and description, and each quest's title, status and description.

Before this fix, both were included in what a read-only link returned, even though the shared page didn't display them.

**Collaborate links were never affected.** A collaborate link shows only the campaign's name, genre and description until someone signs in and joins. It never returned journal, NPC or quest content.

**Your existing links keep working.** You don't need to revoke or re-issue anything. Links you've already sent go to the same page and show the same journal entries, characters and quests, just without the private fields above.
