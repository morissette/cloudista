-- Cloudista Blog Schema
-- PostgreSQL 15+

-- Authors
CREATE TABLE authors (
    id          SERIAL PRIMARY KEY,
    uuid        UUID NOT NULL DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(255) UNIQUE NOT NULL,
    bio         TEXT,
    avatar_url  VARCHAR(500),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Posts
CREATE TABLE posts (
    id              SERIAL PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid(),
    title           VARCHAR(500) NOT NULL,
    slug            VARCHAR(500) NOT NULL UNIQUE,
    content         TEXT NOT NULL DEFAULT '',
    excerpt         TEXT,
    author_id       INT NOT NULL REFERENCES authors(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'published', 'archived')),
    original_url    VARCHAR(500),    -- for migrated posts
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ
);

-- Tags
CREATE TABLE tags (
    id          SERIAL PRIMARY KEY,
    uuid        UUID NOT NULL DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    slug        VARCHAR(100) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Categories
CREATE TABLE categories (
    id          SERIAL PRIMARY KEY,
    uuid        UUID NOT NULL DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    slug        VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    parent_id   INT REFERENCES categories(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Post <-> Tag
CREATE TABLE post_tags (
    post_id     INT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tag_id      INT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, tag_id)
);

-- Post <-> Category
CREATE TABLE post_categories (
    post_id     INT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    category_id INT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, category_id)
);

-- Media attachments
CREATE TABLE media (
    id          SERIAL PRIMARY KEY,
    uuid        UUID NOT NULL DEFAULT gen_random_uuid(),
    filename    VARCHAR(500) NOT NULL,
    url         VARCHAR(1000) NOT NULL,
    mime_type   VARCHAR(100),
    size_bytes  BIGINT,
    post_id     INT REFERENCES posts(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_posts_slug ON posts(slug);
CREATE INDEX idx_posts_status ON posts(status);
CREATE INDEX idx_posts_published_at ON posts(published_at DESC)
    WHERE status = 'published';
CREATE INDEX idx_posts_author_id ON posts(author_id);
CREATE INDEX idx_tags_slug ON tags(slug);
CREATE INDEX idx_categories_slug ON categories(slug);
CREATE INDEX idx_categories_parent_id ON categories(parent_id);

-- Seed author
INSERT INTO authors (name, email, bio)
VALUES ('Marie H.', 'marie@cloudista.org', 'DevOps and cloud infrastructure engineer.');
