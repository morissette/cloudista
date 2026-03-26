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
    unsubscribed_at  TIMESTAMPTZ,
    frequency        VARCHAR(20)     NOT NULL DEFAULT 'weekly',
    last_digest_at   TIMESTAMPTZ,
    prefs_token          CHAR(64)        UNIQUE,
    prefs_token_expires_at TIMESTAMPTZ
);

-- UNIQUE constraint on token already creates an implicit B-tree index;
-- no separate CREATE INDEX needed for the token column.
CREATE INDEX IF NOT EXISTS idx_subscribers_status  ON subscribers (status);
CREATE INDEX IF NOT EXISTS idx_subscribers_created ON subscribers (created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscribers_prefs_token ON subscribers (prefs_token) WHERE prefs_token IS NOT NULL;

CREATE OR REPLACE VIEW active_subscribers AS
    SELECT id, email, source, confirmed_at, created_at
    FROM subscribers
    WHERE status = 'confirmed';

-- ============================================================
--  Post view counts (daily time-series)
-- ============================================================

CREATE TABLE IF NOT EXISTS post_views (
    post_id    INTEGER       NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    viewed_on  DATE          NOT NULL DEFAULT CURRENT_DATE,
    country    CHAR(2)       NOT NULL DEFAULT 'XX',  -- ISO 3166-1 alpha-2; XX = unknown/Tor
    is_bot     BOOLEAN       NOT NULL DEFAULT false,
    referrer   VARCHAR(100)  NOT NULL DEFAULT '',    -- domain only, e.g. google.com; '' = direct
    view_count INTEGER       NOT NULL DEFAULT 1,
    PRIMARY KEY (post_id, viewed_on, country, is_bot, referrer)
);

CREATE INDEX IF NOT EXISTS idx_post_views_date     ON post_views (viewed_on);
CREATE INDEX IF NOT EXISTS idx_post_views_post_id  ON post_views (post_id);
CREATE INDEX IF NOT EXISTS idx_post_views_country  ON post_views (country);
CREATE INDEX IF NOT EXISTS idx_post_views_referrer ON post_views (referrer) WHERE referrer != '';
-- Partial index for human-only queries (most common analytics path)
CREATE INDEX IF NOT EXISTS idx_post_views_humans
    ON post_views (post_id, viewed_on) WHERE is_bot = false;

-- ============================================================
--  Post revisions
-- ============================================================

CREATE TABLE IF NOT EXISTS post_revisions (
    id           INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    post_id      INTEGER      NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    title        TEXT         NOT NULL,
    content_md   TEXT         NOT NULL,
    content_html TEXT         NOT NULL,
    excerpt      TEXT,
    revised_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_post_revisions_post_id
    ON post_revisions (post_id, revised_at DESC);

-- ============================================================
--  Production upgrade migrations (run once per schema change):
--
--  -- Add token_expires_at (from pre-expiry schema):
--  ALTER TABLE subscribers
--    ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ;
--
--  -- Drop the now-redundant manual token index if it exists:
--  DROP INDEX IF EXISTS idx_subscribers_token;
--
--  -- Post revisions table:
--  CREATE TABLE IF NOT EXISTS post_revisions ( ... );
--  CREATE INDEX IF NOT EXISTS idx_post_revisions_post_id ...;
-- ============================================================

-- ============================================================
--  Post view metrics (run once on production):
--
--  CREATE TABLE IF NOT EXISTS post_views (
--      post_id    INTEGER  NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
--      viewed_on  DATE     NOT NULL DEFAULT CURRENT_DATE,
--      country    CHAR(2)  NOT NULL DEFAULT 'XX',
--      is_bot     BOOLEAN  NOT NULL DEFAULT false,
--      view_count INTEGER  NOT NULL DEFAULT 1,
--      PRIMARY KEY (post_id, viewed_on, country, is_bot)
--  );
--  CREATE INDEX IF NOT EXISTS idx_post_views_date    ON post_views (viewed_on);
--  CREATE INDEX IF NOT EXISTS idx_post_views_post_id ON post_views (post_id);
--  CREATE INDEX IF NOT EXISTS idx_post_views_country ON post_views (country);
--  CREATE INDEX IF NOT EXISTS idx_post_views_humans
--      ON post_views (post_id, viewed_on) WHERE is_bot = false;
--
-- ============================================================
--  Subscriber notification preferences + post notifications
--  (run once on production):
--
--  ALTER TABLE subscribers
--    ADD COLUMN IF NOT EXISTS frequency             VARCHAR(20) NOT NULL DEFAULT 'weekly',
--    ADD COLUMN IF NOT EXISTS last_digest_at        TIMESTAMPTZ,
--    ADD COLUMN IF NOT EXISTS prefs_token           CHAR(64) UNIQUE,
--    ADD COLUMN IF NOT EXISTS prefs_token_expires_at TIMESTAMPTZ;
--
--  ALTER TABLE posts
--    ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
--
--  CREATE INDEX IF NOT EXISTS idx_posts_unnotified
--    ON posts (published_at DESC) WHERE status = 'published' AND notified_at IS NULL;
-- ============================================================
