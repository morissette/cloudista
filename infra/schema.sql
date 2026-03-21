-- ============================================================
--  Cloudista — Notify Me subscriber schema
--  Target: MariaDB 5.5.68
--
--  Notes for 5.5 compatibility:
--    • Only one TIMESTAMP column per table may carry
--      DEFAULT CURRENT_TIMESTAMP / ON UPDATE CURRENT_TIMESTAMP
--      (restriction lifted in MariaDB 10.0).
--      secondary date columns use DATETIME instead.
--    • JSON type not available; use VARCHAR/TEXT.
--    • utf8mb4 requires InnoDB (MyISAM row-length limit too small).
-- ============================================================

CREATE DATABASE IF NOT EXISTS cloudista
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE cloudista;

-- ------------------------------------------------------------
--  subscribers
--    Stores email capture submissions from the coming-soon page.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscribers (

  id            INT UNSIGNED    NOT NULL AUTO_INCREMENT,

  -- Contact
  -- VARCHAR(191): utf8mb4 uses 4 bytes/char; InnoDB 5.5 index limit is
  -- 767 bytes → max indexable length = floor(767/4) = 191 chars.
  -- 191 chars covers all real-world email addresses (RFC 5321 max is 254).
  email         VARCHAR(191)    NOT NULL,

  -- Lifecycle state
  --   pending      → submitted, awaiting confirmation e-mail click
  --   confirmed    → double opt-in verified
  --   unsubscribed → user opted out
  status        ENUM(
                  'pending',
                  'confirmed',
                  'unsubscribed'
                )               NOT NULL DEFAULT 'pending',

  -- Where on the site the form was submitted from.
  -- Useful if you add additional capture forms later.
  source        VARCHAR(100)    NOT NULL DEFAULT 'coming_soon',

  -- Opaque token used in confirm / unsubscribe links.
  -- Generate with: SHA2(CONCAT(email, UUID(), RAND()), 256)
  token         CHAR(64)        NOT NULL,

  -- Optional metadata
  ip_address    VARCHAR(45)     DEFAULT NULL,  -- IPv4 or IPv6
  user_agent    VARCHAR(500)    DEFAULT NULL,

  -- Timestamps
  -- created_at uses TIMESTAMP so it gets DEFAULT CURRENT_TIMESTAMP.
  -- confirmed_at / unsubscribed_at use DATETIME (5.5 limitation).
  created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  confirmed_at    DATETIME      DEFAULT NULL,
  unsubscribed_at DATETIME      DEFAULT NULL,

  -- Keys
  PRIMARY KEY         (id),
  UNIQUE  KEY uq_email (email),
  UNIQUE  KEY uq_token (token),
  KEY     idx_status   (status),
  KEY     idx_created  (created_at)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
--  Helper: view active (confirmed) subscribers only
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW active_subscribers AS
  SELECT
    id,
    email,
    source,
    confirmed_at,
    created_at
  FROM subscribers
  WHERE status = 'confirmed';


-- ============================================================
--  Sample application queries
-- ============================================================

-- INSERT a new submission (generate token in app layer):
-- INSERT INTO subscribers (email, source, token, ip_address, user_agent)
-- VALUES ('user@example.com', 'coming_soon', ?, ?, ?);

-- CONFIRM via token click:
-- UPDATE subscribers
--    SET status = 'confirmed', confirmed_at = NOW()
--  WHERE token = ?
--    AND status = 'pending';

-- UNSUBSCRIBE via token:
-- UPDATE subscribers
--    SET status = 'unsubscribed', unsubscribed_at = NOW()
--  WHERE token = ?;

-- FETCH all confirmed emails (e.g. for a launch blast):
-- SELECT email FROM active_subscribers ORDER BY confirmed_at;

-- CHECK if email already exists before inserting:
-- SELECT id, status FROM subscribers WHERE email = ? LIMIT 1;
