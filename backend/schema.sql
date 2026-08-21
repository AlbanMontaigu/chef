-- A slot is one service the chef is willing to cook: a date + midi/soir.
-- The chef opens them from the back-office; the public site only ever sees
-- the ones still available.
CREATE TABLE IF NOT EXISTS slots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,              -- YYYY-MM-DD, Europe/Paris
    service     TEXT NOT NULL,              -- 'midi' | 'soir'
    note        TEXT NOT NULL DEFAULT '',   -- optional, shown to visitors
    created_at  TEXT NOT NULL,
    UNIQUE (date, service)
);

CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ref           TEXT NOT NULL UNIQUE,     -- human-readable, given to the client
    slot_id       INTEGER NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    phone         TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    guests        INTEGER NOT NULL,
    formula       TEXT NOT NULL DEFAULT '',
    message       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'confirmed',   -- 'confirmed' | 'cancelled'
    created_at    TEXT NOT NULL,
    cancelled_at  TEXT,
    -- Mail outcome, per recipient. 'pending' until the send is attempted,
    -- then 'sent' | 'failed' | 'disabled'. Never silently dropped.
    mail_client   TEXT NOT NULL DEFAULT 'pending',
    mail_chef     TEXT NOT NULL DEFAULT 'pending',
    mail_error    TEXT NOT NULL DEFAULT ''
);

-- Double-booking protection at the storage layer, not in application logic:
-- a slot can carry at most one live booking, whatever races upstream.
CREATE UNIQUE INDEX IF NOT EXISTS bookings_one_live_per_slot
    ON bookings (slot_id) WHERE status = 'confirmed';

CREATE INDEX IF NOT EXISTS bookings_by_created ON bookings (created_at DESC);
CREATE INDEX IF NOT EXISTS slots_by_date ON slots (date);
