#!/usr/bin/env python3
"""
One-time migration: MySQL/MariaDB subscribers → PostgreSQL.

Run once on the server while both databases are accessible:

    MYSQL_HOST=127.0.0.1 MYSQL_USER=cloudista_api MYSQL_PASSWORD=... \\
    BLOG_DB_HOST=localhost BLOG_DB_PORT=5433 BLOG_DB_PASSWORD=... \\
    python3 scripts/migrate_subscribers_to_pg.py

Safe to re-run — uses ON CONFLICT DO NOTHING.
"""
import os

import psycopg2
import psycopg2.extras
import pymysql
import pymysql.cursors


def main() -> None:
    mysql_conn = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ.get("MYSQL_DB", "cloudista"),
        cursorclass=pymysql.cursors.DictCursor,
    )
    pg_conn = psycopg2.connect(
        host=os.environ.get("BLOG_DB_HOST", "localhost"),
        port=int(os.environ.get("BLOG_DB_PORT", 5433)),
        user=os.environ.get("BLOG_DB_USER", "cloudista"),
        password=os.environ["BLOG_DB_PASSWORD"],
        dbname=os.environ.get("BLOG_DB_NAME", "cloudista"),
    )

    with mysql_conn.cursor() as src:
        src.execute("SELECT * FROM subscribers ORDER BY id")
        rows = src.fetchall()

    print(f"Found {len(rows)} subscribers in MySQL.")

    if not rows:
        print("Nothing to migrate.")
        mysql_conn.close()
        pg_conn.close()
        return

    with pg_conn.cursor() as dst:
        psycopg2.extras.execute_batch(
            dst,
            """
            INSERT INTO subscribers
                (email, status, source, token, ip_address, user_agent,
                 created_at, confirmed_at, unsubscribed_at)
            VALUES
                (%(email)s, %(status)s, %(source)s, %(token)s, %(ip_address)s,
                 %(user_agent)s, %(created_at)s, %(confirmed_at)s, %(unsubscribed_at)s)
            ON CONFLICT (email) DO NOTHING
            """,
            rows,
        )
    pg_conn.commit()

    print(f"Migration complete — {len(rows)} rows inserted (duplicates skipped).")
    mysql_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
