-- ============================================================
--  Cloudista — subscribers schema (PostgreSQL)
-- ============================================================

CREATE TABLE IF NOT EXISTS subscribers (
    id               INTEGER         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email            VARCHAR(254)    NOT NULL UNIQUE,
    status           TEXT            NOT NULL DEFAULT 'pending'
                                     CHECK (status IN ('pending', 'confirmed', 'unsubscribed')),
    source           VARCHAR(100)    NOT NULL DEFAULT 'coming_soon',
    token            CHAR(64)        NOT NULL UNIQUE,
    token_expires_at TIMESTAMPTZ,
    ip_address       VARCHAR(45),
    user_agent       VARCHAR(500),
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT now(),
    confirmed_at     TIMESTAMPTZ,
    unsubscribed_at  TIMESTAMPTZ
);

-- UNIQUE constraint on token already creates an implicit B-tree index;
-- no separate CREATE INDEX needed for the token column.
CREATE INDEX IF NOT EXISTS idx_subscribers_status  ON subscribers (status);
CREATE INDEX IF NOT EXISTS idx_subscribers_created ON subscribers (created_at);

CREATE OR REPLACE VIEW active_subscribers AS
    SELECT id, email, source, confirmed_at, created_at
    FROM subscribers
    WHERE status = 'confirmed';

-- ============================================================
--  Production upgrade migrations (run once per schema change):
--
--  -- Add token_expires_at (from pre-expiry schema):
--  ALTER TABLE subscribers
--    ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ;
--
--  -- Drop the now-redundant manual token index if it exists:
--  DROP INDEX IF EXISTS idx_subscribers_token;
-- ============================================================
