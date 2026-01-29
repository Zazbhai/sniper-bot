"""
Utility script to add or update an admin/user record in PostgreSQL (Neon).

Usage examples:
    python add_admin.py --username admin --password secret --expiry 2026-12-31
    python add_admin.py --username admin --password secret --role admin --expiry 2099-12-31

Notes:
- Password is stored as plain text because the app currently expects plain storage.
- Expiry is stored as an ISO date string (YYYY-MM-DD). You can also pass "never" to set a far‑future date.
"""

import argparse
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor

POSTGRES_URI_DEFAULT = "postgresql://neondb_owner:npg_UcP04dlFbDqL@ep-summer-feather-a17shjad-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"


def parse_args():
    parser = argparse.ArgumentParser(description="Add/update admin/user in PostgreSQL")
    parser.add_argument("--username", required=True, help="Username to add/update")
    parser.add_argument("--password", required=True, help="Password (stored as plain text)")
    parser.add_argument(
        "--expiry",
        default="2099-12-31",
        help="Expiry date YYYY-MM-DD (use 'never' for far future)",
    )
    parser.add_argument(
        "--role",
        default="admin",
        choices=["admin", "user"],
        help="Role label (admin or user)",
    )
    parser.add_argument(
        "--postgres-uri",
        default=os.environ.get("POSTGRES_URI", POSTGRES_URI_DEFAULT),
        help="PostgreSQL URI (defaults to env POSTGRES_URI or bundled URI)",
    )
    return parser.parse_args()


def normalize_expiry(expiry_str: str) -> str:
    if expiry_str.lower() == "never":
        return "2099-12-31"
    try:
        dt = datetime.strptime(expiry_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        raise SystemExit("Expiry must be YYYY-MM-DD or 'never'")


def init_db(conn):
    """Initialize database tables if they don't exist"""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username VARCHAR(255) PRIMARY KEY,
                password VARCHAR(255) NOT NULL,
                expiry VARCHAR(50),
                expired BOOLEAN DEFAULT FALSE,
                shortener_enabled BOOLEAN DEFAULT TRUE,
                role VARCHAR(50) DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"⚠️ Error initializing database: {e}")
        conn.rollback()
        return False

def main():
    args = parse_args()
    expiry_val = normalize_expiry(args.expiry)

    try:
        conn = psycopg2.connect(args.postgres_uri)
        # Initialize tables if needed
        init_db(conn)
    except Exception as e:
        raise SystemExit(f"Failed to connect to PostgreSQL: {e}")

    username = args.username.strip()
    password = args.password
    role = args.role
    created_at = datetime.utcnow()

    try:
        cur = conn.cursor()
        
        # Check if user exists
        cur.execute("SELECT username FROM users WHERE username = %s", (username,))
        user_exists = cur.fetchone() is not None
        
        if user_exists:
            # Update existing user
            cur.execute("""
                UPDATE users 
                SET password = %s, expiry = %s, expired = %s, 
                    shortener_enabled = %s, role = %s
                WHERE username = %s
            """, (password, expiry_val, False, True, role, username))
            conn.commit()
            print(f"✅ Updated existing user '{username}' with new values.")
        else:
            # Insert new user
            cur.execute("""
                INSERT INTO users (username, password, expiry, expired, shortener_enabled, role, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (username, password, expiry_val, False, True, role, created_at))
            conn.commit()
            print(f"✅ Inserted new user '{username}'.")
        
        cur.close()
        print(f"Role: {role}")
        print(f"Expiry: {expiry_val}")
        
    except Exception as e:
        conn.rollback()
        raise SystemExit(f"Error saving user: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

