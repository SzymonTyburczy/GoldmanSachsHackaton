-- ControlProof SQLite schema, version 2 (PRAGMA user_version).
-- Times are UTC ISO 8601 strings, IDs are UUID strings, amounts and counters are integers.
-- No table stores raw request bodies, prompts, documents, tokens or SDK errors.
-- human_reviews stores only masked inputs for a bounded review continuation.

-- Validated policy/feed versions. Files in config/ only seed or import these rows.
CREATE TABLE IF NOT EXISTS config_versions (
    kind TEXT NOT NULL CHECK (kind IN ('policy', 'feed')),
    version INTEGER NOT NULL CHECK (version >= 1),
    body TEXT NOT NULL,             -- canonical JSON that passed validation
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (kind, version)
);

-- Pointer to the active version; replaced atomically on activation.
CREATE TABLE IF NOT EXISTS active_config (
    kind TEXT PRIMARY KEY CHECK (kind IN ('policy', 'feed')),
    version INTEGER NOT NULL,
    activated_at TEXT NOT NULL,
    FOREIGN KEY (kind, version) REFERENCES config_versions (kind, version)
);

-- Tasks: owner and client are assigned by the server.
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_by_principal ON tasks (principal_id, created_at);

-- Idempotency and stored (already redacted) results of POST /v1/execute.
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL CHECK (length(request_sha256) = 64),
    task_id TEXT NOT NULL REFERENCES tasks (task_id),
    tool TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('IN_PROGRESS', 'COMPLETED', 'UNKNOWN')),
    policy_version INTEGER,
    feed_version INTEGER,
    response_body TEXT,             -- ExecuteResponse JSON after redaction; NULL until completed
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (principal_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS requests_by_task ON requests (task_id, created_at);

-- Budget balances per scope. Limits come from the active policy at reservation time,
-- so lowering a limit below spent + reserved blocks new reservations without a CHECK here.
CREATE TABLE IF NOT EXISTS budget_accounts (
    scope TEXT NOT NULL CHECK (scope IN ('task', 'principal', 'global')),
    scope_id TEXT NOT NULL,         -- task_id, principal_id or 'global'
    unit TEXT NOT NULL CHECK (unit IN ('nusd', 'test_credit')),
    spent INTEGER NOT NULL DEFAULT 0 CHECK (spent >= 0),
    reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, scope_id, unit)
);

CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks (task_id),
    principal_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('detector', 'summary', 'fixture')),
    unit TEXT NOT NULL CHECK (unit IN ('nusd', 'test_credit')),
    amount INTEGER NOT NULL CHECK (amount > 0),
    settled_amount INTEGER CHECK (settled_amount >= 0),
    state TEXT NOT NULL
        CHECK (state IN ('RESERVED', 'STARTED', 'SETTLED', 'RELEASED', 'UNKNOWN')),
    pricing_version TEXT,
    limit_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((purpose = 'fixture') = (unit = 'test_credit')),
    CHECK (unit <> 'nusd' OR pricing_version IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS reservations_by_state ON reservations (state);
CREATE INDEX IF NOT EXISTS reservations_by_request ON reservations (request_id);

-- Append-only audit log. event_json holds the full validated AuditEvent;
-- the other columns exist for filtering and pagination.
CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL,
    task_id TEXT,
    principal_id TEXT,
    occurred_at TEXT NOT NULL,
    control_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    stage TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    policy_version INTEGER,
    feed_version INTEGER,
    event_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_by_task ON audit_events (task_id, seq);
CREATE INDEX IF NOT EXISTS audit_by_request ON audit_events (request_id, seq);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

-- One durable review per original request. No raw prompt/document values.
CREATE TABLE IF NOT EXISTS human_reviews (
    request_id TEXT PRIMARY KEY REFERENCES requests (request_id),
    context_json TEXT NOT NULL,
    safe_request_json TEXT NOT NULL,
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    review_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN
        ('PENDING', 'RUNNING', 'APPROVED', 'BLOCKED', 'EXPIRED', 'STALE', 'UNKNOWN'))
);
CREATE INDEX IF NOT EXISTS human_reviews_by_state ON human_reviews (state);
