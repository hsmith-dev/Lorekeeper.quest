# Database Schema — Lorekeeper

PostgreSQL database (`lorekeeper`). All primary keys are UUIDs. All tables with `TimestampMixin` include `created_at` and `updated_at` (timestamp with time zone, default `now()`).

---

## Tables

### `users`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `email` | varchar(255) | NO | unique, indexed |
| `hashed_password` | varchar(255) | NO | |
| `display_name` | varchar(100) | NO | |
| `avatar_data` | text | YES | base64 or URL |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

**Relations:** has many `campaigns`, `journal_entries`, `chat_sessions`, one `user_settings`.

---

### `campaigns`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | uuid | NO | FK → users (CASCADE DELETE) |
| `name` | varchar(200) | NO | |
| `genre` | enum | NO | `fantasy` `scifi` `horror` `videogame` `other` |
| `description` | text | YES | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

**Relations:** belongs to `users`; has many `journal_entries`, `npcs`, `quests`, `chat_sessions`.

---

### `journal_entries`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | uuid | NO | FK → users (CASCADE DELETE) |
| `campaign_id` | uuid | NO | FK → campaigns (CASCADE DELETE) |
| `shorthand` | text | NO | raw bullet-point input from user |
| `narrative` | text | NO | AI-expanded prose output |
| `narrative_tsv` | tsvector | YES | full-text search vector (GIN index) |
| `entry_hash` | varchar(64) | NO | unique SHA fingerprint for dedup |
| `session_date` | date | YES | |
| `embedding` | vector(384) | YES | pgvector semantic search embedding |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

**Indexes:** `ix_journal_narrative_fts` (GIN on `narrative_tsv`) for full-text search.

**Relations:** belongs to `users` and `campaigns`; many-to-many with `tags` via `journal_tags`.

---

### `tags`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `name` | varchar(200) | NO | indexed |
| `tag_type` | enum | NO | `character` `location` `item` `quest` `faction` |

**Constraints:** unique on (`name`, `tag_type`).

**Relations:** many-to-many with `journal_entries` via `journal_tags`.

---

### `journal_tags` *(junction table)*

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `journal_id` | uuid | NO | PK, FK → journal_entries (CASCADE DELETE) |
| `tag_id` | uuid | NO | PK, FK → tags (CASCADE DELETE) |

---

### `npcs`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | uuid | NO | FK → users (CASCADE DELETE) |
| `campaign_id` | uuid | NO | FK → campaigns (CASCADE DELETE) |
| `name` | varchar(200) | NO | |
| `role` | enum | NO | `npc` `pc` `monster` `faction` |
| `status` | enum | NO | `alive` `dead` `unknown` |
| `description` | text | YES | |
| `notes` | text | YES | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

---

### `quests`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | uuid | NO | FK → users (CASCADE DELETE) |
| `campaign_id` | uuid | NO | FK → campaigns (CASCADE DELETE) |
| `title` | varchar(300) | NO | |
| `description` | text | YES | |
| `status` | enum | NO | `active` `completed` `failed` `abandoned` |
| `notes` | text | YES | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

---

### `chat_sessions`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | uuid | NO | FK → users (CASCADE DELETE) |
| `campaign_id` | uuid | YES | FK → campaigns (SET NULL on delete) |
| `title` | varchar(120) | NO | default `"New conversation"` |
| `messages` | jsonb | NO | full message history array |
| `message_count` | integer | NO | default `0` |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

---

### `user_settings`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | uuid | NO | FK → users (CASCADE DELETE), unique |
| `llm_provider` | varchar(50) | NO | default `"kobold"` — `kobold` `openai` `anthropic` `gemini` `custom` |
| `llm_api_url` | varchar(500) | YES | |
| `llm_api_key` | varchar(500) | YES | |
| `llm_model` | varchar(200) | YES | |
| `llm_temperature` | float | NO | default `0.72` |
| `llm_max_tokens` | integer | NO | default `800` |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

**Constraints:** unique on `user_id` (enforces 1-to-1 with users).

---

## Relationship Map

```
users
 ├── campaigns (1:many, cascade delete)
 │    ├── journal_entries (1:many, cascade delete)
 │    │    └── journal_tags ──→ tags (many:many)
 │    ├── npcs (1:many, cascade delete)
 │    ├── quests (1:many, cascade delete)
 │    └── chat_sessions (1:many, SET NULL on campaign delete)
 ├── journal_entries (also direct FK for ownership)
 ├── chat_sessions (1:many, cascade delete)
 └── user_settings (1:1, cascade delete)
```

---

## Notable Design Decisions

- **Dual search on `journal_entries`:** `narrative_tsv` (tsvector + GIN index) for keyword full-text search; `embedding` (pgvector vector(384)) for semantic similarity search.
- **`chat_sessions.messages` is JSONB:** the full conversation history is stored as a single array column rather than a normalized messages table.
- **`campaign_id` is nullable on `chat_sessions`:** allows global (non-campaign-scoped) chat sessions; the FK is SET NULL rather than CASCADE so deleting a campaign doesn't destroy chat history.
- **`entry_hash` deduplication:** SHA-64 fingerprint on journal entries prevents duplicate ingestion from the same raw input.
- **All content scoped to `(user_id, campaign_id)`:** clean multi-user, multi-campaign isolation throughout.
