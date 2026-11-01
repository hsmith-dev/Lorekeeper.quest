# Release notes

Changes that affect campaign Owners, newest first.

## Unreleased

### Self-hosters: Redis is replaced by Valkey

**What changed.** The Compose stack now runs Valkey (`valkey/valkey:8.1.11-alpine`, BSD-3-Clause), a Redis-compatible server, instead of `redis:7-alpine`. The service is now called `valkey`, its volume `valkey_data`, and the setting `VALKEY_URL`.

**What you need to do.** Rename `REDIS_URL` to `VALKEY_URL` in your `.env` when convenient. The old name and the old `redis` hostname keep working for now, with a warning in the backend log. Nothing else: Valkey starts with an empty volume, which is fine because it only holds short-lived caches and the AI queue. Your campaigns are in Postgres and are unaffected. See "Upgrading from Redis to Valkey" in the README.

### Share Links no longer show GM-private notes

**What changed.** Read-only Share Links now show only the player-facing parts of a campaign. Anyone viewing a read-only link no longer sees:

- the **Shorthand** behind each journal entry (your raw session notes). Viewers see the written-up narrative only.
- the **notes** on NPCs (shown on the Characters tab) and quests. Viewers still see each NPC's name, role, status and description, and each quest's title, status and description.

Before this fix, both were included in what a read-only link returned, even though the shared page didn't display them.

**Collaborate links were never affected.** A collaborate link shows only the campaign's name, genre and description until someone signs in and joins. It never returned journal, NPC or quest content.

**Your existing links keep working.** You don't need to revoke or re-issue anything. Links you've already sent go to the same page and show the same journal entries, characters and quests, just without the private fields above.
