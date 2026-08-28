# Database Backup Strategy

Lorekeeper's production database (Postgres, `pgvector/pgvector:pg16`, running
in the `postgres` container on the OCI instance) held zero backup coverage
before this — no automated dump, no offsite copy, nothing. Given the app now
processes real Stripe payments (`STRIPE_SECRET_KEY` is a live key, not a test
one), that's the single highest-risk gap in the deployment: a bad migration,
an application bug, an accidental deletion, or an instance/disk failure could
lose every user's account, campaigns, journal entries, and subscription
history with no way back.

This is a two-tier plan. **Tier 1 is implemented and running.** Tier 2 needs
one manual setup step from whoever holds the OCI account, described below.

## Tier 1 — local nightly backups (done)

`scripts/backup-db.sh` runs `pg_dump` in custom format (`-Fc` — compressed,
selectively restorable) against the live `postgres` container, writes a
timestamped file to `~/lorekeeper/backups/`, and prunes anything older than
14 days. It's installed via cron on the instance:

```
0 3 * * * /home/ubuntu/lorekeeper/scripts/backup-db.sh >> /home/ubuntu/lorekeeper/backups/backup.log 2>&1
```

**What this protects against:** a bad migration, an application bug that
corrupts or deletes data, a user or admin action that shouldn't have
happened. Restoring rolls the whole database back to the most recent nightly
dump (`scripts/restore-db.sh <dump-file>` — destructive, stops the backend,
asks for confirmation, restores, restarts).

**What this does NOT protect against:** losing the instance itself. The
backups live on the same disk as the live database — if that disk, volume,
or instance is gone, so are the backups.

## Tier 2 — offsite copy (planned, not yet active)

Needs a copy of each nightly dump to live somewhere other than this
instance. Not implemented yet because it requires credentials only the OCI
account owner can create — nothing here should be guessing at or fabricating
those. Recommended path, in order of preference:

### Option A: OCI Object Storage (recommended — same provider, Always Free tier covers it)

1. OCI Console → Storage → Object Storage → **Create Bucket** (e.g.
   `lorekeeper-db-backups`), same region as the instance, Standard tier.
2. OCI Console → your user → **Auth Tokens** → **Generate Token**. Copy it
   immediately (shown once).
3. On the instance: `pip install --user oci-cli` (or `bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"`),
   then `oci setup config` — needs your tenancy OCID, user OCID, region, and
   an API signing key (the setup wizard generates one and prints the public
   key to add in the Console under your user → API Keys).
4. Add one line to the end of `backup-db.sh` (or a small wrapper script)
   after the existing pruning step:
   ```bash
   oci os object put --bucket-name lorekeeper-db-backups \
     --file "$OUT_FILE" --name "$(basename "$OUT_FILE")"
   ```
5. Set a lifecycle rule on the bucket (Console → bucket → Lifecycle Policy
   Rules) to auto-delete objects after e.g. 90 days, so offsite retention is
   longer than the 14-day local window without needing to manage it by hand.

### Option B: rclone to any S3-compatible provider (Backblaze B2, etc.)

Simpler credential model if you'd rather not touch OCI IAM at all —
Backblaze B2's free tier (10GB) comfortably covers years of these dumps.
1. Create a B2 bucket + application key.
2. `rclone config` on the instance (select "B2" as the provider type, paste
   the key).
3. Same idea as Option A: `rclone copy "$OUT_FILE" b2:lorekeeper-db-backups/`
   appended to the backup script.

### Whichever option: verify it actually works

An offsite copy nobody has tested restoring is not a real backup. Once
Tier 2 is wired up, periodically (monthly is reasonable) pull the latest
object back down and run `scripts/restore-db.sh` against a throwaway local
Postgres — not production — to confirm the whole chain (dump → upload →
download → restore) actually round-trips.

## Quick reference

| Task | Command |
|---|---|
| Manual backup right now | `ssh ubuntu@<instance> "cd ~/lorekeeper && ./scripts/backup-db.sh"` |
| List backups | `ssh ubuntu@<instance> "ls -lh ~/lorekeeper/backups"` |
| Restore from a backup | `ssh ubuntu@<instance> "cd ~/lorekeeper && ./scripts/restore-db.sh backups/<file>.dump"` |
| Check the cron job is installed | `ssh ubuntu@<instance> "crontab -l"` |
