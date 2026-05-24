-- Zak Memory Schema
-- All timestamps are ISO8601 strings in UTC.
-- episode.id and relationship dedup keys are SHA1 hashes.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ─── EPISODES ────────────────────────────────────────────────────────────────
-- Every perceivable event. Append-only — never updated after insert.
CREATE TABLE IF NOT EXISTS episodes (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    source      TEXT NOT NULL,      -- 'gmail' | 'slack' | 'telegram' | 'gcal' | 'system' | 'alfred_import'
    source_id   TEXT,               -- original message-id / event-id from the source
    kind        TEXT NOT NULL,      -- 'email' | 'slack_msg' | 'user_msg' | 'zak_msg' | 'calendar' | 'reflection' | 'note'
    signal      TEXT NOT NULL DEFAULT 'MEDIUM',  -- 'HIGH' | 'MEDIUM' | 'LOW'
    actor_id    TEXT,               -- FK → entities.id (who sent/caused this)
    subject     TEXT,               -- email subject, event title, or short summary
    body        TEXT,               -- full content
    summary     TEXT,               -- LLM-generated one-liner (populated lazily by agent loop)
    meta        TEXT,               -- JSON blob for source-specific fields
    processed   INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=done
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_episodes_ts        ON episodes(ts DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_source    ON episodes(source);
CREATE INDEX IF NOT EXISTS idx_episodes_actor     ON episodes(actor_id);
CREATE INDEX IF NOT EXISTS idx_episodes_processed ON episodes(processed);
CREATE INDEX IF NOT EXISTS idx_episodes_signal    ON episodes(signal);
CREATE INDEX IF NOT EXISTS idx_episodes_kind      ON episodes(kind);

-- ─── ENTITIES ─────────────────────────────────────────────────────────────────
-- People, projects, companies, departments. Upserted in place.
CREATE TABLE IF NOT EXISTS entities (
    id            TEXT PRIMARY KEY,  -- slug: 'person_ahmed_ali', 'project_atlas'
    kind          TEXT NOT NULL,     -- 'person' | 'project' | 'company' | 'department'
    name          TEXT NOT NULL,
    aliases       TEXT,              -- JSON array of alternative names/emails/handles
    attributes    TEXT,              -- JSON blob: role, email, slack_handle, investor_status, etc.
    notes         TEXT,              -- Zak's evolving notes about this entity
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    episode_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- Full-text search over entities
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    id UNINDEXED,
    name,
    aliases,
    notes,
    content='entities',
    content_rowid='rowid'
);

-- ─── RELATIONSHIPS ────────────────────────────────────────────────────────────
-- Directed edges in the entity graph.
CREATE TABLE IF NOT EXISTS relationships (
    id          TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL REFERENCES entities(id),
    predicate   TEXT NOT NULL,   -- 'leads_project' | 'executes_project' | 'owns_action'
                                 -- 'member_of' | 'reports_to' | 'blocks' | 'knows'
    object_id   TEXT NOT NULL REFERENCES entities(id),
    strength    REAL NOT NULL DEFAULT 1.0,  -- 0.0–1.0; decays if not reinforced
    evidence    TEXT,            -- JSON array of episode_ids supporting this edge
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(subject_id, predicate, object_id)
);

CREATE INDEX IF NOT EXISTS idx_rel_subject   ON relationships(subject_id);
CREATE INDEX IF NOT EXISTS idx_rel_object    ON relationships(object_id);
CREATE INDEX IF NOT EXISTS idx_rel_predicate ON relationships(predicate);

-- ─── REFLECTIONS ──────────────────────────────────────────────────────────────
-- Zak's own observations from the reflection loop. Append-only.
-- observation text becomes verbatim context in future LLM calls.
CREATE TABLE IF NOT EXISTS reflections (
    id           TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    kind         TEXT NOT NULL,  -- 'pattern' | 'stale_thread' | 'blocked_project'
                                 -- 'relationship_drift' | 'proactive_nudge' | 'question'
    subject_ids  TEXT,           -- JSON array of entity ids involved
    episode_ids  TEXT,           -- JSON array of supporting episode ids
    observation  TEXT NOT NULL,
    action_taken TEXT,
    resolved     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_reflections_ts       ON reflections(ts DESC);
CREATE INDEX IF NOT EXISTS idx_reflections_kind     ON reflections(kind);
CREATE INDEX IF NOT EXISTS idx_reflections_resolved ON reflections(resolved);

-- ─── TODOS ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS todos (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    notes             TEXT,
    owner_id          TEXT REFERENCES entities(id),
    project_id        TEXT REFERENCES entities(id),
    status            TEXT NOT NULL DEFAULT 'open',    -- 'open' | 'in_progress' | 'done' | 'cancelled'
    priority          TEXT NOT NULL DEFAULT 'medium',  -- 'high' | 'medium' | 'low'
    due_date          TEXT,
    source_episode_id TEXT REFERENCES episodes(id),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_todos_status   ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_owner    ON todos(owner_id);
CREATE INDEX IF NOT EXISTS idx_todos_due_date ON todos(due_date);
CREATE INDEX IF NOT EXISTS idx_todos_priority ON todos(priority);

-- ─── ZAK_STATE ────────────────────────────────────────────────────────────────
-- Key-value store for agent state: last sync times, onboarding flags, preferences.
CREATE TABLE IF NOT EXISTS zak_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
