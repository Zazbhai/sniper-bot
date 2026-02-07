"""
FlipkartSniper 2.0 with PostgreSQL Authentication + Admin Panel

Installation:
pip install flask psycopg2-binary

Usage:
1. Run: python app.py
2. Visit http://localhost:5000/admin to add users
3. Login with added credentials
"""


# ==================== ADMIN PANEL ====================
from flask import Flask, request, jsonify, render_template_string, redirect, make_response, send_file, send_from_directory
from functools import wraps
import time
import os
import logging
import logging
from datetime import datetime
import threading

# Load Environment Variables from .env file (Custom implementation to avoid dependency)
def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    # Only set if not already set (don't override system envs)
                    if key.strip() not in os.environ:
                        os.environ[key.strip()] = val.strip()

load_env_file()
import socket
import time
import sys
import io
import threading
import requests
import json
import csv
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool





# ============================================================
# TRY IMPORTING CONNECT RUNNER (FALLBACK TO MOCK)
# ============================================================
try:
    from connect import ConnectRunner
except ImportError:
    print("WARNING: connect.py missing — using MockRunner")

    log_func = None

    class ConnectRunner:
        def __init__(self, **kwargs):
            self.config = kwargs
            self._log("MockRunner loaded.")
            self._log(f"Products: {self.config.get('products_dict')}")
            self._log(f"Count limit: {self.config.get('count_limit')}")

        def _log(self, msg):
            if log_func:
                log_func(msg)
            else:
                print(msg)

        def run_all(self):
            self._log("🚀 Mock runner started...")
            limit = self.config.get("count_limit", 3)
            for i in range(1, limit + 1):
                self._log(f"Processing order {i}...")
                time.sleep(1)
            self._log("✔ Mock runner finished.")


# ============================================================
# FLASK INITIALIZATION
# ============================================================
app = Flask(__name__)
app.secret_key = "flipkart_sniper_secret_key"

# Hide werkzeug request logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)


# ============================================================
# POSTGRESQL CONFIG / HELPERS (Neon)
# ============================================================
import time
from datetime import datetime, timedelta
from flask import make_response, redirect, request, jsonify
from functools import wraps
import threading

POSTGRES_URI = "postgresql://neondb_owner:npg_UcP04dlFbDqL@ep-summer-feather-a17shjad-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
SHORTENER_SETTING_ID = "shortener"
SHORTENER_ENABLED_DEFAULT = True

db_pool = None
db_conn = None

def get_db_connection():
    """Get a database connection - create new one each time"""
    try:
        conn = psycopg2.connect(POSTGRES_URI)
        return conn
    except Exception as e:
        print(f"⚠️ Database connection error: {e}")
        return None

def return_db_connection(conn):
    """Close database connection"""
    if conn:
        try:
            conn.close()
        except:
            pass

def init_db(conn):
    """Initialize database tables"""
    if not conn:
        return False
    try:
        cur = conn.cursor()
        # Create users table
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
        # Create settings table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                setting_id VARCHAR(255) PRIMARY KEY,
                enabled BOOLEAN DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.close()
        print(f"✅ Database tables created successfully")
        return True
    except Exception as e:
        print(f"⚠️ Database initialization error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False

# Initialize database tables
try:
    test_conn = get_db_connection()
    if test_conn:
        if init_db(test_conn):
            print(f"✅ Connected to PostgreSQL (Neon) - Tables ready")
            db_conn = test_conn  # Keep connection for ready check
        else:
            print(f"⚠️ Database connection established but initialization failed")
            return_db_connection(test_conn)
            db_conn = None
    else:
        db_conn = None
except Exception as e:
    print(f"⚠️ PostgreSQL connection failed: {e}")
    import traceback
    traceback.print_exc()
    db_conn = None

def mongo_ready() -> bool:
    """Check if database is ready (kept name for compatibility)"""
    global db_conn
    if db_conn:
        try:
            # Quick test query
            cur = db_conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return True
        except:
            # Connection might be stale, try to reconnect
            try:
                db_conn = get_db_connection()
                return db_conn is not None
            except:
                return False
    return False


def get_user_doc(username: str):
    if not mongo_ready():
        return None
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        cur.close()
        if row:
            return dict(row)
        return None
    except Exception as e:
        print(f"⚠️ Error getting user: {e}")
        return None
    finally:
        return_db_connection(conn)


def parse_expiry(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except Exception:
            return None
    if isinstance(value, str) and value:
        try:
            # Allow ISO strings with or without Z
            return datetime.fromisoformat(value.replace("Z", ""))
        except Exception:
            return None
    return None


def get_expiry_dt(username: str) -> datetime:
    """
    Compute expiry datetime from stored expiry field.
    """
    user = get_user_doc(username)
    expiry = parse_expiry(user.get("expiry")) if user else None
    return expiry or datetime.utcnow()


def is_user_expired_doc(user_doc) -> bool:
    """
    True if the user's subscription has expired or marked expired.
    """
    if not user_doc:
        return True
    if user_doc.get("expired") is True:
        return True
    expiry_dt = parse_expiry(user_doc.get("expiry"))
    if expiry_dt and datetime.utcnow() > expiry_dt:
        return True
    return False


def get_shortener_enabled() -> bool:
    if not mongo_ready():
        return SHORTENER_ENABLED_DEFAULT
    conn = get_db_connection()
    if not conn:
        return SHORTENER_ENABLED_DEFAULT
    try:
        cur = conn.cursor()
        cur.execute("SELECT enabled FROM settings WHERE setting_id = %s", (SHORTENER_SETTING_ID,))
        row = cur.fetchone()
        cur.close()
        if row:
            return bool(row[0])
        return SHORTENER_ENABLED_DEFAULT
    except Exception as e:
        print(f"⚠️ Error getting shortener setting: {e}")
        return SHORTENER_ENABLED_DEFAULT
    finally:
        return_db_connection(conn)


def set_shortener_enabled(enabled: bool):
    if not mongo_ready():
        return
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO settings (setting_id, enabled, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (setting_id) 
            DO UPDATE SET enabled = %s, updated_at = CURRENT_TIMESTAMP
        """, (SHORTENER_SETTING_ID, bool(enabled), bool(enabled)))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"⚠️ Error setting shortener: {e}")
        conn.rollback()
    finally:
        return_db_connection(conn)


def get_shortener_enabled_for_user(username: str) -> bool:
    """Per-user shortener flag, fallback to global setting."""
    user = get_user_doc(username)
    if user is None:
        return get_shortener_enabled()
    if "shortener_enabled" in user:
        return bool(user.get("shortener_enabled"))
    return get_shortener_enabled()


def get_username_from_cookie():
    token = request.cookies.get("auth_token")
    if not token:
        return None
    try:
        username, _ = token.split("::", 1)
        return username
    except ValueError:
        return None


def is_admin_user(username: str) -> bool:
    if not username:
        return False
    user = get_user_doc(username)
    return bool(user and user.get("role", "user") == "admin")


def require_admin_json():
    uname = get_username_from_cookie()
    if not is_admin_user(uname):
        return jsonify({"success": False, "message": "Admin access required"}), 403
    return None



# ============================================================
# AUTH DECORATOR (PROTECTED ROUTES)
# ============================================================
def login_required(f):
    @wraps(f)
    def secured(*args, **kwargs):
        token = request.cookies.get("auth_token")
        if not token:
            return redirect("/login")

        try:
            username, ts = token.split("::", 1)
        except ValueError:
            return redirect("/login")

        user_doc = get_user_doc(username)
        if not user_doc:
            return redirect("/login")

        # Check subscription expiry
        if is_user_expired_doc(user_doc):
            print(f"⚠️  Subscription expired for user: {username} \n Contact Admin To Renew")
            return redirect("/login?error=expired")

        return f(*args, **kwargs)
    return secured


# ============================================================
# LOGIN ROUTE
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        # Render login page; if redirected with error show it
        err = request.args.get("error") or request.args.get("message", "")
        succ = request.args.get("success") or request.args.get("msg", "")
        # Map common codes
        if err == "unauthorized":
            err = "Admin access required."
        return render_template_string(LOGIN_TEMPLATE, error_message=err, success_message=succ)

    # POST: standard form submission (no JSON login)
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    if not username or not password:
        return render_template_string(LOGIN_TEMPLATE, error_message="Missing credentials")

    if not mongo_ready():
        return render_template_string(LOGIN_TEMPLATE, error_message="Database unavailable")

    user_doc = get_user_doc(username)
    if not user_doc or user_doc.get("password") != password:
        return render_template_string(LOGIN_TEMPLATE, error_message="Invalid username or password")

    # Subscription expiry check
    if is_user_expired_doc(user_doc):
        return render_template_string(LOGIN_TEMPLATE, error_message="Subscription expired. Contact admin.")

    # Determine expiry for logging
    expiry_dt = parse_expiry(user_doc.get("expiry")) or datetime.utcnow()

    # Generate auth token
    token = f"{username}::{time.time()}"

    # 🔍 Console debug info
    days_left = (expiry_dt - datetime.utcnow()).days
    print("=============================================")
    print(f"🔐 LOGIN SUCCESS for user: {username}")
    print(f"📅 Subscription expires on: {expiry_dt.strftime('%Y-%m-%d')}")
    print(f"⏳ Days left: {max(days_left, 0)} days")
    print("=============================================")

    resp = make_response(redirect("/?login=success"))
    resp.set_cookie("auth_token", token, max_age=30 * 24 * 3600, httponly=True)
    return resp
# ============================================================
# LOGOUT
# ============================================================
@app.route("/logout")
def logout():
    resp = make_response(redirect("/login"))
    resp.set_cookie("auth_token", "", max_age=0)
    return resp


# ============================================================
# ============================================================
# DEBUG ROUTE - Check Database Status
# ============================================================
@app.route("/api/debug/db-status")
def debug_db_status():
    """Debug endpoint to check database connection and tables"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        # Check if tables exist
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row[0] for row in cur.fetchall()]
        
        # Count users
        user_count = 0
        if 'users' in tables:
            cur.execute("SELECT COUNT(*) FROM users")
            user_count = cur.fetchone()[0]
        
        # Count settings
        settings_count = 0
        if 'settings' in tables:
            cur.execute("SELECT COUNT(*) FROM settings")
            settings_count = cur.fetchone()[0]
        
        cur.close()
        return_db_connection(conn)
        
        return jsonify({
            "connected": True,
            "tables": tables,
            "user_count": user_count,
            "settings_count": settings_count
        })
    except Exception as e:
        import traceback
        return jsonify({
            "connected": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

# ============================================================
# ADMIN PANEL ROUTES (PostgreSQL-backed)
# ============================================================
@app.route("/admin-panel")
@login_required
def admin_panel():
    if not mongo_ready():
        return "Database not available", 500
    if not is_admin_user(get_username_from_cookie()):
        return redirect("/login?error=unauthorized")
    return render_template_string(ADMIN_TEMPLATE)


@app.route("/api/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
    if not mongo_ready():
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    guard = require_admin_json()
    if guard:
        return guard

    if request.method == "GET":
        users = []
        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "message": "Database unavailable"}), 500
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()
            cur.close()
            for doc in rows:
                doc_dict = dict(doc)
                users.append(
                    {
                        "username": doc_dict.get("username", ""),
                        "expiry": doc_dict.get("expiry"),
                        "expired": bool(doc_dict.get("expired")) or is_user_expired_doc(doc_dict),
                        "shortener_enabled": bool(doc_dict.get("shortener_enabled", True)),
                    }
                )
            return jsonify({"success": True, "users": users, "total": len(users)})
        except Exception as e:
            print(f"⚠️ Error getting users: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
        finally:
            return_db_connection(conn)

    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    expiry = (data.get("expiry") or "").strip()
    days = data.get("days")
    role = (data.get("role") or "user").strip().lower()

    if not username or not password:
        return jsonify({"success": False, "message": "username and password required"}), 400

    # compute expiry
    if expiry:
        expiry_val = expiry
    elif days:
        try:
            days_int = int(days)
            if days_int <= 0:
                raise ValueError
            expiry_val = (datetime.utcnow() + timedelta(days=days_int)).strftime("%Y-%m-%d")
        except Exception:
            return jsonify({"success": False, "message": "Invalid days"}), 400
    else:
        return jsonify({"success": False, "message": "Provide expiry date or days"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    try:
        cur = conn.cursor()
        # Check if user exists
        cur.execute("SELECT username FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            cur.close()
            return jsonify({"success": False, "message": "User already exists"}), 400
        
        # Insert new user
        cur.execute("""
            INSERT INTO users (username, password, expiry, expired, shortener_enabled, role, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (username, password, expiry_val, False, True, role if role in ("admin", "user") else "user", datetime.utcnow()))
        conn.commit()
        cur.close()
        return jsonify({"success": True, "message": "User added"})
    except Exception as e:
        print(f"⚠️ Error adding user: {e}")
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        return_db_connection(conn)


@app.route("/api/admin/shortener", methods=["GET", "POST"])
@login_required
def admin_shortener():
    if not mongo_ready():
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    guard = require_admin_json()
    if guard:
        return guard

    if request.method == "GET":
        return jsonify({"success": True, "enabled": get_shortener_enabled()})

    data = request.get_json(force=True, silent=True) or {}
    enabled = bool(data.get("enabled"))
    set_shortener_enabled(enabled)
    return jsonify({"success": True, "enabled": enabled})


@app.route("/api/admin/user/shortener", methods=["POST"])
@login_required
def admin_user_shortener():
    if not mongo_ready():
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    guard = require_admin_json()
    if guard:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    enabled = bool(data.get("enabled"))
    if not username:
        return jsonify({"success": False, "message": "username required"}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET shortener_enabled = %s WHERE username = %s", (enabled, username))
        conn.commit()
        if cur.rowcount == 0:
            cur.close()
            return jsonify({"success": False, "message": "User not found"}), 404
        cur.close()
        return jsonify({"success": True, "enabled": enabled})
    except Exception as e:
        print(f"⚠️ Error updating user shortener: {e}")
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        return_db_connection(conn)


@app.route("/api/admin/user/update", methods=["POST"])
@login_required
def admin_user_update():
    if not mongo_ready():
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    guard = require_admin_json()
    if guard:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    new_username = (data.get("new_username") or "").strip() or username
    password = (data.get("password") or "").strip() or None
    expiry = (data.get("expiry") or "").strip() or None
    shortener_enabled = data.get("shortener_enabled")
    role = (data.get("role") or "").strip().lower() or None

    if not username:
        return jsonify({"success": False, "message": "username required"}), 400

    updates = {"username": new_username}
    if password:
        updates["password"] = password
    if expiry:
        updates["expiry"] = expiry
    if shortener_enabled is not None:
        updates["shortener_enabled"] = bool(shortener_enabled)
    if role:
        if role not in ("admin", "user"):
            return jsonify({"success": False, "message": "role must be admin or user"}), 400
        updates["role"] = role

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    try:
        cur = conn.cursor()
        # Build update query dynamically
        set_clauses = []
        values = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = %s")
            values.append(value)
        values.append(username)
        
        query = f"UPDATE users SET {', '.join(set_clauses)} WHERE username = %s"
        cur.execute(query, values)
        conn.commit()
        if cur.rowcount == 0:
            cur.close()
            return jsonify({"success": False, "message": "User not found"}), 404
        cur.close()
        return jsonify({"success": True})
    except Exception as e:
        print(f"⚠️ Error updating user: {e}")
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        return_db_connection(conn)


@app.route("/api/admin/user/delete", methods=["POST"])
@login_required
def admin_user_delete():
    if not mongo_ready():
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    guard = require_admin_json()
    if guard:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"success": False, "message": "username required"}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE username = %s", (username,))
        conn.commit()
        if cur.rowcount == 0:
            cur.close()
            return jsonify({"success": False, "message": "User not found"}), 404
        cur.close()
        return jsonify({"success": True})
    except Exception as e:
        print(f"⚠️ Error deleting user: {e}")
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        return_db_connection(conn)


@app.route("/api/admin/user/extend", methods=["POST"])
@login_required
def admin_user_extend():
    if not mongo_ready():
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    guard = require_admin_json()
    if guard:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    days = data.get("days")
    if not username:
        return jsonify({"success": False, "message": "username required"}), 400
    try:
        days_int = int(days)
        if days_int <= 0:
            raise ValueError
    except Exception:
        return jsonify({"success": False, "message": "Invalid days"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database unavailable"}), 500
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        if not user:
            cur.close()
            return jsonify({"success": False, "message": "User not found"}), 404

        user_dict = dict(user)
        current_expiry = parse_expiry(user_dict.get("expiry")) or datetime.utcnow()
        new_expiry = current_expiry + timedelta(days=days_int)
        
        cur.execute("UPDATE users SET expiry = %s WHERE username = %s", 
                   (new_expiry.strftime("%Y-%m-%d"), username))
        conn.commit()
        cur.close()
        return jsonify({"success": True, "new_expiry": new_expiry.strftime("%Y-%m-%d")})
    except Exception as e:
        print(f"⚠️ Error extending user: {e}")
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        return_db_connection(conn)


@app.route("/api/shortener/status")
@login_required
def shortener_status():
    username = get_username_from_cookie()
    per_user = get_shortener_enabled_for_user(username) if username else get_shortener_enabled()
    return jsonify({
        "enabled": per_user,
        "global_enabled": get_shortener_enabled()
    })


LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Login - FlipkartSniper 2.0</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0f1419;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: rgba(28, 36, 46, 0.98);
            border: 1px solid rgba(48, 54, 61, 0.8);
            border-radius: 16px;
            padding: 48px 40px;
            max-width: 420px;
            width: 100%;
            box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
            animation: slideUp 0.5s ease-out;
        }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .logo { text-align: center; margin-bottom: 36px; }
        .logo h1 {
            font-size: 2.2em;
            color: #e7e9eb;
            margin-bottom: 8px;
        }
        .logo p { color: #8b949e; font-size: 0.95em; }
        .form-group { margin-bottom: 22px; }
        label {
            display: block;
            margin-bottom: 8px;
            color: #e7e9eb;
            font-weight: 500;
            font-size: 0.9em;
        }
        input {
            width: 100%;
            padding: 14px 16px;
            border: 1px solid rgba(48, 54, 61, 0.8);
            border-radius: 8px;
            background: rgba(15, 20, 25, 0.9);
            color: #e7e9eb;
            font-size: 1em;
            transition: all 0.2s ease;
        }
        input:focus {
            outline: none;
            border-color: #58a6ff;
            box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15);
        }
        input::placeholder { color: #6e7681; }
        button {
            width: 100%;
            padding: 14px;
            background: #238636;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 8px;
        }
        button:hover {
            background: #2ea043;
            transform: translateY(-1px);
        }
        button:active {
            transform: translateY(0);
        }
.error-message,
.success-message {
            padding: 12px 14px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: none;
            font-size: 0.9em;
        }
.error-message {
    background: rgba(248, 81, 73, 0.1);
    border: 1px solid rgba(248, 81, 73, 0.4);
    color: #f85149;
}
.success-message {
    background: rgba(63, 185, 80, 0.1);
    border: 1px solid rgba(63, 185, 80, 0.4);
    color: #3fb950;
        }
        .admin-link {
            text-align: center;
            margin-top: 24px;
        }
        .admin-link a {
            color: #58a6ff;
            text-decoration: none;
            font-size: 0.9em;
        }
        .admin-link a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <h1>🎯 FlipkartSniper 2.0</h1>
            <p>Automated Deal Hunter</p>
        </div>

        <div class="error-message" id="errorMessage" style="{% if not error_message %}display:none;{% endif %}">{{ error_message or '' }}</div>
        <div class="success-message" id="successMessage" style="{% if not success_message %}display:none;{% endif %}">{{ success_message or '' }}</div>

        <form id="loginForm" method="POST" action="/login">
            <div class="form-group">
                <label>Username</label>
                <input type="text" id="username" name="username" placeholder="Enter your username" required autofocus>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" id="password" name="password" placeholder="Enter your password" required>
            </div>
            <button type="submit">🔓 Login</button>
        </form>

        <div class="admin-link">
          
        </div>
    </div>

</body>
</html>
"""

# ============================================================
# ADMIN PANEL TEMPLATE (PostgreSQL-backed)
# ============================================================
ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Panel - Users</title>
    <style>
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0A1828;
            color: #e6edf3;
            margin: 0;
            padding: 0;
        }
        .wrap {
            max-width: 900px;
            margin: 0 auto;
            padding: 32px 22px 48px;
        }
        h1 {
            margin: 0 0 12px;
            letter-spacing: 0.4px;
            color: #e7e9eb;
        }
        .card {
            background: rgba(28, 36, 46, 0.95);
            border: 1px solid rgba(48, 54, 61, 0.8);
            border-radius: 12px;
            padding: 18px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
            margin-bottom: 18px;
        }
        .row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 12px;
            margin-top: 12px;
        }
        label { display:block; margin-bottom:6px; font-weight:500; color:#e7e9eb; }
        input, button {
            width: 100%;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid rgba(48, 54, 61, 0.8);
            background: rgba(15, 20, 25, 0.9);
            color: #e7e9eb;
            font-size: 14px;
            box-sizing: border-box;
        }
        input:focus { outline:none; border-color:#58a6ff; box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15); }
        button {
            background: #238636;
            cursor: pointer;
            font-weight: 600;
            border: none;
        }
        button:hover { background: #2ea043; transform: translateY(-1px); }
        table { width:100%; border-collapse: collapse; margin-top: 12px; }
        th, td { padding: 10px 8px; border-bottom: 1px solid rgba(48, 54, 61, 0.8); text-align:left; }
        th { color: #8b949e; font-weight:600; }
        .pill { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }
        .pill.ok { background: rgba(63, 185, 80, 0.12); color:#3fb950; border:1px solid rgba(63, 185, 80, 0.3); }
        .pill.bad { background: rgba(248, 81, 73, 0.12); color:#f85149; border:1px solid rgba(248, 81, 73, 0.3); }
        .flex { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
        .muted { color:#8b949e; font-size:14px; }
        .toggle {
            display:inline-flex;
            align-items:center;
            gap:10px;
        }
        .toggle input { width:auto; }
        .status-dot {
            width:10px; height:10px; border-radius:50%; display:inline-block;
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="flex">
            <h1>Admin Panel</h1>
            <div>
                <a href="/" style="color:#178582; text-decoration:none; font-weight:700;">← Back to Dashboard</a>
            </div>
        </div>
        <p class="muted">Manage users from PostgreSQL and control the URL shortener toggle.</p>

        <div class="card">
            <div class="flex">
                <div>
                    <div class="muted">Total Users</div>
                    <div id="totalUsers" style="font-size:28px; font-weight:800;">0</div>
                </div>
                <div class="toggle">
                    <input type="checkbox" id="shortenerToggle">
                    <label for="shortenerToggle" style="cursor:pointer; font-weight:700;">URL Shortener</label>
                </div>
            </div>
        </div>

        <div class="card">
            <h3 style="margin-top:0;">Add User</h3>
            <form id="addUserForm">
                <div class="row">
                    <div>
                        <label>Username</label>
                        <input name="username" required placeholder="username">
                    </div>
                    <div>
                        <label>Password</label>
                        <input name="password" required placeholder="password">
                    </div>
                    <div>
                        <label>Expiry (YYYY-MM-DD)</label>
                        <input name="expiry" placeholder="2025-12-31">
                    </div>
                    <div>
                        <label>Days (alternative)</label>
                        <input name="days" type="number" min="1" placeholder="e.g. 30">
                    </div>
                    <div>
                        <label>Role</label>
                        <select name="role">
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                        </select>
                    </div>
                </div>
                <button type="submit" style="margin-top:12px;">Add User</button>
            </form>
            <div id="addUserMsg" class="muted" style="margin-top:8px;"></div>
        </div>

        <div class="card">
            <div class="flex">
                <h3 style="margin:0;">Users</h3>
                <span class="muted" id="lastRefreshed"></span>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Username</th>
                        <th>Expiry</th>
                        <th>Status</th>
                        <th>Shortener</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="usersTable">
                    <tr><td colspan="5" class="muted">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    <script>
        const usersTable = document.getElementById('usersTable');
        const totalUsersEl = document.getElementById('totalUsers');
        const lastRefreshed = document.getElementById('lastRefreshed');
        const shortenerToggle = document.getElementById('shortenerToggle');
        const addUserMsg = document.getElementById('addUserMsg');

        function fmtDate(d){
            const dt = new Date(d);
            if (isNaN(dt.getTime())) return d || 'N/A';
            return dt.toISOString().slice(0,10);
        }

        function renderUsers(users){
            if (!users || users.length === 0){
            usersTable.innerHTML = '<tr><td colspan="5" class="muted">No users</td></tr>';
                return;
            }
            usersTable.innerHTML = '';
            users.forEach(u=>{
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${u.username}</td>
                    <td>${fmtDate(u.expiry || '')}</td>
                    <td>
                        <span class="pill ${u.expired ? 'bad' : 'ok'}">
                            ${u.expired ? 'Expired' : 'Active'}
                        </span>
                    </td>
                <td>
                    <input type="checkbox" ${u.shortener_enabled ? 'checked' : ''} data-username="${u.username}" class="shortener-toggle">
                </td>
                <td style="display:flex; gap:6px; flex-wrap:wrap;">
                    <button type="button" class="btn-ghost" data-username="${u.username}" data-expiry="${u.expiry || ''}" data-shortener="${u.shortener_enabled ? '1' : '0'}" data-role="${u.role || 'user'}" onclick="openUpdateUser(this)">✏️ Update</button>
                    <button type="button" class="btn-ghost" style="color:var(--danger)" data-username="${u.username}" onclick="deleteUser(this)">🗑️ Delete</button>
                    <button type="button" class="btn-ghost" data-username="${u.username}" onclick="extendUser(this)">➕ Extend</button>
                </td>
                `;
                usersTable.appendChild(tr);
            });

        // Bind toggles
        usersTable.querySelectorAll('.shortener-toggle').forEach(cb=>{
            cb.addEventListener('change', (e)=>{
                const uname = e.target.getAttribute('data-username');
                const enabled = e.target.checked;
                fetch('/api/admin/user/shortener', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({username: uname, enabled})
                }).then(r=>r.json()).then(data=>{
                    if (!data.success) {
                        alert(data.message || 'Update failed');
                        e.target.checked = !enabled; // revert
                    }
                }).catch(()=>{
                    alert('Update failed');
                    e.target.checked = !enabled;
                });
            });
        });
        }

        function refreshUsers(){
            fetch('/api/admin/users')
                .then(r=>r.json())
                .then(data=>{
                    renderUsers(data.users || []);
                    totalUsersEl.textContent = data.total || 0;
                    lastRefreshed.textContent = 'Updated ' + new Date().toLocaleTimeString();
                })
                .catch(()=>{
                    usersTable.innerHTML = '<tr><td colspan="5" class="muted">Failed to load users</td></tr>';
                });
        }

        document.getElementById('addUserForm').addEventListener('submit', (e)=>{
            e.preventDefault();
            addUserMsg.textContent = 'Saving...';
            const form = new FormData(e.target);
            const payload = {
                username: form.get('username'),
                password: form.get('password'),
                expiry: form.get('expiry'),
                days: form.get('days'),
                role: form.get('role') || 'user'
            };
            fetch('/api/admin/users', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify(payload)
            }).then(r=>r.json()).then(data=>{
                if (data.success){
                    addUserMsg.textContent = '✅ User added';
                    e.target.reset();
                    refreshUsers();
                } else {
                    addUserMsg.textContent = '❌ ' + (data.message || 'Failed');
                }
            }).catch(err=>{
                addUserMsg.textContent = '❌ ' + err;
            });
        });

        function loadShortener(){
            fetch('/api/admin/shortener')
                .then(r=>r.json())
                .then(data=>{
                    shortenerToggle.checked = !!data.enabled;
                })
                .catch(()=>{});
        }

        shortenerToggle.addEventListener('change', ()=>{
            fetch('/api/admin/shortener', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({enabled: shortenerToggle.checked})
            }).catch(()=>{});
        });

function openUpdateUser(btn){
    const uname = btn.getAttribute('data-username');
    const currentExpiry = btn.getAttribute('data-expiry') || '';
    const currentShort = btn.getAttribute('data-shortener') === '1';
    const currentRole = btn.getAttribute('data-role') || 'user';
    const newUsername = prompt('New username (leave blank to keep)', uname) || uname;
    const newPassword = prompt('New password (leave blank to keep)', '');
    const newExpiry = prompt('New expiry YYYY-MM-DD (leave blank to keep)', currentExpiry) || currentExpiry;
    const roleStr = prompt('Role (admin/user, leave blank to keep)', currentRole) || currentRole;
    const shortStr = prompt('Shortener enabled? (yes/no, blank to keep)', currentShort ? 'yes' : 'no');
    let shortVal = currentShort;
    if (shortStr) {
        shortVal = ['yes','y','true','1'].includes(shortStr.toLowerCase());
    }
    fetch('/api/admin/user/update', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
            username: uname,
            new_username: newUsername,
            password: newPassword || null,
            expiry: newExpiry || null,
            shortener_enabled: shortVal,
            role: roleStr
        })
    }).then(r=>r.json()).then(data=>{
        if (!data.success) alert(data.message || 'Update failed');
        refreshUsers();
    }).catch(()=>alert('Update failed'));
}

function deleteUser(btn){
    const uname = btn.getAttribute('data-username');
    if (!confirm(`Delete user ${uname}?`)) return;
    fetch('/api/admin/user/delete', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({username: uname})
    }).then(r=>r.json()).then(data=>{
        if (!data.success) alert(data.message || 'Delete failed');
        refreshUsers();
    }).catch(()=>alert('Delete failed'));
}

function extendUser(btn){
    const uname = btn.getAttribute('data-username');
    const days = prompt('Enter days to extend subscription by:', '30');
    if (days === null) return;
    const n = parseInt(days,10);
    if (isNaN(n) || n <= 0) {
        alert('Enter a valid positive number of days.');
        return;
    }
    fetch('/api/admin/user/extend', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({username: uname, days: n})
    }).then(r=>r.json()).then(data=>{
        if (!data.success) alert(data.message || 'Extend failed');
        refreshUsers();
    }).catch(()=>alert('Extend failed'));
}

        refreshUsers();
        loadShortener();
    </script>
</body>
</html>
"""

# [INSERT THE ENTIRE MAIN_TEMPLATE FROM PREVIOUS ARTIFACT HERE - IT'S TOO LONG TO PASTE AGAIN]
# Copy the MAIN_TEMPLATE variable from the previous response above
MAIN_TEMPLATE = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>FlipkartSniper 2.0 Dashboard</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    display: flex;
    background: var(--bg);
    color: var(--text);
    transition: background 0.3s, color 0.3s;
    overflow-x: hidden;
}

:root {
    /* 🎨 SUBTLE PROFESSIONAL SLATE THEME */
    --bg: #0f1419;                           /* Deep charcoal */
    --bg2: #151b23;                          /* Slightly lighter */
    --card: rgba(28, 36, 46, 0.95);          /* Slate cards */
    --card-hover: rgba(36, 46, 58, 0.98);    /* Card hover */
    --text: #e7e9eb;                         /* Soft off-white */
    --text-muted: #8b949e;                   /* GitHub-style muted */
    --blue: #58a6ff;                         /* Soft blue accent */
    --blue-hover: #79b8ff;                   /* Lighter blue */
    --success: #3fb950;                      /* Soft green */
    --danger: #f85149;                       /* Soft red */
    --warning: #d29922;                      /* Muted gold */
    --border: rgba(48, 54, 61, 0.8);         /* Subtle border */
    --border-hover: rgba(68, 76, 86, 0.9);
    --shadow: rgba(0, 0, 0, 0.3);
    --glass: rgba(255, 255, 255, 0.03);
    --glass-strong: rgba(255, 255, 255, 0.06);
    --highlight: rgba(88, 166, 255, 0.1);
    --backdrop: rgba(0, 0, 0, 0.7);
    /* Subtle gradients */
    --gradient-primary: linear-gradient(135deg, #58a6ff 0%, #79b8ff 100%);
    --gradient-success: linear-gradient(135deg, #3fb950 0%, #56d364 100%);
    --gradient-danger: linear-gradient(135deg, #f85149 0%, #ff7b72 100%);
}

.light {
    /* Light variant - clean professional */
    --bg: #ffffff;
    --bg2: #f6f8fa;
    --card: rgba(255, 255, 255, 1);
    --card-hover: rgba(246, 248, 250, 1);
    --text: #24292f;
    --text-muted: #57606a;
    --blue: #0969da;
    --blue-hover: #218bff;
    --success: #1a7f37;
    --danger: #cf222e;
    --warning: #9a6700;
    --border: rgba(208, 215, 222, 0.8);
    --border-hover: rgba(175, 184, 193, 0.9);
    --shadow: rgba(0, 0, 0, 0.08);
}

/* Splash Screen */
#splashScreen {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: var(--bg);
    z-index: 10000;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    animation: fadeOut 0.5s ease-out 2s forwards;
    /* prevent invisible overlay blocking clicks */
    pointer-events: none;
}

@keyframes fadeOut {
    to {
        opacity: 0;
        visibility: hidden;
    }
}

.splash-content {
    text-align: center;
    animation: slideUp 0.8s ease-out;
}

.splash-logo {
    font-size: 4em;
    margin-bottom: 20px;
    animation: pulse 2s infinite;
}

.splash-title {
    font-size: 2.5em;
    font-weight: 700;
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 10px;
}

.splash-subtitle {
    font-size: 1.2em;
    color: var(--text-muted);
    margin-bottom: 30px;
}

.splash-loader {
    width: 50px;
    height: 50px;
    border: 4px solid var(--border);
    border-top-color: var(--blue);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin: 0 auto;
}

@keyframes slideInLeft {
    from { opacity: 0; transform: translateX(-30px); }
    to { opacity: 1; transform: translateX(0); }
}

@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.05); }
}

@keyframes glow {
    0%, 100% { box-shadow: 0 0 20px rgba(88, 166, 255, 0.4); }
    50% { box-shadow: 0 0 30px rgba(88, 166, 255, 0.6); }
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

@keyframes slideUp {
    from { opacity: 0; transform: translateY(30px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes shimmer {
    0% { transform: translateX(-100%) translateY(-100%) rotate(45deg); }
    100% { transform: translateX(100%) translateY(100%) rotate(45deg); }
}

@keyframes bounce {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-10px); }
}

@keyframes countUp {
    from { opacity: 0; transform: scale(0.5); }
    to { opacity: 1; transform: scale(1); }
}

@keyframes fadeOut {
    to {
        opacity: 0;
        transform: scale(0.9);
    }
}

@keyframes slide {
    0% { left: -100%; }
    100% { left: 100%; }
}

.sidebar {
    width: 280px;
    height: 100vh;
    background: var(--bg2);
    border-right: 2px solid var(--border);
    padding: 30px 20px;
    position: fixed;
    backdrop-filter: blur(10px);
    box-shadow: 5px 0 30px rgba(0, 0, 0, 0.3);
    animation: slideInLeft 0.6s ease-out;
    z-index: 100;
}

.sidebar-header {
    text-align: center;
    margin-bottom: 40px;
    padding-bottom: 20px;
    border-bottom: 2px solid var(--border);
}

.sidebar h2 {
    font-size: 1.8em;
    font-weight: 700;
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 5px;
    animation: pulse 2s infinite;
}

.sidebar-subtitle {
    font-size: 0.85em;
    color: var(--text);
    opacity: 0.7;
}

.menu-item {
    padding: 15px 20px;
    margin-bottom: 12px;
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.3s ease;
    display: flex;
    align-items: center;
    gap: 12px;
    font-weight: 500;
    border: 2px solid transparent;
    position: relative;
    overflow: hidden;
}

.menu-item::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(91, 124, 255, 0.2), transparent);
    transition: left 0.5s;
}

.menu-item:hover::before {
    left: 100%;
}

.menu-item:hover {
    background: var(--card);
    border-color: var(--blue);
    transform: translateX(5px);
}

.menu-item.active {
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    color: white;
    box-shadow: 0 5px 20px rgba(91, 124, 255, 0.4);
    animation: glow 2s infinite;
}

.menu-icon {
    font-size: 1.3em;
}

.nav-toggle {
    display: none;
    position: fixed;
    top: 16px;
    left: 16px;
    z-index: 110;
    background: var(--blue);
    color: #fff;
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    font-weight: 700;
    box-shadow: 0 6px 18px rgba(91, 124, 255, 0.35);
    cursor: pointer;
    transition: all 0.2s ease;
}

.nav-toggle:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 22px rgba(91, 124, 255, 0.45);
}

.sidebar-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.45);
    z-index: 90;
    backdrop-filter: blur(3px);
    opacity: 0;
    transition: opacity 0.25s ease;
}

body.sidebar-open .sidebar-overlay {
    display: block;
    opacity: 1;
}

.main {
    margin-left: 280px;
    padding: 30px;
    width: calc(100% - 280px);
    min-height: 100vh;
    background: var(--bg);
}

.card {
    background: var(--glass);
    padding: 30px;
    margin-bottom: 25px;
    border-radius: 18px;
    border: 1px solid var(--border);
    backdrop-filter: blur(18px);
    transition: all 0.35s ease, border-color 0.2s ease;
    animation: fadeInUp 0.6s ease-out;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
}

.card:hover {
    background: var(--glass-strong);
    transform: translateY(-6px) scale(1.01);
    border-color: var(--blue);
    box-shadow: 0 16px 50px rgba(0, 0, 0, 0.35);
}

.card h2, .card h3 {
    color: var(--blue);
    margin-bottom: 20px;
    font-weight: 600;
}

input, button, select, textarea {
    width: 100%;
    padding: 14px 18px;
    margin-top: 12px;
    border: 1.5px solid var(--border);
    border-radius: 14px;
    background: rgba(255,255,255,0.05);
    color: var(--text);
    font-size: 1em;
    transition: all 0.25s ease;
    backdrop-filter: blur(14px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 10px 28px rgba(0,0,0,0.18);
}

input:focus, select:focus, textarea:focus {
    outline: none;
    border-color: var(--blue);
    box-shadow: 0 0 0 6px rgba(23,133,130,0.16), inset 0 1px 0 rgba(255,255,255,0.08), 0 12px 30px rgba(0,0,0,0.22);
    transform: translateY(-1px) scale(1.01);
}

button {
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    color: white;
    cursor: pointer;
    font-weight: 700;
    letter-spacing: 0.3px;
    border: none;
    box-shadow: 0 6px 18px rgba(23,133,130,0.35);
    transition: all 0.25s ease;
}

button:hover {
    transform: translateY(-2px) scale(1.01);
    box-shadow: 0 10px 30px rgba(23,133,130,0.45);
}

button:active {
    transform: translateY(0);
}

button:disabled {
    background: grey;
    cursor: not-allowed;
    box-shadow: none;
    transform: none;
}

pre {
    background: #0d1117;
    color: #e6edf3;
    height: 300px;
    overflow-y: auto;
    padding: 20px;
    font-size: 14px;
    border-radius: 12px;
    border: 1px solid var(--border);
    font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    line-height: 1.6;
    box-shadow: inset 0 2px 10px rgba(0, 0, 0, 0.5);
    white-space: pre-wrap;
    word-break: break-all;
}

pre::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

pre::-webkit-scrollbar-track {
    background: #161b22;
}

pre::-webkit-scrollbar-thumb {
    background: #30363d;
    border-radius: 5px;
    border: 2px solid #161b22;
}

pre::-webkit-scrollbar-thumb:hover {
    background: #484f58;
}

.log-line {
    display: block;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);
}

.log-info { color: #8b949e; }
.log-success { color: #3fb950; font-weight: 500; }
.log-warning { color: #d29922; font-weight: 500; }
.log-error { color: #f85149; font-weight: 600; background: rgba(248, 81, 73, 0.1); padding: 2px 4px; border-radius: 4px; }
.log-debug { color: #d2a8ff; }
.log-timestamp { color: #58a6ff; font-weight: 600; margin-right: 8px; font-size: 0.9em; opacity: 0.8; }
.log-highlight { background: rgba(255, 255, 0, 0.2); color: #fff; text-decoration: underline; }

.hidden {
    display: none;
}

.toggle-switch {
    display: inline-flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    user-select: none;
    font-weight: 600;
    color: var(--text);
}
.toggle-switch input {
    display: none;
}
.toggle-labels {
    display: flex;
    flex-direction: column;
    line-height: 1.15;
    font-size: 12px;
    color: var(--text-muted);
    min-width: 70px;
}
.toggle-labels .on {
    color: var(--success);
    font-weight: 700;
    transition: color 0.25s ease;
}
.toggle-labels .off {
    color: var(--text-muted);
    font-weight: 600;
    transition: color 0.25s ease;
}
.toggle-track {
    position: relative;
    width: 92px;
    height: 44px;
    background: linear-gradient(135deg, rgba(23,133,130,0.14) 0%, rgba(191,161,129,0.1) 100%);
    border: 2px solid var(--border);
    border-radius: 24px;
    display: inline-flex;
    align-items: center;
    padding: 6px;
    transition: all 0.3s ease;
    box-shadow: 0 6px 16px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.04);
    overflow: hidden;
}
.toggle-thumb {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: linear-gradient(145deg, var(--blue) 0%, var(--blue-hover) 100%);
    color: white;
    display: grid;
    place-items: center;
    font-size: 14px;
    box-shadow: 0 10px 24px rgba(23,133,130,0.45);
    transition: transform 0.25s ease, background 0.25s ease, box-shadow 0.25s ease;
    transform: translateX(0);
    position: relative;
    z-index: 1;
    overflow: hidden;
}
.toggle-ripple {
    position: absolute;
    inset: 0;
    border-radius: 24px;
    background: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.08), transparent 40%),
                radial-gradient(circle at 70% 60%, rgba(255,255,255,0.05), transparent 45%);
    opacity: 0;
    transition: opacity 0.2s ease;
}
.toggle-switch input:checked ~ .toggle-labels .on {
    color: var(--success);
}
.toggle-switch input:checked ~ .toggle-labels .off {
    color: var(--text-muted);
}
.toggle-switch input:checked + .toggle-labels + .toggle-track {
    background: linear-gradient(135deg, rgba(23,133,130,0.35) 0%, rgba(23,133,130,0.22) 100%);
    border-color: var(--blue);
    box-shadow: 0 14px 32px rgba(23,133,130,0.45);
}
.toggle-switch input:checked + .toggle-labels + .toggle-track .toggle-thumb {
    transform: translateX(44px);
    background: linear-gradient(145deg, var(--success) 0%, var(--blue-hover) 100%);
    box-shadow: 0 10px 22px rgba(23,133,130,0.45);
}
.toggle-switch input:checked + .toggle-labels + .toggle-track .toggle-ripple {
    opacity: 1;
}
.toggle-thumb img {
    width: 16px;
    height: 16px;
    position: absolute;
    inset: 0;
    margin: auto;
    transition: opacity 0.2s ease;
}
.toggle-thumb .icon-off { opacity: 1; }
.toggle-thumb .icon-on { opacity: 0; }
.toggle-switch input:checked + .toggle-labels + .toggle-track .toggle-thumb .icon-off {
    opacity: 0;
}
.toggle-switch input:checked + .toggle-labels + .toggle-track .toggle-thumb .icon-on {
    opacity: 1;
}
.add-btn {
    background: linear-gradient(135deg, var(--success) 0%, #00c853 100%) !important;
    margin-top: 15px;
}

.add-btn:hover {
    box-shadow: 0 6px 25px rgba(0, 230, 118, 0.5) !important;
}

.warning-box {
    background: var(--glass-strong);
    border: 1.5px solid var(--border);
    border-left: 4px solid var(--warning);
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 20px;
    color: var(--text);
    font-weight: 600;
    box-shadow: 0 10px 24px rgba(0,0,0,0.18);
    animation: fadeIn 0.3s ease;
}

.warning-box .warning-item {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--warning);
}

.warning-item {
    margin: 5px 0;
    display: flex;
    align-items: center;
    gap: 10px;
}

.top-icons {
    position: relative;
    display: flex;
    gap: 10px;
    align-items: center;
    z-index: 1200;
    flex-shrink: 0;
}
.icon-btn {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--glass);
    border: 1.5px solid var(--border);
    color: var(--text);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s ease;
    box-shadow: 0 6px 20px rgba(0,0,0,0.15);
    font-size: 18px;
    padding: 0;
}
.icon-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 28px rgba(0,0,0,0.2);
}
.icon-btn.danger {
    color: var(--danger);
    border-color: var(--danger);
}

@media (max-width: 600px) {
    .top-icons {
        gap: 8px;
    }
    .icon-btn {
        width: 36px;
        height: 36px;
        font-size: 16px;
        border-radius: 50%;
    }
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 20px;
    margin-bottom: 30px;
}

.stat-card {
    background: var(--card);
    padding: 25px;
    border-radius: 12px;
    border: 2px solid var(--border);
    text-align: center;
    transition: all 0.3s ease;
    animation: fadeInUp 0.6s ease-out;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
    position: relative;
    overflow: hidden;
}

.stat-card::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: linear-gradient(45deg, transparent, rgba(91, 124, 255, 0.1), transparent);
    transform: rotate(45deg);
    animation: shimmer 3s infinite;
}

.stat-card:hover {
    transform: translateY(-10px) scale(1.05);
    box-shadow: 0 10px 35px rgba(91, 124, 255, 0.3);
}

.stat-icon {
    font-size: 2.5em;
    margin-bottom: 10px;
    animation: bounce 2s infinite;
}

.stat-label {
    font-size: 0.9em;
    opacity: 0.8;
    margin-bottom: 5px;
}

.stat-value {
    font-size: 2em;
    font-weight: 700;
    color: var(--blue);
    animation: countUp 1s ease-out;
}

.progress-ring-container {
    width: 180px;
    height: 180px;
    margin: 0 auto 20px;
    position: relative;
}

.progress-ring {
    transform: rotate(-90deg);
}

.progress-ring-circle {
    transition: stroke-dashoffset 0.5s ease;
    transform-origin: 50% 50%;
}

.progress-text {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 2em;
    font-weight: 700;
    color: var(--blue);
}

.progress-label {
    text-align: center;
    font-size: 1.1em;
    color: var(--text);
    opacity: 0.9;
    margin-top: 10px;
}

.dashboard-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 30px;
    margin-bottom: 30px;
}

.big-stat-card {
    background: var(--card);
    padding: 40px;
    border-radius: 16px;
    border: 2px solid var(--border);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
    transition: all 0.3s ease;
    animation: fadeInUp 0.6s ease-out;
}

.big-stat-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 12px 40px rgba(91, 124, 255, 0.3);
}

.percentage-bar {
    width: 100%;
    height: 12px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 10px;
    overflow: hidden;
    margin-top: 15px;
    position: relative;
}

.percentage-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--success) 0%, #00c853 100%);
    border-radius: 10px;
    transition: width 1s ease-out;
    position: relative;
    overflow: hidden;
}

.percentage-fill::after {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
    animation: slide 2s infinite;
}

.percentage-text {
    display: flex;
    justify-content: space-between;
    margin-top: 10px;
    font-size: 0.9em;
    opacity: 0.8;
}

.product-row {
    display: flex;
    gap: 15px;
    margin-bottom: 15px;
    animation: fadeInUp 0.4s ease-out;
    align-items: flex-end;
}

.delete-product-btn {
    background: linear-gradient(135deg, var(--danger) 0%, #ff5252 100%) !important;
    color: white;
    border: none;
    border-radius: 50%;
    width: 45px;
    height: 45px;
    min-width: 45px;
    cursor: pointer;
    font-size: 1.3em;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.3s ease;
    box-shadow: 0 4px 15px rgba(255, 23, 68, 0.3);
    padding: 0;
    margin: 0;
    margin-bottom: 2px;
}

.delete-product-btn:hover {
    transform: rotate(90deg) scale(1.1);
    box-shadow: 0 6px 25px rgba(255, 23, 68, 0.5);
}

.page-title {
    font-size: 2.5em;
    font-weight: 700;
    margin-bottom: 30px;
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: fadeInUp 0.6s ease-out;
}

/* ================= REPORTS SECTION - REDESIGNED ================= */

.reports-header {
    margin-bottom: 24px;
}

.reports-header-content {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    flex-wrap: wrap;
}

.reports-subtitle {
    color: var(--text-muted);
    font-size: 0.95em;
    margin-top: 4px;
}

.btn-refresh {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    background: rgba(88, 166, 255, 0.1);
    border: 1px solid rgba(88, 166, 255, 0.3);
    border-radius: 10px;
    color: var(--blue);
    font-weight: 600;
    font-size: 0.9em;
    cursor: pointer;
    transition: all 0.2s ease;
}

.btn-refresh:hover {
    background: rgba(88, 166, 255, 0.2);
    transform: translateY(-1px);
}

.refresh-icon {
    transition: transform 0.3s ease;
}

.btn-refresh:hover .refresh-icon {
    transform: rotate(180deg);
}

/* Reports Stats Bar */
.reports-stats-bar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    padding: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 20px;
}

.reports-stats-bar .stat-item {
    text-align: center;
    padding: 8px;
}

.reports-stats-bar .stat-label {
    display: block;
    font-size: 0.8em;
    color: var(--text-muted);
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.reports-stats-bar .stat-value {
    font-size: 1.5em;
    font-weight: 700;
    color: var(--blue);
}

/* Reports Content Card */
.reports-content-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
}

.reports-content-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 24px;
    border-bottom: 1px solid var(--border);
    background: rgba(0, 0, 0, 0.2);
}

.reports-content-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 1.1em;
    font-weight: 600;
    color: var(--text);
    margin: 0;
}

.title-icon {
    font-size: 1.2em;
}

.reports-loading {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 0.9em;
}

.loading-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--blue);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

/* Reports Grid */
.reports-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
    padding: 20px;
}

.report-card {
    background: rgba(28, 36, 46, 0.6);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    transition: all 0.25s ease;
    position: relative;
    overflow: hidden;
}

.report-card:hover {
    border-color: var(--blue);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

.report-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--blue) 0%, var(--success) 100%);
    opacity: 0;
    transition: opacity 0.25s ease;
}

.report-card:hover::before {
    opacity: 1;
}

.report-card-header {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    margin-bottom: 16px;
}

.report-icon {
    width: 48px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(88, 166, 255, 0.12);
    border: 1px solid rgba(88, 166, 255, 0.25);
    border-radius: 12px;
    font-size: 1.5em;
    flex-shrink: 0;
}

.report-title {
    flex: 1;
    font-size: 1em;
    font-weight: 600;
    color: var(--text);
    line-height: 1.4;
    word-break: break-word;
}

.report-info {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 16px;
    padding: 12px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 10px;
}

.report-info-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.85em;
}

.report-info-item .label {
    color: var(--text-muted);
}

.report-info-item .value {
    color: var(--text);
    font-weight: 500;
}

.report-actions {
    display: flex;
    gap: 10px;
}

.report-btn {
    flex: 1;
    padding: 12px 16px;
    border: none;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.9em;
    cursor: pointer;
    transition: all 0.2s ease;
    text-decoration: none;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
}

.report-btn-view {
    background: var(--blue);
    color: white;
}

.report-btn-view:hover {
    background: var(--blue-hover);
    transform: translateY(-1px);
}

.report-btn-download {
    background: rgba(255, 255, 255, 0.05);
    color: var(--text);
    border: 1px solid var(--border);
}

.report-btn-download:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: var(--text-muted);
}

/* Report Modal */
.report-modal-content {
    width: 100%;
    max-width: 900px;
    max-height: 90vh;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 20px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    position: relative;
    box-shadow: 0 25px 80px rgba(0, 0, 0, 0.5);
}

.report-table-container {
    flex: 1;
    overflow: auto;
    padding: 20px;
    background: var(--bg);
}

.report-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9em;
}

.report-table th {
    position: sticky;
    top: 0;
    background: var(--bg2);
    padding: 14px 12px;
    text-align: left;
    font-weight: 600;
    color: var(--text-muted);
    border-bottom: 2px solid var(--border);
}

.report-table td {
    padding: 12px;
    border-bottom: 1px solid var(--border);
    color: var(--text);
}

.report-table tr:hover td {
    background: rgba(88, 166, 255, 0.05);
}

.report-modal-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 24px;
    border-top: 1px solid var(--border);
    background: rgba(0, 0, 0, 0.2);
    gap: 12px;
    flex-wrap: wrap;
}

/* Empty State */
.reports-empty {
    text-align: center;
    padding: 60px 20px;
    color: var(--text-muted);
}

.reports-empty-icon {
    font-size: 4em;
    margin-bottom: 16px;
    opacity: 0.5;
}

.reports-empty-title {
    font-size: 1.3em;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 8px;
}

/* Mobile Reports */
@media (max-width: 768px) {
    .reports-header-content {
        flex-direction: column;
        align-items: stretch;
    }
    
    .btn-refresh {
        width: 100%;
        justify-content: center;
    }
    
    .reports-stats-bar {
        grid-template-columns: repeat(3, 1fr);
        padding: 12px;
    }
    
    .reports-stats-bar .stat-value {
        font-size: 1.2em;
    }
    
    .reports-grid {
        grid-template-columns: 1fr;
        padding: 16px;
        gap: 12px;
    }
    
    .report-card {
        padding: 16px;
    }
    
    .report-icon {
        width: 42px;
        height: 42px;
        font-size: 1.3em;
    }
    
    .report-actions {
        flex-direction: column;
    }
    
    .report-btn {
        padding: 14px;
    }
    
    .report-modal-content {
        max-width: 100%;
        max-height: 95vh;
        border-radius: 20px 20px 0 0;
    }
    
    .report-table {
        font-size: 0.8em;
        display: block;
        overflow-x: auto;
    }
    
    .report-modal-footer {
        flex-direction: column;
        padding: 14px 16px;
    }
    
    .report-modal-footer > div {
        width: 100%;
        display: flex;
        gap: 10px;
    }
}

@media (max-width: 480px) {
    .reports-stats-bar .stat-label {
        font-size: 0.7em;
    }
    
    .reports-stats-bar .stat-value {
        font-size: 1em;
    }
    
    .report-card {
        padding: 14px;
    }
    
    .report-table th,
    .report-table td {
        padding: 8px 6px;
        font-size: 0.75em;
    }
}

/* Reports Grid Layout */
.reports-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
    margin-top: 16px;
}

.report-card {
    background: linear-gradient(135deg, rgba(23,133,130,0.14) 0%, rgba(17,38,60,0.78) 100%);
    border: 1.5px solid var(--border);
    border-radius: 16px;
    padding: 18px;
    transition: all 0.28s ease;
    position: relative;
    overflow: hidden;
    animation: fadeInUp 0.5s ease-out;
    box-shadow: 0 14px 32px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(10px);
}

.report-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--blue) 0%, var(--blue-hover) 100%);
    transform: scaleX(0);
    transform-origin: left;
    transition: transform 0.3s ease;
}

.report-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 16px 34px rgba(23,133,130,0.32);
    border-color: var(--blue);
}

.report-card:hover::before {
    transform: scaleX(1);
}

.report-card-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 15px;
}

.report-icon {
    font-size: 2.5em;
    width: 60px;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, rgba(91, 124, 255, 0.2) 0%, rgba(123, 156, 255, 0.2) 100%);
    border-radius: 12px;
    border: 2px solid rgba(91, 124, 255, 0.3);
}

.report-title {
    flex: 1;
    font-size: 1.2em;
    font-weight: 600;
    color: var(--text);
}

.report-info {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 20px;
    font-size: 0.9em;
    color: var(--text-muted);
}

.report-info-item {
    display: flex;
    align-items: center;
    gap: 8px;
}

.report-info-item strong {
    color: var(--text);
    min-width: 80px;
}

.report-actions {
    display: flex;
    gap: 10px;
    margin-top: 15px;
}
.report-actions button {
    width: 100%;
    padding: 11px;
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    color: white;
    border: 1px solid var(--border);
    border-radius: 12px;
    font-size: 0.95em;
    font-weight: 700;
    letter-spacing: 0.3px;
    cursor: pointer;
    transition: all 0.22s ease;
    box-shadow: 0 10px 22px rgba(23,133,130,0.32);
}
.report-actions button:hover {
    transform: translateY(-2px);
    box-shadow: 0 14px 30px rgba(23,133,130,0.4);
}

/* Logs page glass layout */
.logs-shell {
    display: grid;
    grid-template-columns: 280px 1fr;
    gap: 20px;
    height: calc(100vh - 200px);
    min-height: 500px;
}

.logs-panel {
    border: 1.5px solid var(--border);
    border-radius: 16px;
    padding: 16px;
    background: var(--bg2);
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
}

.logs-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}

.logs-viewer-container {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
    background: #0d1117;
    border: 1.5px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 15px 40px rgba(0,0,0,0.3);
}

.logs-viewer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    background: #161b22;
    border-bottom: 1px solid var(--border);
    gap: 15px;
    flex-wrap: wrap;
}

.logs-viewer-controls {
    display: flex;
    align-items: center;
    gap: 12px;
}

.logs-search-box {
    position: relative;
    flex: 1;
    max-width: 300px;
}

.logs-search-box input {
    width: 100%;
    padding: 8px 12px 8px 35px;
    font-size: 0.9em;
    height: 36px;
    margin: 0;
    background: #0d1117;
    border: 1px solid var(--border);
}

.logs-search-box i {
    position: absolute;
    left: 12px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
    font-size: 0.9em;
}

.logs-viewer {
    flex: 1;
    margin: 0;
    border: none;
    border-radius: 0;
    height: 100%;
    background: transparent;
    padding: 15px 20px;
    box-shadow: none;
}

.logs-list-container {
    flex: 1;
    overflow-y: auto;
    padding-right: 4px;
}

.logs-list-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    border: 1px solid transparent;
    border-radius: 10px;
    margin-bottom: 6px;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    background: rgba(255,255,255,0.03);
}

.logs-list-item:hover {
    background: rgba(255,255,255,0.06);
    border-color: var(--border);
    transform: translateY(-1px);
}

.logs-list-item.active {
    background: var(--highlight);
    border-color: var(--blue);
    position: relative;
}

.logs-list-item.active::after {
    content: '';
    position: absolute;
    left: -16px;
    top: 50%;
    transform: translateY(-50%);
    width: 4px;
    height: 20px;
    background: var(--blue);
    border-radius: 0 4px 4px 0;
}

.logs-file-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
}

.logs-file-name {
    font-weight: 600;
    font-size: 0.95em;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.logs-file-meta {
    font-size: 0.8em;
    color: var(--text-muted);
}

@media (max-width: 992px) {
    .logs-shell {
        grid-template-columns: 1fr;
        height: auto;
    }
    .logs-panel {
        max-height: 250px;
    }
    .logs-viewer-container {
        height: 500px;
    }
}

.report-btn {
    flex: 1;
    padding: 12px 18px;
    border: none;
    border-radius: 10px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.3s ease;
    text-decoration: none;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    font-size: 0.95em;
}

.report-btn-view {
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    color: white;
    box-shadow: 0 4px 15px rgba(91, 124, 255, 0.3);
}

.report-btn-view:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(91, 124, 255, 0.5);
}

.report-btn-download {
    background: var(--bg2);
    color: var(--text);
    border: 2px solid var(--border);
}

.report-btn-download:hover {
    background: var(--card);
    border-color: var(--blue);
    transform: translateY(-2px);
}

/* Onboarding tour */
.tour-overlay {
    position: fixed;
    inset: 0;
    background: var(--backdrop);
    backdrop-filter: blur(6px);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 20000;
}
.tour-modal {
    width: min(540px, 92vw);
    background: var(--glass-strong);
    border: 1.5px solid var(--border);
    border-radius: 18px;
    padding: 24px;
    box-shadow: 0 18px 60px rgba(0,0,0,0.4);
    backdrop-filter: blur(14px);
    animation: fadeInUp 0.35s ease;
}
.tour-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 1.25em;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 8px;
}
.tour-body {
    color: var(--text-muted);
    line-height: 1.5;
    margin-bottom: 18px;
}
.tour-steps {
    font-size: 0.9em;
    color: var(--text-muted);
    margin-bottom: 6px;
}
.tour-actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
}
.btn-ghost {
    background: transparent;
    border: 1.5px solid var(--border);
    color: var(--text);
}

/* Guided spotlight tour */
.guided-overlay {
    position: fixed;
    inset: 0;
    display: none;
    z-index: 22000;
    pointer-events: auto;
}
.guided-spotlight {
    position: absolute;
    border: 2px solid var(--blue);
    border-radius: 14px;
    box-shadow:
        0 0 0 9999px var(--backdrop),
        0 12px 40px rgba(0,0,0,0.55),
        0 0 0 2px rgba(23,133,130,0.25);
    background: rgba(23,133,130,0.06);
    pointer-events: none;
    transition: all 0.25s ease;
}
.guided-tooltip {
    position: absolute;
    max-width: 320px;
    background: var(--glass-strong);
    border: 1.5px solid var(--border);
    border-radius: 14px;
    padding: 14px 16px;
    color: var(--text);
    box-shadow: 0 14px 40px rgba(0,0,0,0.45);
    backdrop-filter: blur(12px);
    pointer-events: auto;
    z-index: 1;
}
.guided-tooltip:after {
    content: '';
    position: absolute;
    width: 12px;
    height: 12px;
    background: var(--glass-strong);
    border-left: 1.5px solid var(--border);
    border-top: 1.5px solid var(--border);
    transform: rotate(45deg);
    top: -7px;
    left: 24px;
}
.guided-tooltip.tip-above:after {
    top: auto;
    bottom: -7px;
    transform: rotate(225deg);
}
.guided-tooltip h4 {
    margin: 0 0 6px;
    font-size: 1.02em;
    font-weight: 700;
}
.guided-tooltip p {
    margin: 0 0 12px;
    color: var(--text-muted);
    line-height: 1.45;
}
.guided-controls {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
}
.guided-btn {
    border: 1.5px solid var(--border);
    border-radius: 10px;
    background: var(--glass);
    color: var(--text);
    padding: 8px 14px;
    cursor: pointer;
    transition: all 0.2s ease;
}
.guided-btn.primary {
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    color: #fff;
    border-color: var(--blue-hover);
    box-shadow: 0 10px 26px rgba(23,133,130,0.35);
}
.guided-btn:hover {
    transform: translateY(-1px);
}

/* Lock scroll during guided tour */
body.tour-lock {
    overflow: hidden;
}

.report-empty-state {
    grid-column: 1 / -1;
    text-align: center;
    padding: 60px 20px;
    color: var(--text-muted);
}

.report-empty-icon {
    font-size: 4em;
    margin-bottom: 20px;
    opacity: 0.5;
}

.report-empty-text {
    font-size: 1.2em;
    margin-bottom: 10px;
}

.report-empty-subtext {
    font-size: 0.9em;
    opacity: 0.7;
}

/* Report Modal Table - Modern Gradient Design */
.report-modal-content {
    max-width: 92vw;
    width: 1200px;
    max-height: 90vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    border-radius: 24px;
    background: linear-gradient(135deg, #0f172a 0%, #581c87 50%, #0f172a 100%);
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    animation: modalSlideIn 0.3s ease-out;
    position: relative;
}

@keyframes modalSlideIn {
    from {
        opacity: 0;
        transform: scale(0.95) translateY(20px);
    }
    to {
        opacity: 1;
        transform: scale(1) translateY(0);
    }
}

.report-table-container {
    overflow-x: auto;
    overflow-y: auto;
    max-height: calc(90vh - 240px);
    margin: 0;
    padding: 24px;
    background: transparent;
    -webkit-overflow-scrolling: touch;
}

@media (max-width: 768px) {
    .report-table-container {
        padding: 12px;
        max-height: calc(95vh - 200px);
    }
}

@media (max-width: 480px) {
    .report-table-container {
        padding: 8px;
        max-height: calc(100vh - 220px);
    }
}

.report-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.95em;
    min-width: 600px;
}

.report-modal-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 20px 24px;
    background: rgba(30, 41, 59, 0.5);
    border-top: 1px solid rgba(148, 163, 184, 0.2);
    flex-wrap: wrap;
}

@media (max-width: 768px) {
    .report-modal-footer {
        flex-direction: column;
        align-items: stretch;
        gap: 12px;
        padding: 16px;
    }
    
    .report-modal-footer > div {
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    
    .report-modal-footer a,
    .report-modal-footer button {
        width: 100%;
        padding: 12px;
        text-align: center;
    }
    
    .report-modal-footer p {
        text-align: center;
        margin-bottom: 8px;
    }
}

.report-table thead {
    position: sticky;
    top: 0;
    z-index: 10;
}

.report-table th {
    background: transparent;
    color: rgba(148, 163, 184, 1);
    padding: 16px 12px;
    text-align: left;
    font-weight: 600;
    font-size: 0.9em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.3);
    position: sticky;
    top: 0;
}

.report-table td {
    padding: 16px 12px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.1);
    color: rgba(226, 232, 240, 1);
    background: transparent;
    transition: all 0.2s ease;
}

.report-table tbody tr {
    transition: all 0.2s ease;
    animation: rowSlideIn 0.3s ease-out backwards;
}

@keyframes rowSlideIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.report-table tbody tr:hover {
    background: rgba(168, 85, 247, 0.1);
    transform: translateX(2px);
}

.report-table tbody tr:nth-child(even) {
    background: rgba(15, 23, 42, 0.3);
}

.report-table tbody tr:nth-child(even):hover {
    background: rgba(168, 85, 247, 0.15);
}

/* Responsive Design for Reports */
@media (max-width: 768px) {
    .reports-grid {
        grid-template-columns: 1fr;
        gap: 15px;
    }
    
    .report-card {
        padding: 20px;
    }
    
    .report-actions {
        flex-direction: column;
    }
    
    .report-btn {
        width: 100%;
    }
    
    .report-modal-content {
        max-width: 100vw;
        width: 100%;
        max-height: 95vh;
        margin: 0;
        border-radius: 0;
    }
    
    .report-modal-header-gradient {
        padding: 16px !important;
        padding-right: 50px !important;
    }
    
    .report-modal-header-gradient h2 {
        font-size: 18px !important;
    }
    
    .report-modal-header-gradient p {
        font-size: 12px !important;
    }
    
    .report-modal-header-gradient > div > div:first-child {
        padding: 8px !important;
    }
    
    .report-modal-header-gradient > div > div:first-child span {
        font-size: 20px !important;
    }
    
    .report-modal-content > button {
        top: 6px !important;
        right: 6px !important;
        padding: 4px !important;
        width: 24px !important;
        height: 24px !important;
    }
    
    .report-modal-content > button svg {
        width: 14px !important;
        height: 14px !important;
    }
    
    .report-table-container {
        max-height: calc(95vh - 240px);
        padding: 12px;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
    }
    
    .report-table {
        font-size: 0.85em;
        min-width: 600px;
    }
    
    .report-table th,
    .report-table td {
        padding: 10px 8px;
        font-size: 0.85em;
    }
}

@media (max-width: 480px) {
    .report-modal-content {
        max-height: 100vh;
        border-radius: 0;
    }
    
    .report-modal-header-gradient {
        padding: 12px !important;
        padding-right: 45px !important;
    }
    
    .report-modal-header-gradient h2 {
        font-size: 16px !important;
    }
    
    .report-modal-header-gradient p {
        font-size: 11px !important;
    }
    
    .report-modal-header-gradient > div > div:first-child {
        padding: 6px !important;
    }
    
    .report-modal-header-gradient > div > div:first-child span {
        font-size: 18px !important;
    }
    
    .report-modal-content > button {
        top: 4px !important;
        right: 4px !important;
        padding: 4px !important;
        width: 22px !important;
        height: 22px !important;
    }
    
    .report-modal-content > button svg {
        width: 12px !important;
        height: 12px !important;
    }
    
    .report-table-container {
        max-height: calc(100vh - 240px);
        padding: 8px;
    }
    
    .report-table {
        font-size: 0.75em;
        min-width: 500px;
    }
    
    .report-table th,
    .report-table td {
        padding: 8px 6px;
        font-size: 0.75em;
    }
    
    .report-modal-footer {
        padding: 12px !important;
    }
    
    .report-modal-footer p {
        font-size: 12px !important;
    }
}

/* Toast notifications */
.toast-container {
    position: fixed;
    top: 18px;
    right: 18px;
    z-index: 2000;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.toast {
    min-width: 260px;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1.5px solid var(--border);
    background: linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%);
    color: var(--text);
    box-shadow: 0 14px 36px rgba(0,0,0,0.25);
    animation: toast-pop 0.28s ease, toast-fade 0.28s ease 3.5s forwards;
    display: flex;
    align-items: center;
    gap: 12px;
    font-weight: 600;
    backdrop-filter: blur(12px);
    position: relative;
    overflow: hidden;
}

.toast-success {
    border-color: var(--success);
    background: rgba(23,133,130, 0.12);
    color: var(--success);
}

.toast-error {
    border-color: var(--danger);
    background: rgba(248, 81, 73, 0.12);
    color: var(--danger);
}

@keyframes toast-pop {
    from { transform: translateY(10px) scale(0.97); opacity: 0; }
    to { transform: translateY(0) scale(1); opacity: 1; }
}

@keyframes toast-fade {
    to { opacity: 0; transform: translateY(-6px); }
}

.toast::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg, rgba(255,255,255,0.08), transparent 60%);
    opacity: 0.35;
    pointer-events: none;
}
.toast-icon {
    width: 26px;
    height: 26px;
    border-radius: 8px;
    display: grid;
    place-items: center;
    font-size: 14px;
    background: rgba(255,255,255,0.08);
}
.toast-text {
    flex: 1;
    line-height: 1.35;
}

@media (max-width: 480px) {
    .report-card-header {
        flex-direction: column;
        align-items: flex-start;
    }
    
    .report-icon {
        width: 50px;
        height: 50px;
        font-size: 2em;
    }
    
    .report-table {
        font-size: 0.75em;
        min-width: 400px;
    }
}

/* ==================== CYBERPUNK SPLASH SCREEN ==================== */
.splash-screen {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: #0a0a0f;
    z-index: 99999;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    animation: fadeOut 0.6s ease-out 3.5s forwards;
}

.splash-background {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    z-index: 1;
    background: 
        linear-gradient(0deg, transparent 24%, rgba(0, 255, 255, 0.05) 25%, rgba(0, 255, 255, 0.05) 26%, transparent 27%, transparent 74%, rgba(0, 255, 255, 0.05) 75%, rgba(0, 255, 255, 0.05) 76%, transparent 77%, transparent),
        linear-gradient(90deg, transparent 24%, rgba(0, 255, 255, 0.05) 25%, rgba(0, 255, 255, 0.05) 26%, transparent 27%, transparent 74%, rgba(0, 255, 255, 0.05) 75%, rgba(0, 255, 255, 0.05) 76%, transparent 77%, transparent);
    background-size: 50px 50px;
    background-color: #0a0a0f;
    animation: gridMove 20s linear infinite;
}

@keyframes gridMove {
    0% { background-position: 0 0; }
    100% { background-position: 50px 50px; }
}

.splash-background::before {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at 50% 50%, rgba(0, 255, 255, 0.1), transparent 70%);
    animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 0.3; }
    50% { opacity: 0.6; }
}

.splash-content {
    text-align: center;
    position: relative;
    z-index: 10;
    animation: contentFadeIn 0.8s cubic-bezier(0.23, 1, 0.32, 1);
}

@keyframes contentFadeIn {
    0% {
        opacity: 0;
        transform: scale(0.95);
    }
    100% {
        opacity: 1;
        transform: scale(1);
    }
}

.splash-title {
    font-size: 5.5rem;
    font-weight: 900;
    margin: 0;
    margin-bottom: 30px;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Courier New', monospace;
    text-transform: uppercase;
    letter-spacing: 12px;
    position: relative;
    color: #00ffff;
    text-shadow: 
        0 0 10px #00ffff,
        0 0 20px #00ffff,
        0 0 40px #00ffff,
        0 0 80px #00ffff,
        0 0 120px #00ffff;
    animation: 
        titleEntry 1.5s cubic-bezier(0.23, 1, 0.32, 1) forwards,
        ultraGlitch 3s infinite 1.5s,
        titleExit 0.8s ease-in 2.8s forwards;
    opacity: 0;
    transform: scale(0.3) translateY(100px);
    filter: blur(20px);
}

@keyframes titleEntry {
    0% {
        opacity: 0;
        transform: scale(0.3) translateY(100px) rotateX(80deg) rotateZ(-5deg);
        filter: blur(20px) brightness(0.5);
    }
    60% {
        opacity: 1;
        transform: scale(1.05) translateY(-15px) rotateX(0deg) rotateZ(0deg);
        filter: blur(2px) brightness(1.3);
    }
    100% {
        opacity: 1;
        transform: scale(1) translateY(0) rotateX(0deg) rotateZ(0deg);
        filter: blur(0) brightness(1);
    }
}

@keyframes titleExit {
    0% {
        opacity: 1;
        transform: scale(1) translateY(0);
        filter: blur(0);
    }
    100% {
        opacity: 0;
        transform: scale(0.7) translateY(-80px);
        filter: blur(10px);
    }
}

.splash-title::before,
.splash-title::after {
    content: attr(data-text);
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    mix-blend-mode: screen;
}

.splash-title::before {
    left: 3px;
    text-shadow: -3px 0 #ff00ff;
    clip-path: polygon(0 0, 100% 0, 100% 45%, 0 45%);
    animation: glitchTop 0.5s infinite cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.splash-title::after {
    left: -3px;
    text-shadow: 3px 0 #00ff00;
    clip-path: polygon(0 55%, 100% 55%, 100% 100%, 0 100%);
    animation: glitchBottom 0.3s infinite cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

@keyframes ultraGlitch {
    0%, 50%, 100% {
        transform: translate(0);
        filter: hue-rotate(0deg);
    }
    10% {
        transform: translate(-5px, 5px);
        filter: hue-rotate(90deg);
    }
    20% {
        transform: translate(5px, -5px);
        filter: hue-rotate(180deg);
    }
    30% {
        transform: translate(-5px, -5px);
        filter: hue-rotate(270deg);
    }
    40% {
        transform: translate(5px, 5px);
        filter: hue-rotate(360deg);
    }
}

@keyframes glitchTop {
    0% {
        clip-path: polygon(0 0, 100% 0, 100% 42%, 0 44%);
        transform: translate(0);
    }
    10% {
        clip-path: polygon(0 3%, 100% 0, 100% 40%, 0 38%);
        transform: translate(-5px, 5px);
    }
    20% {
        clip-path: polygon(0 0, 100% 2%, 100% 45%, 0 42%);
        transform: translate(5px, -3px);
    }
    30% {
        clip-path: polygon(0 5%, 100% 0, 100% 42%, 0 40%);
        transform: translate(-3px, 3px);
    }
    40% {
        clip-path: polygon(0 0, 100% 3%, 100% 48%, 0 45%);
        transform: translate(3px, -5px);
    }
    50% {
        clip-path: polygon(0 2%, 100% 0, 100% 45%, 0 43%);
        transform: translate(0);
    }
    100% {
        clip-path: polygon(0 0, 100% 0, 100% 42%, 0 44%);
        transform: translate(0);
    }
}

@keyframes glitchBottom {
    0% {
        clip-path: polygon(0 53%, 100% 55%, 100% 100%, 0 100%);
        transform: translate(0);
    }
    15% {
        clip-path: polygon(0 55%, 100% 53%, 100% 100%, 0 100%);
        transform: translate(5px, -5px);
    }
    30% {
        clip-path: polygon(0 52%, 100% 56%, 100% 100%, 0 100%);
        transform: translate(-5px, 5px);
    }
    45% {
        clip-path: polygon(0 56%, 100% 54%, 100% 100%, 0 100%);
        transform: translate(3px, -3px);
    }
    60% {
        clip-path: polygon(0 54%, 100% 52%, 100% 100%, 0 100%);
        transform: translate(-3px, 5px);
    }
    75% {
        clip-path: polygon(0 53%, 100% 57%, 100% 100%, 0 100%);
        transform: translate(0);
    }
    100% {
        clip-path: polygon(0 53%, 100% 55%, 100% 100%, 0 100%);
        transform: translate(0);
    }
}

.splash-tagline {
    font-size: 1.4rem;
    color: #ff00ff;
    margin-bottom: 50px;
    font-weight: 600;
    letter-spacing: 6px;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
    text-transform: uppercase;
    animation: 
        taglineEntry 1.2s ease-out 0.6s forwards,
        chromaShift 4s infinite 1.8s,
        taglineExit 0.6s ease-in 2.9s forwards;
    text-shadow: 
        0 0 10px #ff00ff,
        0 0 20px #ff00ff,
        0 0 30px #ff00ff;
    opacity: 0;
    transform: translateX(-150px) rotateY(-90deg);
}

@keyframes taglineEntry {
    0% {
        opacity: 0;
        transform: translateX(-150px) rotateY(-90deg) scale(0.8);
        filter: blur(15px);
    }
    70% {
        opacity: 0.9;
        transform: translateX(15px) rotateY(0deg) scale(1.05);
        filter: blur(3px);
    }
    100% {
        opacity: 1;
        transform: translateX(0) rotateY(0deg) scale(1);
        filter: blur(0);
    }
}

@keyframes taglineExit {
    0% {
        opacity: 1;
        transform: translateX(0) scale(1);
    }
    100% {
        opacity: 0;
        transform: translateX(150px) scale(0.8);
    }
}

@keyframes chromaShift {
    0%, 100% {
        text-shadow: 
            2px 0 #00ffff,
            -2px 0 #ff00ff,
            0 0 20px #ff00ff;
    }
    25% {
        text-shadow: 
            -2px 0 #00ffff,
            2px 0 #ff00ff,
            0 0 25px #ff00ff;
    }
    50% {
        text-shadow: 
            0 2px #00ffff,
            0 -2px #ff00ff,
            0 0 30px #ff00ff;
    }
    75% {
        text-shadow: 
            2px 2px #00ffff,
            -2px -2px #ff00ff,
            0 0 25px #ff00ff;
    }
}

.splash-loader-wrapper {
    width: 100%;
    max-width: 500px;
    margin: 0 auto;
    animation: 
        loaderEntry 1s ease-out 1.2s forwards,
        loaderExit 0.5s ease-in 3s forwards;
    opacity: 0;
    transform: translateY(50px) scale(0.9);
}

@keyframes loaderEntry {
    0% {
        opacity: 0;
        transform: translateY(80px) scale(0.7);
        filter: blur(15px);
    }
    100% {
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: blur(0);
    }
}

@keyframes loaderExit {
    0% {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
    100% {
        opacity: 0;
        transform: translateY(-50px) scale(0.8);
    }
}

.splash-loader {
    width: 100%;
    height: 6px;
    background: rgba(0, 255, 255, 0.1);
    border: 2px solid #00ffff;
    border-radius: 3px;
    overflow: hidden;
    position: relative;
    margin-bottom: 20px;
    box-shadow: 
        0 0 15px rgba(0, 255, 255, 0.5),
        inset 0 0 10px rgba(0, 255, 255, 0.2);
}

.loader-progress {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, 
        #ff00ff 0%, 
        #00ffff 25%, 
        #00ff00 50%, 
        #ffff00 75%, 
        #ff00ff 100%);
    animation: 
        progressLoad 2.5s cubic-bezier(0.65, 0, 0.35, 1) forwards,
        colorWave 1.5s linear infinite;
    box-shadow: 
        0 0 30px #00ffff,
        0 0 60px #ff00ff;
    position: relative;
}

@keyframes colorWave {
    0% { filter: hue-rotate(0deg) brightness(1.2); }
    100% { filter: hue-rotate(360deg) brightness(1.2); }
}

.loader-progress::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(
        90deg,
        transparent,
        rgba(255, 255, 255, 0.6),
        transparent
    );
    animation: shimmer 1s infinite;
}

@keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(200%); }
}

@keyframes progressLoad {
    0% { width: 0%; }
    100% { width: 100%; }
}

.loader-text {
    text-align: center;
    color: #00ffff;
    font-size: 1rem;
    font-weight: 600;
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
    text-shadow: 
        0 0 8px #00ffff,
        0 0 15px #00ffff;
    letter-spacing: 3px;
}

.loading-dots span {
    animation: dotPulse 1.4s infinite;
    opacity: 0;
    font-size: 1.5em;
    color: #ff00ff;
    text-shadow: 0 0 10px #ff00ff;
}

.loading-dots span:nth-child(1) {
    animation-delay: 0s;
}

.loading-dots span:nth-child(2) {
    animation-delay: 0.2s;
}

.loading-dots span:nth-child(3) {
    animation-delay: 0.4s;
}

@keyframes dotPulse {
    0%, 80%, 100% {
        opacity: 0;
        transform: scale(1);
    }
    40% {
        opacity: 1;
        transform: scale(1.3);
    }
}

.glitch-noise {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: 
        repeating-linear-gradient(
            0deg,
            rgba(0, 255, 255, 0.03),
            rgba(0, 255, 255, 0.03) 1px,
            transparent 1px,
            transparent 2px
        );
    opacity: 0.6;
    pointer-events: none;
    animation: scanline 8s linear infinite;
}

@keyframes scanline {
    0% { transform: translateY(0); }
    100% { transform: translateY(100%); }
}

.glitch-noise::before {
    content: '';
    position: absolute;
    inset: 0;
    background: 
        repeating-linear-gradient(
            90deg,
            rgba(255, 0, 255, 0.02) 0px,
            transparent 1px,
            transparent 2px,
            rgba(0, 255, 255, 0.02) 3px
        );
    animation: staticNoise 0.1s infinite;
}

@keyframes staticNoise {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 0.7; }
}

@keyframes fadeOut {
    0% {
        opacity: 1;
        visibility: visible;
    }
    100% {
        opacity: 0;
        visibility: hidden;
    }
}

/* Responsive Cyberpunk Splash */
@media (max-width: 768px) {
    .splash-title {
        font-size: 3.5rem;
        letter-spacing: 6px;
    }
    
    .splash-tagline {
        font-size: 1.1rem;
        letter-spacing: 3px;
    }
    
    .splash-loader-wrapper {
        max-width: 350px;
    }
}

@media (max-width: 480px) {
    .splash-title {
        font-size: 2.2rem;
        letter-spacing: 4px;
    }
    
    .splash-tagline {
        font-size: 0.95rem;
        letter-spacing: 2px;
    }
    
    .splash-loader-wrapper {
        max-width: 280px;
    }
}

label {
    display: block;
    margin-top: 15px;
    margin-bottom: 8px;
    font-weight: 600;
    color: var(--text);
    font-size: 0.95em;
}

input[type="checkbox"], input[type="radio"] {
    width: auto;
    margin-right: 10px;
    cursor: pointer;
}

.modal {
    display: none;
    position: fixed;
    z-index: 10000;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    animation: fadeIn 0.3s ease;
}

.modal.report-modal {
    display: none; /* Hidden by default */
    align-items: center;
    justify-content: center;
    padding: 16px;
}

.modal-content {
    background: var(--card);
    margin: 10% auto;
    padding: 30px;
    border-radius: 16px;
    max-width: 600px;
    border: 2px solid var(--border);
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
    animation: fadeInUp 0.4s ease-out;
}

.modal-header {
    font-size: 1.5em;
    font-weight: 600;
    margin-bottom: 20px;
    color: var(--blue);
}

.deal-item {
    padding: 15px;
    margin: 10px 0;
    border: 2px solid var(--border);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.3s ease;
    background: var(--bg2);
}

.deal-item:hover {
    border-color: var(--blue);
    background: var(--card);
    transform: translateX(5px);
}

.deal-item.selected {
    border-color: var(--blue);
    background: linear-gradient(135deg, rgba(91, 124, 255, 0.2) 0%, rgba(123, 156, 255, 0.2) 100%);
    box-shadow: 0 4px 15px rgba(91, 124, 255, 0.3);
}

.modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 20px;
}

.btn-modal {
    padding: 12px 24px;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    font-weight: 600;
    transition: all 0.3s ease;
}

.btn-modal-primary {
    background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
    color: white;
}

.btn-modal-secondary {
    background: var(--bg2);
    color: var(--text);
    border: 2px solid var(--border);
}

.form-label {
    display: block;
    margin-bottom: 8px;
    font-weight: 600;
    color: var(--text);
    font-size: 0.95em;
}

.upload-card {
    position: relative;
    overflow: visible;
}

.upload-area {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 60px 40px;
    border: 3px dashed var(--border);
    border-radius: 16px;
    background: var(--bg2);
    cursor: pointer;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
}

.upload-area::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: linear-gradient(45deg, transparent, rgba(91, 124, 255, 0.1), transparent);
    transform: rotate(45deg);
    animation: shimmer 3s infinite;
}

.upload-area:hover {
    border-color: var(--blue);
    background: var(--card);
    transform: translateY(-5px);
    box-shadow: 0 10px 30px rgba(91, 124, 255, 0.2);
}

.upload-area.drag-over {
    border-color: var(--blue);
    background: var(--card);
    transform: scale(1.02);
    box-shadow: 0 10px 30px rgba(91, 124, 255, 0.3);
}

.upload-icon-animated {
    font-size: 4em;
    margin-bottom: 20px;
    animation: float 3s ease-in-out infinite;
}

@keyframes float {
    0%, 100% {
        transform: translateY(0px);
    }
    50% {
        transform: translateY(-20px);
    }
}

.upload-text {
    font-size: 1.3em;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 10px;
}

.upload-hint {
    font-size: 0.95em;
    color: var(--text);
    opacity: 0.6;
}

.file-name-display {
    margin-top: 15px;
    font-size: 0.9em;
    color: var(--blue);
    font-weight: 600;
}

.progress-container {
    background: var(--bg2);
    border-radius: 16px;
    padding: 30px;
    border: 2px solid var(--border);
}

.progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}

.progress-status {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 1.1em;
    font-weight: 600;
}

.status-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--text);
    opacity: 0.3;
    animation: pulse 2s infinite;
}

.status-dot.running {
    background: var(--blue);
    opacity: 1;
    animation: pulse 1s infinite;
}

.status-dot.success {
    background: var(--success);
    opacity: 1;
    animation: none;
}

.status-dot.error {
    background: var(--danger);
    opacity: 1;
    animation: pulse 0.5s infinite;
}

.progress-percentage {
    font-size: 2em;
    font-weight: 700;
    color: var(--blue);
}

.progress-bar-wrapper {
    width: 100%;
    height: 30px;
    background: rgba(0, 0, 0, 0.3);
    border-radius: 15px;
    overflow: hidden;
    position: relative;
    margin-bottom: 25px;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.3);
}

.progress-bar-fill {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, var(--blue) 0%, var(--blue-hover) 100%);
    border-radius: 15px;
    transition: width 0.5s ease;
    position: relative;
    overflow: hidden;
}

.progress-bar-fill::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    right: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
    animation: shimmerBar 2s infinite;
}

@keyframes shimmerBar {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
}

.progress-bar-shimmer {
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(91, 124, 255, 0.4), transparent);
    animation: shimmerBar 3s infinite;
}

.progress-stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 15px;
    margin-bottom: 20px;
}

.progress-stat-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 15px;
    background: var(--card);
    border-radius: 10px;
    border: 1px solid var(--border);
    font-size: 0.95em;
}

.stat-emoji {
    font-size: 1.2em;
}

.stat-label {
    opacity: 0.7;
}

.stat-number {
    font-weight: 700;
    color: var(--blue);
    margin-left: auto;
}

.current-action {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 15px 20px;
    background: var(--card);
    border-radius: 12px;
    border: 2px solid var(--border);
    font-weight: 500;
}

.action-spinner {
    width: 20px;
    height: 20px;
    border: 3px solid var(--border);
    border-top-color: var(--blue);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.action-spinner.hidden {
    display: none;
}

/* ==================== BOTTOM NAVIGATION BAR (MOBILE) ==================== */
.bottom-nav {
    display: none;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: var(--card);
    border-top: 2px solid var(--border);
    z-index: 1000;
    box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.3);
    backdrop-filter: blur(10px);
    height: 70px;
    padding: 8px 0;
    padding-bottom: calc(8px + env(safe-area-inset-bottom));
    flex-direction: row;
    justify-content: space-around;
    align-items: center;
}

.bottom-nav-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 8px 4px;
    cursor: pointer;
    transition: all 0.3s ease;
    border-radius: 12px;
    margin: 0 4px;
    position: relative;
    color: var(--text-muted);
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
}

.bottom-nav-item::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--blue) 0%, var(--blue-hover) 100%);
    border-radius: 0 0 12px 12px;
    transform: scaleX(0);
    transition: transform 0.3s ease;
}

.bottom-nav-item.active::before {
    transform: scaleX(1);
}

.bottom-nav-item:hover {
    background: var(--card-hover);
    color: var(--text);
}

.bottom-nav-item:active {
    transform: scale(0.95);
    background: var(--card-hover);
}

.bottom-nav-item.active {
    color: var(--blue);
    background: rgba(91, 124, 255, 0.1);
}

.bottom-nav-icon {
    font-size: 1.5em;
    transition: transform 0.3s ease;
}

.bottom-nav-item.active .bottom-nav-icon {
    transform: scale(1.2);
}

.bottom-nav-label {
    font-size: 0.7em;
    font-weight: 600;
    text-align: center;
    white-space: nowrap;
    line-height: 1.2;
    max-width: 100%;
        overflow: hidden;
    text-overflow: ellipsis;
}

@media (max-width: 768px) {
    .sidebar {
        width: 240px;
        padding: 22px 16px;
        transform: translateX(-100%);
        transition: transform 0.25s ease;
        display: block;
    }
    body.sidebar-open .sidebar {
        transform: translateX(0);
    }
    .nav-toggle {
        display: block;
    }
    .main {
        margin-left: 0;
        width: 100%;
        padding-bottom: 90px; /* Space for bottom nav */
    }
    
    .toggle-btn {
        top: 10px;
        right: 10px;
    }
    
    .dashboard-row {
        grid-template-columns: 1fr;
    }
    
    .bottom-nav {
        display: flex;
    }
}

@media (min-width: 769px) {
    .bottom-nav {
        display: none !important;
    }
}

@media (max-width: 480px) {
    .bottom-nav {
        height: 65px;
        padding: 6px 0;
    }
    
    .bottom-nav-icon {
        font-size: 1.3em;
    }
    
    .bottom-nav-label {
        font-size: 0.65em;
    }
    
    .main {
        padding-bottom: 85px;
    }
}
</style>
</head>

<body>
<!-- Splash Screen with Glitch Effect -->
<div id="splash-screen" class="splash-screen">
    <div class="splash-background"></div>
    <div class="glitch-noise"></div>
    <div class="splash-content">
        <h1 class="splash-title" data-text="FLIPKARTSNIPER 2.0">FLIPKARTSNIPER 2.0</h1>
        <p class="splash-tagline">⚡ QUANTUM DEAL HUNTER ⚡</p>
        <div class="splash-loader-wrapper">
            <div class="splash-loader">
                <div class="loader-progress"></div>
            </div>
            <div class="loader-text">
                <span class="loading-dots">
                    <span>.</span><span>.</span><span>.</span>
                </span>
            </div>
        </div>
    </div>

</div>

<div class="sidebar">
    <div class="sidebar-header">
        <h2>🎯 FlipkartSniper 2.0</h2>
        <div class="sidebar-subtitle">Automated Deal Hunter</div>
    </div>
    <div class="menu-item active" onclick="openPage('dashboard',this)">
        <span class="menu-icon">📊</span>
        <span>Dashboard</span>
    </div>
    <div class="menu-item" onclick="openPage('accounts',this)">
        <span class="menu-icon">👥</span>
        <span>Accounts</span>
    </div>
    <div class="menu-item" onclick="openPage('runorder',this)">
        <span class="menu-icon">🚀</span>
        <span>Run Order</span>
    </div>
    <div class="menu-item" onclick="openPage('reports',this)">
        <span class="menu-icon">📁</span>
        <span>Reports</span>
    </div>
    <div class="menu-item" onclick="openPage('logs',this)">
        <span class="menu-icon">🧾</span>
        <span>Logs</span>
    </div>
    <div class="menu-item" onclick="openPage('imap',this)">
        <span class="menu-icon">📧</span>
        <span>IMAP</span>
    </div>
</div>

<!-- Bottom Navigation Bar for Mobile -->
<div class="bottom-nav">
    <div class="bottom-nav-item active" onclick="openPage('dashboard',this)">
        <span class="bottom-nav-icon">📊</span>
        <span class="bottom-nav-label">Dashboard</span>
    </div>
    <div class="bottom-nav-item" onclick="openPage('accounts',this)">
        <span class="bottom-nav-icon">👥</span>
        <span class="bottom-nav-label">Accounts</span>
    </div>
    <div class="bottom-nav-item" onclick="openPage('runorder',this)">
        <span class="bottom-nav-icon">🚀</span>
        <span class="bottom-nav-label">Run Order</span>
    </div>
    <div class="bottom-nav-item" onclick="openPage('reports',this)">
        <span class="bottom-nav-icon">📁</span>
        <span class="bottom-nav-label">Reports</span>
    </div>
    <div class="bottom-nav-item" onclick="openPage('logs',this)">
        <span class="bottom-nav-icon">🧾</span>
        <span class="bottom-nav-label">Logs</span>
    </div>
    <div class="bottom-nav-item" onclick="openPage('imap',this)">
        <span class="bottom-nav-icon">📧</span>
        <span class="bottom-nav-label">IMAP</span>
    </div>
</div>

<div class="main">

    <!-- ================= Dashboard ================= -->
    <div id="dashboard" class="page">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 30px;">
            <h1 class="page-title" style="margin: 0;">📊 Dashboard</h1>
            <div class="top-icons">
                <button class="icon-btn" onclick="toggleTheme()" title="Toggle theme">🌓</button>
                <button class="icon-btn danger" onclick="window.location.href='/logout'" title="Logout">⎋</button>
            </div>
        </div>
        <div id="dashAlert" class="warning-box" style="display:none; margin-bottom:16px;"></div>

        <div class="dashboard-row glass-grid">
            <div class="big-stat-card glass-float">
                <h3 style="color: var(--success); margin-bottom: 20px;">✅ Success Rate</h3>
                <div class="progress-ring-container">
                    <svg class="progress-ring" width="180" height="180">
                        <circle class="progress-ring-circle" 
                                stroke="rgba(255,255,255,0.08)" 
                                stroke-width="12" 
                                fill="transparent" 
                                r="70" 
                                cx="90" 
                                cy="90"/>
                        <circle id="success-circle" 
                                class="progress-ring-circle" 
                                stroke="var(--success)" 
                                stroke-width="12" 
                                fill="transparent" 
                                r="70" 
                                cx="90" 
                                cy="90"
                                stroke-dasharray="439.6"
                                stroke-dashoffset="439.6"
                                stroke-linecap="round"/>
                    </svg>
                    <div class="progress-text" id="success-percent-text">0%</div>
                </div>
                <div class="percentage-bar glass-bar">
                    <div class="percentage-fill" id="success-bar" style="width: 0%"></div>
                </div>
                <div class="percentage-text">
                    <span>Success: <strong id="success-count">0</strong></span>
                    <span>Total: <strong id="total-count">0</strong></span>
                </div>
            </div>

            <div class="big-stat-card glass-float">
                <h3 style="color: var(--danger); margin-bottom: 20px;">❌ Failure Rate</h3>
                <div class="progress-ring-container">
                    <svg class="progress-ring" width="180" height="180">
                        <circle class="progress-ring-circle" 
                                stroke="rgba(255,255,255,0.08)" 
                                stroke-width="12" 
                                fill="transparent" 
                                r="70" 
                                cx="90" 
                                cy="90"/>
                        <circle id="failure-circle" 
                                class="progress-ring-circle" 
                                stroke="var(--danger)" 
                                stroke-width="12" 
                                fill="transparent" 
                                r="70" 
                                cx="90" 
                                cy="90"
                                stroke-dasharray="439.6"
                                stroke-dashoffset="439.6"
                                stroke-linecap="round"/>
                    </svg>
                    <div class="progress-text" id="failure-percent-text" style="color: var(--danger)">0%</div>
                </div>
                <div class="percentage-bar glass-bar">
                    <div class="percentage-fill" id="failure-bar" style="width: 0%; background: linear-gradient(90deg, var(--danger) 0%, #ff7a6d 100%)"></div>
                </div>
                <div class="percentage-text">
                    <span>Failed: <strong id="failure-count">0</strong></span>
                    <span>Total: <strong id="total-count-2">0</strong></span>
                </div>
            </div>
        </div>

        <div class="stats-grid glass-grid">
            <div class="stat-card glass-float">
                <div class="stat-icon">📦</div>
                <div class="stat-label">Total Orders</div>
                <div class="stat-value" id="total">0</div>
            </div>
            <div class="stat-card glass-float">
                <div class="stat-icon">✅</div>
                <div class="stat-label">Success</div>
                <div class="stat-value" id="success" style="color: var(--success)">0</div>
            </div>
            <div class="stat-card glass-float">
                <div class="stat-icon">❌</div>
                <div class="stat-label">Failure</div>
                <div class="stat-value" id="failure" style="color: var(--danger)">0</div>
            </div>
            <div class="stat-card glass-float">
                <div class="stat-icon">📧</div>
                <div class="stat-label">Mails Left</div>
                <div class="stat-value" id="mails_left">0</div>
            </div>
            <div class="stat-card glass-float">
                <div class="stat-icon">🏷️</div>
                <div class="stat-label">Coupons Left</div>
                <div class="stat-value" id="coupons_left">0</div>
            </div>
        </div>
    </div>

    <!-- ================= Accounts ================= -->
    <div id="accounts" class="page hidden">
        <h1 class="page-title">👥 Accounts Management</h1>
        
        <div class="card upload-card">
            <h3>📧 Mail Accounts</h3>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;">
                <div>
                    <h4 style="margin-bottom: 15px; color: var(--blue);">📤 Upload Mail File</h4>
                    <form action="/upload-mail" method="POST" enctype="multipart/form-data" id="mail-upload-form">
                        <label for="mail-file" class="upload-area" style="padding: 40px 20px; cursor: pointer;">
                            <div class="upload-icon-animated">📤</div>
                            <div class="upload-text">Click or Drag to Upload</div>
                            <div class="upload-hint">Mail accounts (.txt)</div>
                            <input type="file" name="file" id="mail-file" accept=".txt" style="display: none;" onchange="updateFileName(this, 'mail-name')" required>
                            <div class="file-name-display" id="mail-name"></div>
                        </label>
                        <button type="submit">📤 Upload Mail Accounts</button>
                    </form>
                </div>
                <div>
                    <h4 style="margin-bottom: 15px; color: var(--blue);">✏️ Edit Mail File</h4>
                    <button onclick="openEditor('mail')" style="margin-bottom: 10px; width: 100%;">📝 Open Mail Editor</button>
                    <div id="mail-editor-status" style="font-size: 0.9em; color: var(--text-muted);"></div>
                </div>
            </div>
        </div>

        <div class="card upload-card">
            <h3>🏷️ Coupon Codes</h3>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;">
                <div>
                    <h4 style="margin-bottom: 15px; color: var(--blue);">📤 Upload Coupon File</h4>
                    <form action="/upload-coupon" method="POST" enctype="multipart/form-data" id="coupon-upload-form">
                        <label for="coupon-file" class="upload-area" style="padding: 40px 20px; cursor: pointer;">
                            <div class="upload-icon-animated">🔖</div>
                            <div class="upload-text">Click or Drag to Upload</div>
                            <div class="upload-hint">Coupon codes (.txt)</div>
                            <input type="file" name="file" id="coupon-file" accept=".txt" style="display: none;" onchange="updateFileName(this, 'coupon-name')" required>
                            <div class="file-name-display" id="coupon-name"></div>
                        </label>
                        <button type="submit">🔖 Upload Coupons</button>
                    </form>
                </div>
                <div>
                    <h4 style="margin-bottom: 15px; color: var(--blue);">✏️ Edit Coupon File</h4>
                    <button onclick="openEditor('coupon')" style="margin-bottom: 10px; width: 100%;">📝 Open Coupon Editor</button>
                    <div id="coupon-editor-status" style="font-size: 0.9em; color: var(--text-muted);"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- ================= Run Order ================= -->
    <div id="runorder" class="page hidden">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <h1 class="page-title">🚀 Run Automation</h1>
            <button type="button" class="btn-ghost" style="width:auto; padding:10px 16px;" onclick="startGuidedTour()">
                ✨ Guided tour
            </button>
        </div>
        
        

        <div class="card">
            
            
            <div class="progress-container">
                <div class="progress-header">
                    <div class="progress-stat">
                        <span class="status-dot" id="statusDot"></span>
                        
                    </div>
                    
                </div>
                
                
                    
            </div>
            
 
                
            <details id="logsDetails" style="margin-top: 20px;">
                <summary style="cursor: pointer; padding: 10px; background: var(--bg2); border-radius: 8px; font-weight: 600;">
                    📝 View Detailed Logs
                </summary>
                <pre id="runlog" style="margin-top: 15px;"></pre>
            </details>
        </div>

        <div class="card">
            <form method="POST" action="/start" id="orderForm" onsubmit="return handleSubmit(event)">

                <h3>👤 Customer Details</h3>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                    <div>
                        <label class="form-label">First Name *</label>
                        <input type="text" name="first_name" placeholder="Enter first name" required>
                    </div>
                    <div>
                        <label class="form-label">Surname *</label>
                        <input type="text" name="surname" placeholder="Enter surname" required>
                    </div>
                </div>
                
                <label class="form-label">Phone Number *</label>
                <input type="text" name="phone" placeholder="Enter your phone number" required>
                
                <label class="form-label">Pincode *</label>
                <input type="text" name="pincode" placeholder="Enter pincode" required>
                
                <label class="form-label">Address Line 1 *</label>
                <input type="text" name="address1" placeholder="Street address, building number" required>
                
                <label class="form-label">Address Line 2</label>
                <input type="text" name="address2" placeholder="Apartment, suite, floor (optional)">

                <h3 style="margin-top: 30px;">⚙️ Order Settings</h3>
                
                <label class="form-label">Order Limit *</label>
                <input type="number" name="limit" value="4" placeholder="Number of orders" required>
                
                <label class="form-label">Max Price (₹) *</label>
                <input type="number" name="max_price" value="1300" placeholder="Maximum price limit">
                
                <label class="form-label">Parallel Orders *</label>
                <input type="number" name="parallel" value="2" min="1" max="4" placeholder="Concurrent orders (recommended: 2 for RDP)">
                
                <label class="form-label">Deal Keyword</label>
                <input type="text" name="deal_keyword" placeholder="Search keyword (optional)">
                <small style="color: var(--text); opacity: 0.7; font-size: 0.85em; display: block; margin-top: 5px;">If matching product not found, you'll be prompted to select from available deals</small>

                <label class="form-label" style="margin-top: 15px;">Screenshot Domain</label>
                <input type="text" name="screenshot_domain" value="{{ screenshot_domain }}" placeholder="e.g. husan.shop (Public IP/Domain for screenshots)">
                <small style="color: var(--text); opacity: 0.7; font-size: 0.85em; display: block; margin-top: 5px;">Leave empty to auto-detect. Used to generate clickable screenshot links.</small>

                <div style="margin-top: 20px; padding: 15px; background: var(--card); border-radius: 10px; border: 2px solid var(--border);">
                    <label class="form-label" style="margin-bottom: 10px;">Use Coupon? *</label>
                    <div style="display: flex; gap: 20px;">
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                            <input type="radio" name="use_coupon" value="true" required>
                            <span>Yes, use coupon</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                            <input type="radio" name="use_coupon" value="false" required>
                            <span>No, don't use coupon</span>
                        </label>
                    </div>
                </div>

                <h3 style="margin-top: 30px;">🛍️ Products</h3>
                <div id="product-list">
                    <div class="product-row">
                        <div style="flex: 1;">
                            <label class="form-label">Product URL *</label>
                            <input type="text" name="product_url[]" placeholder="Enter product URL" required>
                        </div>
                        <div style="width: 120px;">
                            <label class="form-label">Quantity *</label>
                            <input type="number" name="product_qty[]" value="1" placeholder="Qty" required>
                        </div>
                    </div>
                </div>

                <button type="button" class="add-btn" onclick="addProduct()">➕ Add Product</button>

                <div style="margin-top: 20px; display: flex; flex-direction: column; gap: 10px;">
                    <label class="toggle-switch">
                        <input type="checkbox" name="retry" id="retryToggle">
                        <span class="toggle-labels">
                            <span class="off"></span>
                            <span class="on">Retry Failed Accounts</span>
                        </span>
                        <span class="toggle-track">
                            <span class="toggle-thumb">
                                <img class="icon-off" src="/images/eye-close.svg" alt="off">
                                <img class="icon-on" src="/images/eye-open.svg" alt="on">
                            </span>
                            <span class="toggle-ripple"></span>
                        </span>
                </label>
                    <label class="toggle-switch">
                        <input type="checkbox" name="auto_apply_deals" id="autoApplyDealsToggle" checked>
                        <span class="toggle-labels">
                            <span class="off"></span>
                            <span class="on">Auto Apply Cart Deals</span>
                        </span>
                        <span class="toggle-track">
                            <span class="toggle-thumb">
                                <img class="icon-off" src="/images/eye-close.svg" alt="off">
                                <img class="icon-on" src="/images/eye-open.svg" alt="on">
                            </span>
                            <span class="toggle-ripple"></span>
                        </span>
                </label>
                    <label class="toggle-switch">
                        <input type="checkbox" name="allow_less_qty" id="allowLessQtyToggle" checked>
                        <span class="toggle-labels">
                            <span class="off"></span>
                            <span class="on">Allow Less Quantity</span>
                        </span>
                        <span class="toggle-track">
                            <span class="toggle-thumb">
                                <img class="icon-off" src="/images/eye-close.svg" alt="off">
                                <img class="icon-on" src="/images/eye-open.svg" alt="on">
                            </span>
                            <span class="toggle-ripple"></span>
                        </span>
                </label>
                    <label class="toggle-switch">
                        <input type="checkbox" name="remove_mail_on_success" id="removeMailOnSuccessToggle" checked>
                        <span class="toggle-labels">
                            <span class="off"></span>
                            <span class="on">Remove Mail on Success</span>
                        </span>
                        <span class="toggle-track">
                            <span class="toggle-thumb">
                                <img class="icon-off" src="/images/eye-close.svg" alt="off">
                                <img class="icon-on" src="/images/eye-open.svg" alt="on">
                            </span>
                            <span class="toggle-ripple"></span>
                        </span>
                </label>
                </div>

                <button style="margin-top: 25px;" id="startBtn" type="submit">🎯 Start Sniper</button>
                <button style="margin-top: 10px; background: var(--danger); border-color: var(--danger); display:none;" id="stopBtn" type="button" onclick="stopAllWorkers()">🛑 Stop All Workers</button>

            </form>
        </div>

    </div>

    <!-- ================= Reports ================= -->
    <div id="reports" class="page hidden">
        <div class="reports-header">
            <div class="reports-header-content">
                <div>
            <h1 class="page-title">📁 Reports</h1>
                    <p class="reports-subtitle">View and download your order reports</p>
                </div>
                <button class="btn-refresh" onclick="loadReports()" title="Refresh Reports">
                    <span class="refresh-icon">🔄</span>
                    <span class="refresh-text">Refresh</span>
            </button>
            </div>
        </div>

        <div class="reports-container">
            <div class="reports-stats-bar" id="reports-stats-bar" style="display: none;">
                <div class="stat-item">
                    <span class="stat-label">Total Reports</span>
                    <span class="stat-value" id="total-reports">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Total Records</span>
                    <span class="stat-value" id="total-records">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Last Updated</span>
                    <span class="stat-value" id="last-updated">Never</span>
                </div>
            </div>

            <div class="reports-content-card">
                <div class="reports-content-header">
                    <h2 class="reports-content-title">
                        <span class="title-icon">📊</span>
                        <span>Available Reports</span>
                    </h2>
                    <div id="reports-loading" class="reports-loading">
                        <div class="loading-spinner"></div>
                        <span>Loading reports...</span>
                </div>
            </div>

            <div id="report-list" class="reports-grid">
                <!-- Loaded dynamically -->
                </div>
            </div>
        </div>

        <!-- Report Viewer Modal -->
        <div id="reportModal" class="modal report-modal" onclick="if(event.target===this) closeReportModal()" style="display: none; background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(4px);">
            <div class="modal-content report-modal-content">
                <!-- Close Button - Top Right -->
                <button onclick="closeReportModal()" style="position: absolute; top: 8px; right: 8px; z-index: 100; background: rgba(0, 0, 0, 0.3); border: none; padding: 6px; border-radius: 6px; cursor: pointer; transition: all 0.2s; backdrop-filter: blur(4px); width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 0, 0, 0.5)'; this.style.transform='rotate(90deg)'" onmouseout="this.style.background='rgba(0, 0, 0, 0.3)'; this.style.transform='rotate(0deg)'" ontouchstart="this.style.background='rgba(0, 0, 0, 0.5)'" ontouchend="this.style.background='rgba(0, 0, 0, 0.3)'">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
                
                <!-- Header with Gradient -->
                <div class="report-modal-header-gradient" style="background: linear-gradient(135deg, #9333ea 0%, #ec4899 100%); padding: 24px; padding-top: 24px; padding-right: 24px; position: relative; overflow: hidden;">
                    <div style="position: absolute; inset: 0; background: rgba(255, 255, 255, 0.1); animation: pulse 2s infinite;"></div>
                    <div style="position: relative; display: flex; align-items: center; gap: 12px;">
                        <div style="background: rgba(255, 255, 255, 0.2); padding: 12px; border-radius: 12px; backdrop-filter: blur(4px); flex-shrink: 0;">
                            <span style="font-size: 24px;">📄</span>
                        </div>
                        <div style="min-width: 0; flex: 1;">
                            <h2 id="reportModalTitle" style="font-size: 24px; font-weight: 700; color: white; margin: 0; word-wrap: break-word;">Report Viewer</h2>
                            <p id="reportModalSubtitle" style="color: rgba(255, 255, 255, 0.8); font-size: 14px; margin: 4px 0 0; word-wrap: break-word; overflow: hidden; text-overflow: ellipsis;">Loading...</p>
                        </div>
                    </div>
                </div>
                
                <!-- Table Container -->
                <div id="reportModalBody" class="report-table-container">
                    <div class="report-loading-state" style="text-align: center; padding: 60px; color: rgba(148, 163, 184, 1);">
                        <div style="animation: spin 1s linear infinite; display: inline-block; font-size: 48px; margin-bottom: 16px;">⏳</div>
                        <p style="font-size: 16px;">Loading report data...</p>
                    </div>
                </div>
                
                <!-- Footer -->
                <div class="report-modal-footer">
                    <p id="reportModalStats" style="color: rgba(148, 163, 184, 1); font-size: 14px; margin: 0;">Loading...</p>
                    <div style="display: flex; gap: 12px; flex-wrap: wrap;">
                        <a id="downloadReportBtn" href="#" download style="padding: 10px 24px; background: linear-gradient(135deg, #9333ea 0%, #ec4899 100%); color: white; border: none; border-radius: 12px; font-weight: 600; text-decoration: none; cursor: pointer; transition: all 0.3s; box-shadow: 0 4px 14px rgba(147, 51, 234, 0.4); white-space: nowrap;" onmouseover="this.style.transform='scale(1.05)'; this.style.boxShadow='0 6px 20px rgba(147, 51, 234, 0.6)'" onmouseout="this.style.transform='scale(1)'; this.style.boxShadow='0 4px 14px rgba(147, 51, 234, 0.4)'" ontouchstart="this.style.transform='scale(0.95)'" ontouchend="this.style.transform='scale(1)'">
                            📥 Download File
                        </a>
                        <button onclick="closeReportModal()" style="padding: 10px 24px; background: rgba(148, 163, 184, 0.2); color: rgba(226, 232, 240, 1); border: 1px solid rgba(148, 163, 184, 0.3); border-radius: 12px; font-weight: 600; cursor: pointer; transition: all 0.3s; white-space: nowrap;" onmouseover="this.style.background='rgba(148, 163, 184, 0.3)'" onmouseout="this.style.background='rgba(148, 163, 184, 0.2)'" ontouchstart="this.style.background='rgba(148, 163, 184, 0.3)'" ontouchend="this.style.background='rgba(148, 163, 184, 0.2)'">
                            Close
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- ================= Logs ================= -->
    <div id="logs" class="page hidden">
        <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 25px;">
            <div>
                <h1 class="page-title" style="margin-bottom: 5px;">🧾 System Logs</h1>
                <p style="color: var(--text-muted);">Monitor real-time system activities and historical logs</p>
            </div>
            <button type="button" onclick="refreshLogs()" class="logs-desktop-refresh" style="width:auto; padding:10px 18px; display: flex; align-items: center; gap: 8px;">
                <span>🔄</span> Refresh
            </button>
        </div>

        <div class="logs-shell">
            <!-- Sidebar: Log Files -->
            <div class="logs-panel">
                <div class="logs-panel-header">
                    <span style="font-weight: 700; color: var(--blue); font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px;">Log Files</span>
                    <span id="logs-count" style="font-size: 0.8em; background: var(--highlight); padding: 2px 8px; border-radius: 10px; color: var(--blue);">0</span>
                </div>
                
                <div class="logs-mobile-actions" style="display: none;">
                    <select id="logsMobileSelect" style="padding:10px; border-radius:12px; border:1px solid var(--border); background: var(--bg2); color: var(--text); font-size: 0.95em;">
                    </select>
                </div>

                <div class="logs-list-container" id="logs-list">
                    <!-- Loaded dynamically -->
                </div>
            </div>

            <!-- Main: Content Viewer -->
            <div class="logs-viewer-container">
                <div class="logs-viewer-header">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <div style="width: 10px; height: 10px; border-radius: 50%; background: #ff5f56;"></div>
                        <div style="width: 10px; height: 10px; border-radius: 50%; background: #ffbd2e;"></div>
                        <div style="width: 10px; height: 10px; border-radius: 50%; background: #27c93f;"></div>
                        <span id="logs-selected-name" style="margin-left: 8px; font-family: monospace; font-size: 0.9em; color: #8b949e;">latest.log</span>
                    </div>

                    <div class="logs-viewer-controls">
                        <div class="logs-search-box">
                            <span style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); font-size: 14px; pointer-events: none;">🔍</span>
                            <input type="text" id="logSearch" placeholder="Filter logs..." onkeyup="applyLogsFilter()" style="padding-left: 36px; border-radius: 8px; height: 34px;">
                        </div>
                        
                        <div style="display: flex; align-items: center; gap: 8px; background: #161b22; padding: 4px 10px; border-radius: 8px; border: 1px solid var(--border);">
                            <span style="font-size: 0.85em; color: var(--text-muted); font-weight: 600;">Follow</span>
                            <label class="toggle-track" style="width: 44px; height: 22px; padding: 2px; cursor: pointer;">
                                <input type="checkbox" id="followLogs" checked style="display: none;">
                                <span class="toggle-thumb" style="width: 16px; height: 16px; transition: transform 0.2s;"></span>
                            </label>
                        </div>

                        <button onclick="copyLogs()" title="Copy to clipboard" style="width: auto; padding: 8px; margin: 0; background: transparent; border: 1px solid var(--border); box-shadow: none;">📋</button>
                        <a id="logs-download" href="#" class="btn-icon" title="Download Log" style="padding: 6px; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 8px; text-decoration: none; color: var(--text); display: flex; align-items: center; justify-content: center;">📥</a>
                    </div>
                </div>
                
                <pre id="logsViewer" class="logs-viewer"></pre>
                
                <div id="logsStatus" style="padding: 6px 20px; background: #161b22; border-top: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; font-size: 0.8em; color: #8b949e;">
                    <div id="logStatsInfo">Line count: 0</div>
                    <div id="logLastUpdate">Last updated: Never</div>
                </div>
            </div>
        </div>
    </div>


    <!-- ================= IMAP Configuration ================= -->
    <div id="imap" class="page hidden">
        <h1 class="page-title">📧 IMAP Configuration</h1>
        
        <div class="card">
            <h3>IMAP Settings</h3>
            <p style="color: var(--text-muted); margin-bottom: 25px;">
                Configure your IMAP server settings for OTP email retrieval
            </p>
            
            <form id="imapForm" onsubmit="saveImapConfig(event)">
                <label>
                    IMAP Host *
                    <input type="text" id="imap_host" name="host" placeholder="imappro.zoho.in" required>
                </label>
                
                <label>
                    Port *
                    <input type="number" id="imap_port" name="port" placeholder="993" required>
                </label>
                
                <label>
                    Email *
                    <input type="email" id="imap_email" name="email" placeholder="work@clyro.sbs" required>
                </label>
                
                <label>
                    Password *
                    <input type="password" id="imap_password" name="password" placeholder="Enter IMAP password" required>
                </label>
                
                <label>
                    Mailbox *
                    <input type="text" id="imap_mailbox" name="mailbox" placeholder="Notification" required>
                </label>
                
                <div id="imap-status" style="margin-top: 15px; padding: 12px; border-radius: 8px; display: none;"></div>
                
                <button type="submit" style="margin-top: 25px;">💾 Save IMAP Configuration</button>
            </form>
                </div>
            </div>


    </div>

    <!-- IMAP Configuration Confirmation Modal -->
    <div id="imapConfirmModal" class="modal" onclick="if(event.target===this) closeImapConfirmModal()">
        <div class="modal-content">
            <div class="modal-header">⚠️ Confirm IMAP Configuration Changes</div>
            <div id="imapConfirmBody" style="margin-bottom: 20px;">
                <p style="margin-bottom: 20px; color: var(--text);">
                    Please review your changes before saving:
                </p>
                <div id="imapChangesList" style="background: var(--bg); padding: 15px; border-radius: 8px; border: 2px solid var(--border);">
                    <!-- Changes will be displayed here -->
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-modal btn-modal-secondary" onclick="closeImapConfirmModal()">Cancel</button>
                <button class="btn-modal btn-modal-primary" onclick="confirmImapSave()">✅ Confirm & Save</button>
            </div>
        </div>
    </div>

    <!-- Deal Selection Modal -->
    <div id="dealModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">🎯 Select Product for Deal</div>
            <div id="dealModalBody">
                <p style="margin-bottom: 15px; color: var(--text);">No exact match found for your deal keyword. Please select a product:</p>
                <div id="dealList"></div>
            </div>
            <div class="modal-footer">
                <button class="btn-modal btn-modal-secondary" onclick="closeDealModal()">Cancel</button>
                <button class="btn-modal btn-modal-primary" onclick="confirmDealSelection()">Confirm Selection</button>
            </div>
        </div>
    </div>

    <!-- Stop Workers Confirmation Modal -->
    <div id="stopWorkersModal" class="modal" onclick="if(event.target===this) closeStopWorkersModal()" style="display: none;">
        <div class="modal-content">
            <div class="modal-header" style="color: var(--danger);">🛑 Stop All Workers</div>
            <div style="margin-bottom: 20px;">
                <p style="color: var(--text); margin-bottom: 10px; line-height: 1.6;">
                    Are you sure you want to stop all running workers immediately?
                </p>
                <p style="color: var(--text-muted); font-size: 0.9em; line-height: 1.5;">
                    This action will terminate all active worker processes. Any orders currently in progress will be cancelled.
                </p>
            </div>
            <div class="modal-footer">
                <button class="btn-modal btn-modal-secondary" onclick="closeStopWorkersModal()">Cancel</button>
                <button class="btn-modal" onclick="confirmStopWorkers()" style="background: linear-gradient(135deg, var(--danger) 0%, #ff5252 100%); color: white; border: none;">🛑 Stop All Workers</button>
            </div>
        </div>
    </div>

    <!-- File Editor Modal -->
    <div id="fileEditorModal" class="modal">
        <div class="modal-content" style="max-width: 900px; max-height: 90vh; overflow-y: auto;">
            <div class="modal-header" id="fileEditorTitle">📝 Edit File</div>
            <div style="margin-bottom: 15px;">
                <textarea id="fileEditorContent" style="width: 100%; min-height: 400px; padding: 15px; border: 2px solid var(--border); border-radius: 10px; background: var(--bg2); color: var(--text); font-family: 'Courier New', monospace; font-size: 14px; line-height: 1.6; resize: vertical;" placeholder="File content will appear here..."></textarea>
            </div>
            <div id="fileEditorStatus" style="margin-bottom: 15px; font-size: 0.9em; color: var(--text-muted);"></div>
            <div class="modal-footer">
                <button class="btn-modal btn-modal-secondary" onclick="closeFileEditor()">Cancel</button>
                <button class="btn-modal btn-modal-primary" onclick="saveFileEditor()">💾 Save File</button>
            </div>
        </div>
    </div>

</div>

<!-- Onboarding Tour Modal -->
<div id="tourOverlay" class="tour-overlay">
    <div class="tour-modal">
        <div class="tour-title">🧭 Welcome</div>
        <div class="tour-body" id="tourBody">Want a quick guided tour of the UI?</div>
        <div class="tour-actions">
            <button class="btn-ghost" id="tourSkipBtn">Not now</button>
            <button id="tourNextBtn">Start tour</button>
        </div>
    </div>
</div>
<!-- Toast container -->
<div class="toast-container" id="toastContainer"></div>

<script>
// ==================== SPLASH SCREEN ====================
(function() {
    const splashScreen = document.getElementById('splash-screen');
    
    // Hide splash screen after animation completes
    setTimeout(() => {
        if (splashScreen) {
            splashScreen.style.display = 'none';
            document.body.style.overflow = 'auto';
        }
    }, 3000);
    
    // Random glitch effect on title
    const title = document.querySelector('.splash-title');
    if (title) {
        setInterval(() => {
            if (Math.random() > 0.7) {
                title.style.animation = 'none';
                setTimeout(() => {
                    title.style.animation = 'glitch 2s infinite';
                }, 10);
            }
        }, 2000);
    }
})();

// THEME TOGGLE
function toggleTheme(){
    document.body.classList.toggle("light");
    localStorage.setItem("theme", document.body.classList.contains("light") ? "light" : "dark");
}

// Helper: Set alert box text/visibility
function setAlertBox(elId, msg, type='warning') {
    const el = document.getElementById(elId);
    if (!el) return;
    if (!msg) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }
    const color = type === 'error' ? 'var(--danger)' : 'var(--warning)';
    el.style.display = 'block';
    el.style.borderColor = color;
    el.style.color = color;
    el.innerHTML = msg;
}

// Toast notifications with basic dedupe (avoid spam of identical messages)
let lastToastKey = '';
let lastToastTime = 0;
function showToast(type, message, duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const key = `${type}:${message}`;
    const now = Date.now();
    // Skip if same toast fired within the last 4 seconds
    if (key === lastToastKey && now - lastToastTime < 4000) return;
    lastToastKey = key;
    lastToastTime = now;
    const div = document.createElement('div');
    div.className = `toast ${type === 'success' ? 'toast-success' : 'toast-error'}`;
    div.innerHTML = `<span class="toast-icon">${type === 'success' ? '✓' : '!'}</span><div class="toast-text">${message}</div>`;
    container.appendChild(div);
    setTimeout(() => div.remove(), duration);
}

// Alert state flags to avoid repeated popups
let lastMailAlert = 'none';   // 'none' | 'low' | 'zero'
let lastCouponAlert = 'none'; // 'none' | 'low' | 'zero'
let lastMailShort = 0;        // deficit count to avoid repeat
let lastCouponShort = 0;
let lastMailToastAt = 0;
let lastCouponToastAt = 0;
let runOrderLowWarningShown = false; // Track if low warning popup shown on run orders section
let shortenerEnabled = true; // controlled from admin panel toggle
// Onboarding tour
let tourSteps = [];
let tourIndex = 0;
let guidedSteps = [];
let guidedIndex = 0;
let guidedOverlay, guidedSpot, guidedTip;

// Stock warning popup
let stockWarningData = null;

// Logs viewer - simplified version
function highlightLogs(text) {
    if (!text) return 'No logs yet.';
    // Simply escape HTML and return
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

var lastLogContent = '';


function renderLogsList(files, selected) {
    var listEl = document.getElementById('logs-list');
    var mobSel = document.getElementById('logsMobileSelect');
    var countEl = document.getElementById('logs-count');
    
    if (countEl) countEl.textContent = files.length;
    if (!listEl) return;
    
    listEl.innerHTML = '';
    files.forEach(function(f, idx) {
        var item = document.createElement('div');
        item.className = 'logs-list-item' + (f.name === selected ? ' active' : '');
        item.onclick = function() {
            var viewer = document.getElementById('logsViewer');
            if (viewer) viewer.scrollTop = 0;
            refreshLogs(f.name);
        };
        
        var isLatest = f.name === 'latest.log' || idx === 0;
        var icon = isLatest ? '* ' : '';
        var sizeKB = (f.size/1024).toFixed(1);
        var timeStr = new Date(f.modified * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        
        item.innerHTML = '<div class="logs-file-info">' +
            '<div class="logs-file-name">' + icon + f.name + '</div>' +
            '<div class="logs-file-meta">' + sizeKB + ' KB - ' + timeStr + '</div>' +
            '</div>';
        listEl.appendChild(item);
    });
    
    if (mobSel) {
        mobSel.innerHTML = '';
        files.forEach(function(f, idx) {
            var opt = document.createElement('option');
            opt.value = f.name;
            var isLatest = f.name === 'latest.log' || idx === 0;
            opt.textContent = (isLatest ? '* ' : '') + f.name;
            if (f.name === selected) opt.selected = true;
            mobSel.appendChild(opt);
        });
    }
}


function refreshLogs(selectedFile) {
    var mobSel = document.getElementById('logsMobileSelect');
    if (!selectedFile && mobSel && mobSel.value) selectedFile = mobSel.value;
    var qs = selectedFile ? '?file=' + encodeURIComponent(selectedFile) : '';
    
    safeFetch('/api/logs' + qs)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var viewEl = document.getElementById('logsViewer');
            var nameEl = document.getElementById('logs-selected-name');
            var dlEl = document.getElementById('logs-download');
            var statsEl = document.getElementById('logStatsInfo');
            var updateEl = document.getElementById('logLastUpdate');
            
            if (data.error) {
                if (viewEl) {
                    viewEl.innerHTML = '<span class="log-error">Error: ' + escapeHtml(data.error) + '</span>';
                }
                return;
            }
            
            var files = data.files || [];
            var selected = data.selected || (files[0] && files[0].name) || 'latest.log';
            
            renderLogsList(files, selected);
            
            if (nameEl) nameEl.textContent = selected;
            if (dlEl) dlEl.href = '/download/log/' + encodeURIComponent(selected);
            
            if (viewEl && data.content !== lastLogContent) {
                lastLogContent = data.content;
                
                viewEl.innerHTML = highlightLogs(data.content || 'No logs yet.');
                viewEl.scrollTop = viewEl.scrollHeight;
                
                if (statsEl) statsEl.textContent = 'Logs loaded';
                if (updateEl) updateEl.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
                
                // Auto-scroll logic
                var follow = document.getElementById('followLogs');
                if (follow && follow.checked) {
                    viewEl.scrollTop = viewEl.scrollHeight;
                }
                
                // Re-apply filter if active
                applyLogsFilter();
            }
        })
        .catch(function(e) {
            if (!isConnectionError(e)) {
                console.error("Failed to fetch logs:", e);
            }
            var el = document.getElementById('logsViewer');
            if (el) {
                el.innerHTML = '<span class="log-info">' + (serverOffline ? 'Server is offline. Please start the Flask server.' : 'Failed to load logs.') + '</span>';
            }
        });
}


function applyLogsFilter() {
    var searchEl = document.getElementById('logSearch');
    if (!searchEl) return;
    var query = searchEl.value.toLowerCase();
    var viewer = document.getElementById('logsViewer');
    if (!viewer) return;
    var lines = viewer.querySelectorAll('.log-line');
    var visibleCount = 0;
    
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        var text = line.textContent.toLowerCase();
        if (text.indexOf(query) >= 0) {
            line.style.display = 'block';
            visibleCount++;
        } else {
            line.style.display = 'none';
        }
    }
    
    var statsEl = document.getElementById('logStatsInfo');
    if (statsEl && query) {
        statsEl.textContent = 'Showing ' + visibleCount + ' of ' + lines.length + ' lines';
    }
}

function copyLogs() {
    var viewer = document.getElementById('logsViewer');
    var text = viewer.textContent;
    navigator.clipboard.writeText(text).then(function() {
        showToast('success', 'Logs copied to clipboard');
    }).catch(function(err) {
        showToast('error', 'Failed to copy logs');
    });
}


window.onload = ()=> {
    if(localStorage.getItem("theme")==="light"){
        document.body.classList.add("light");
    }
    // Show login success toast if redirected with param
    try {
        const params = new URLSearchParams(window.location.search);
        if (params.get('login') === 'success') {
            showToast('success', 'Logged in successfully');
            params.delete('login');
            const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
            window.history.replaceState({}, '', newUrl);
        }
    } catch(e) {}

    loadFormData();
    checkResources(); // Check resources when page loads
    // Fetch shortener toggle status from admin settings
    fetch('/api/shortener/status')
        .then(r => r.json())
        .then(data => {
            shortenerEnabled = data.enabled !== false;
            console.log('[PAGE LOAD] Shortener enabled:', shortenerEnabled);
        })
        .catch(() => {
            shortenerEnabled = true;
            console.warn('[PAGE LOAD] Could not fetch shortener status, defaulting to enabled');
        });
    // Hide splash screen after load to avoid blocking clicks
    setTimeout(() => {
        const splash = document.getElementById('splashScreen');
        if (splash) splash.style.display = 'none';
    }, 1200);

    // Preload logs list/view
    refreshLogs();
    
    // URLs will be shortened automatically when user clicks "Start Sniper" button
    console.log("[PAGE LOAD] URL shortening will occur when user clicks 'Start Sniper' button");

    
    // Check URL parameter to open specific page
    const urlParams = new URLSearchParams(window.location.search);
    const page = urlParams.get('page');
    if (page === 'runorder') {
        const runOrderLink = document.querySelector('.menu-item:nth-child(3)');
        if (runOrderLink) {
            openPage('runorder', runOrderLink);
        }
    }

    // Onboarding tour prompt (first visit)
    setTimeout(() => {
        try {
            if (!localStorage.getItem('tourDone')) {
                showTourPrompt();
            }
        } catch (e) {
            console.warn('tour check failed', e);
        }
    }, 1200);
};

// SERVER OFFLINE DETECTION
let serverOffline = false;
let serverOfflineCount = 0;
const MAX_OFFLINE_COUNT = 3;

function handleServerOffline() {
    if (!serverOffline) {
        serverOffline = true;
        serverOfflineCount = 0;
        // Show user-friendly message
        const offlineToast = document.createElement('div');
        offlineToast.id = 'server-offline-toast';
        offlineToast.className = 'toast toast-error';
        offlineToast.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 10000; max-width: 400px;';
        offlineToast.innerHTML = '⚠️ Server is offline. Please start the Flask server.';
        document.body.appendChild(offlineToast);
        
        // Auto-remove after 10 seconds
        setTimeout(() => {
            const toast = document.getElementById('server-offline-toast');
            if (toast) toast.remove();
        }, 10000);
    }
    serverOfflineCount++;
}

function handleServerOnline() {
    if (serverOffline) {
        serverOffline = false;
        serverOfflineCount = 0;
        const toast = document.getElementById('server-offline-toast');
        if (toast) toast.remove();
    }
}

function isConnectionError(error) {
    return error instanceof TypeError && (
        error.message.includes('Failed to fetch') ||
        error.message.includes('NetworkError') ||
        error.message.includes('ERR_CONNECTION_REFUSED') ||
        error.message.includes('ERR_NETWORK_CHANGED')
    );
}

// Enhanced fetch wrapper with offline detection
async function safeFetch(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (response.ok || response.status < 500) {
            handleServerOnline();
            return response;
        }
        // Server error but server is online
        handleServerOnline();
        return response;
    } catch (error) {
        if (isConnectionError(error)) {
            handleServerOffline();
            throw error; // Re-throw for caller to handle silently
        }
        handleServerOnline();
        throw error;
    }
}

// CHECK RESOURCES AND SHOW WARNINGS
function checkResources() {
    safeFetch("/check-resources")
        .then(r => r.json())
        .then(data => {
            // warnings suppressed on run order page per request
        })
        .catch(e => {
            if (!isConnectionError(e)) {
                console.error("Failed to check resources:", e);
            }
        });
}

// SHORTEN ALL PRODUCT URLS BEFORE SUBMISSION (sends all URLs in one API call)
async function shortenAllProductUrls(form) {
    console.log('[FORM SUBMIT] ========================================');
    console.log('[FORM SUBMIT] Starting URL shortening process for all product URLs...');
    
    const productUrlInputs = Array.from(form.querySelectorAll('input[name="product_url[]"]'));
    console.log('[FORM SUBMIT] Found', productUrlInputs.length, 'product URL input(s)');
    
    // Collect all URLs that need shortening (> 38 chars)
    const urlsToShorten = [];
    const inputIndexMap = []; // Maps shortened URL index back to input element
    
    productUrlInputs.forEach((input, index) => {
        const originalUrl = input.value.trim();
        console.log(`[FORM SUBMIT] Product #${index + 1}:`, originalUrl);
        console.log(`[FORM SUBMIT] Product #${index + 1} length:`, originalUrl.length);
        
        if (!originalUrl) {
            console.log(`[FORM SUBMIT] ⏭️ Product #${index + 1}: Skipping (empty URL)`);
            return;
        }
        
        if (originalUrl.length <= 38) {
            console.log(`[FORM SUBMIT] ⏭️ Product #${index + 1}: Skipping (length ${originalUrl.length} <= 38)`);
            return;
        }
        
        console.log(`[FORM SUBMIT] ✅ Product #${index + 1}: Will shorten (length ${originalUrl.length} > 38)`);
        urlsToShorten.push(originalUrl);
        inputIndexMap.push({ input: input, index: index + 1, originalUrl: originalUrl });
    });
    
    if (urlsToShorten.length === 0) {
        console.log('[FORM SUBMIT] ⏭️ No URLs to shorten (all are <= 38 chars or empty)');
        console.log('[FORM SUBMIT] ========================================');
        return { allShortened: true, results: [], successCount: 0, failCount: 0 };
    }
    
    console.log('[FORM SUBMIT] Sending', urlsToShorten.length, 'URL(s) to shortening API in one request...');
    
    try {
        // Send all URLs in one API call (like reference code)
        const shortenedUrls = await shortenUrls(urlsToShorten);
        
        // Map shortened URLs back to their input fields
        let successCount = 0;
        const results = [];
        
        shortenedUrls.forEach((shortenedUrl, idx) => {
            const mapping = inputIndexMap[idx];
            if (mapping && shortenedUrl) {
                console.log(`[FORM SUBMIT] ✅ Product #${mapping.index}: Successfully shortened`);
                console.log(`[FORM SUBMIT]   Original: ${mapping.originalUrl}`);
                console.log(`[FORM SUBMIT]   Shortened: ${shortenedUrl}`);
                mapping.input.value = shortenedUrl;
                successCount++;
                results.push({ 
                    index: mapping.index, 
                    success: true, 
                    original: mapping.originalUrl, 
                    shortened: shortenedUrl 
                });
            }
        });
        
        console.log('[FORM SUBMIT] ========================================');
        console.log('[FORM SUBMIT] URL Shortening Summary:');
        console.log('[FORM SUBMIT]   Total processed:', urlsToShorten.length);
        console.log('[FORM SUBMIT]   ✅ Successful:', successCount);
        console.log('[FORM SUBMIT]   ⚠️ Failed:', urlsToShorten.length - successCount);
        console.log('[FORM SUBMIT] ========================================');
        
        return {
            allShortened: successCount === urlsToShorten.length,
            results: results,
            successCount: successCount,
            failCount: urlsToShorten.length - successCount
        };
        
    } catch (error) {
        console.error('[FORM SUBMIT] ❌ Error shortening URLs:', error);
        console.log('[FORM SUBMIT] All URLs will use original values');
        
        // On error, keep all original URLs (inputs already have original values)
        const results = inputIndexMap.map(mapping => ({
            index: mapping.index,
            success: false,
            original: mapping.originalUrl,
            error: error.message
        }));
        
        return {
            allShortened: false,
            results: results,
            successCount: 0,
            failCount: urlsToShorten.length
        };
    }
}

// HANDLE FORM SUBMIT
async function handleSubmit(event) {
    event.preventDefault(); // Stop the default form submission
    
    const form = event.target;
    const startBtn = document.getElementById('startBtn');

    // DEBUG: Check form data before submission
    const formData = new FormData(form);
    const useCouponValue = formData.get('use_coupon');
    console.log('[CLIENT DEBUG] Form submission - use_coupon value:', useCouponValue, 'type:', typeof useCouponValue);
    console.log('[CLIENT DEBUG] All form data:', Object.fromEntries(formData.entries()));

    startBtn.disabled = true;
    startBtn.textContent = shortenerEnabled ? 'Shortening URLs...' : 'Starting...';
    
    try {
        // Step 1: Shorten URLs only if enabled from admin toggle
        if (shortenerEnabled) {
            console.log('[FORM SUBMIT] Step 1: Shortening all product URLs...');
            const shortenResult = await shortenAllProductUrls(form);
            
            if (shortenResult.failCount > 0) {
                showToast('error', `${shortenResult.failCount} URL(s) failed to shorten, using original URLs`);
            } else if (shortenResult.successCount > 0) {
                showToast('success', `All ${shortenResult.successCount} URL(s) shortened successfully`);
            }
        } else {
            console.log('[FORM SUBMIT] Shortener disabled via admin toggle — skipping URL shortening');
        }
        
        // Step 2: Proceed with form submission
        console.log('[FORM SUBMIT] Step 2: Submitting form to server...');
    startBtn.textContent = 'Starting...';
        
        // Get updated form data (with shortened URLs)
        const updatedFormData = new FormData(form);

    // Use fetch to submit the form data asynchronously
        const response = await fetch('/start', {
        method: 'POST',
            body: updatedFormData
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Bot started. The setInterval for check-status will update the button text
            // to "Running..." automatically.
            showToast('success', data.message || 'Bot started');
            // Jump to logs and open the details
            setTimeout(() => {
                const logsDetails = document.getElementById('logsDetails');
                if (logsDetails) {
                    logsDetails.open = true;
                    logsDetails.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }, 300);
        } else {
            startBtn.disabled = false; // Re-enable the button on failure
            startBtn.textContent = '🎯 Start Sniper';
            showToast('error', data.message || 'Start failed');
        }
    } catch (error) {
        // This catches network errors or if the server response isn't valid JSON
        console.error('[FORM SUBMIT] ❌ Submission error:', error);
        startBtn.disabled = false;
        startBtn.textContent = '🎯 Start Sniper';
        showToast('error', 'Submission failed. Please retry.');
    }
    
    return false; // Prevent submission
}


// CHECK BOT STATUS AND UPDATE BUTTONS + AUTO REFRESH SECTIONS
setInterval(()=>{
    if (serverOffline) return; // Skip polling when offline
    safeFetch("/check-status")
        .then(r => r.json())
        .then(data => {
            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');
            if (startBtn) {
            if (data.running) {
                startBtn.disabled = true;
                startBtn.textContent = '🚀 Running...';
            } else {
                startBtn.disabled = false;
                startBtn.textContent = '🎯 Start Sniper';
                }
            }
            if (stopBtn) {
                stopBtn.style.display = data.running ? 'block' : 'none';
            }

            // Auto-refresh logs (run order details)
            const runlog = document.getElementById("runlog");
            if (runlog) {
                safeFetch("/logs").then(r=>r.json()).then(data=>{
                    runlog.innerText = data.join("\n");
                    runlog.scrollTop = runlog.scrollHeight;
                }).catch(e => {
                    if (!isConnectionError(e)) {
                        console.error("Failed to fetch logs:", e);
                    }
                });
            }

            // Auto-refresh logs page list/viewer if present
            const logsViewer = document.getElementById("logsViewer");
            if (logsViewer && typeof refreshLogs === "function") {
                refreshLogs();
            }

            // Auto-refresh resource warnings
            if (typeof checkResources === "function") {
                checkResources();
            }
        }).catch(e => {
            console.log("check-status failed, server offline?", e);
            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');
            if (startBtn) {
                startBtn.disabled = true;
                startBtn.textContent = '🚫 Server Offline';
            }
            if (stopBtn) {
                stopBtn.style.display = 'none';
            }
        });
}, 2000);

// SAVE FORM DATA TO LOCALSTORAGE
function saveFormData() {
    const formData = {
        first_name: document.querySelector('input[name="first_name"]')?.value || '',
        surname: document.querySelector('input[name="surname"]')?.value || '',
        phone: document.querySelector('input[name="phone"]')?.value || '',
        pincode: document.querySelector('input[name="pincode"]')?.value || '',
        address1: document.querySelector('input[name="address1"]')?.value || '',
        address2: document.querySelector('input[name="address2"]')?.value || '',
        limit: document.querySelector('input[name="limit"]')?.value || '4',
        max_price: document.querySelector('input[name="max_price"]')?.value || '1300',
        parallel: document.querySelector('input[name="parallel"]')?.value || '4',
        deal_keyword: document.querySelector('input[name="deal_keyword"]')?.value || '',
        use_coupon: document.querySelector('input[name="use_coupon"]:checked')?.value || '',
        retry: document.querySelector('input[name="retry"]')?.checked || false,
        allow_less_qty: document.querySelector('input[name="allow_less_qty"]')?.checked !== false,
        remove_mail_on_success: document.querySelector('input[name="remove_mail_on_success"]')?.checked !== false
    };
    localStorage.setItem('formData', JSON.stringify(formData));
}

// LOAD FORM DATA FROM LOCALSTORAGE
function loadFormData() {
    const savedData = localStorage.getItem('formData');
    if (savedData) {
        const formData = JSON.parse(savedData);
        
        const firstNameInput = document.querySelector('input[name="first_name"]');
        if (firstNameInput && formData.first_name) firstNameInput.value = formData.first_name;
        
        const surnameInput = document.querySelector('input[name="surname"]');
        if (surnameInput && formData.surname) surnameInput.value = formData.surname;
        
        // Handle legacy name field (split if exists)
        if (formData.name && !formData.first_name) {
            const nameParts = formData.name.split(' ', 2);
            if (firstNameInput) firstNameInput.value = nameParts[0] || '';
            if (surnameInput && nameParts.length > 1) surnameInput.value = nameParts[1] || '';
        }
        
        const phoneInput = document.querySelector('input[name="phone"]');
        if (phoneInput && formData.phone) phoneInput.value = formData.phone;
        
        const pincodeInput = document.querySelector('input[name="pincode"]');
        if (pincodeInput && formData.pincode) pincodeInput.value = formData.pincode;
        
        const address1Input = document.querySelector('input[name="address1"]');
        if (address1Input && formData.address1) address1Input.value = formData.address1;
        
        const address2Input = document.querySelector('input[name="address2"]');
        if (address2Input && formData.address2) address2Input.value = formData.address2;
        
        const limitInput = document.querySelector('input[name="limit"]');
        if (limitInput && formData.limit) limitInput.value = formData.limit;
        
        const maxPriceInput = document.querySelector('input[name="max_price"]');
        if (maxPriceInput && formData.max_price) maxPriceInput.value = formData.max_price;
        
        const parallelInput = document.querySelector('input[name="parallel"]');
        if (parallelInput && formData.parallel) parallelInput.value = formData.parallel;
        
        const dealInput = document.querySelector('input[name="deal_keyword"]');
        if (dealInput && formData.deal_keyword) dealInput.value = formData.deal_keyword;
        
        const useCouponInput = document.querySelector(`input[name="use_coupon"][value="${formData.use_coupon}"]`);
        if (useCouponInput) useCouponInput.checked = true;
        
        const retryInput = document.querySelector('input[name="retry"]');
        if (retryInput) retryInput.checked = formData.retry;
        
        const allowLessQtyInput = document.querySelector('input[name="allow_less_qty"]');
        if (allowLessQtyInput) allowLessQtyInput.checked = formData.allow_less_qty !== false;
        
        const removeMailOnSuccessInput = document.querySelector('input[name="remove_mail_on_success"]');
        if (removeMailOnSuccessInput) removeMailOnSuccessInput.checked = formData.remove_mail_on_success !== false;
    }
}

// AUTO-SAVE FORM DATA ON INPUT
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('orderForm');
    if (form) {
        form.addEventListener('input', saveFormData);
        form.addEventListener('change', saveFormData);
    }
});

// SIDEBAR TOGGLE (responsive)
function toggleSidebar(forceClose = false) {
    if (forceClose) {
        document.body.classList.remove('sidebar-open');
        return;
    }
    document.body.classList.toggle('sidebar-open');
}

// PAGE SWITCHING
function openPage(page, el){
    document.querySelectorAll(".page").forEach(p=>p.classList.add("hidden"));
    document.querySelector(`#${page}`).classList.remove("hidden");
    document.querySelectorAll(".menu-item").forEach(m=>m.classList.remove("active"));
    document.querySelectorAll(".bottom-nav-item").forEach(m=>m.classList.remove("active"));
    
    if (el) {
    el.classList.add("active");
    }
    
    // Sync bottom nav if sidebar item was clicked
    if (el && el.classList.contains("menu-item")) {
        const bottomNavItem = document.querySelector(`.bottom-nav-item[onclick*="${page}"]`);
        if (bottomNavItem) {
            bottomNavItem.classList.add("active");
        }
    }
    
    // Sync sidebar if bottom nav item was clicked
    if (el && el.classList.contains("bottom-nav-item")) {
        const sidebarItem = document.querySelector(`.menu-item[onclick*="${page}"]`);
        if (sidebarItem) {
            sidebarItem.classList.add("active");
        }
    }
    
    // Reset low warning flag when navigating away from run orders section
    if (page !== 'runorder') {
        runOrderLowWarningShown = false;
    }
    
    // Refresh resources if switching to runorder page
    if (page === 'runorder') {
        checkResources();
    }
    
    // Load IMAP config if switching to imap page
    if (page === 'imap') {
        loadImapConfig();
    }
    
    // Close sidebar on mobile after navigation
    document.body.classList.remove('sidebar-open');
}

// Update bottom nav active state (helper function)
function updateBottomNav(clickedItem) {
    document.querySelectorAll(".bottom-nav-item").forEach(item => {
        item.classList.remove("active");
    });
    if (clickedItem) {
        clickedItem.classList.add("active");
    }
}

// SHORTEN MULTIPLE URLS FUNCTION (sends all URLs in one request)
async function shortenUrls(urls) {
    console.log("[URL SHORTENER] ========================================");
    console.log("[URL SHORTENER] Starting URL shortening process...");
    console.log("[URL SHORTENER] Total URLs to shorten:", urls.length);
    console.log("[URL SHORTENER] URLs:", urls);
    urls.forEach((url, idx) => {
        console.log(`[URL SHORTENER]   URL #${idx + 1} (length ${url.length}):`, url);
    });
    console.log("[URL SHORTENER] API Endpoint: /api/shorten-url (proxy)");
    
    try {
        const payload = { urls: urls };
        console.log("[URL SHORTENER] Request payload:", JSON.stringify(payload, null, 2));
        
        const response = await fetch("/api/shorten-url", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });
        
        console.log("[URL SHORTENER] Response status:", response.status);
        console.log("[URL SHORTENER] Response statusText:", response.statusText);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error("[URL SHORTENER] ❌ HTTP Error Response Body:", errorText);
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log("[URL SHORTENER] Response data:", JSON.stringify(data, null, 2));
        
        if (data.results && Array.isArray(data.results) && data.results.length === urls.length) {
            console.log("[URL SHORTENER] ✅ Successfully shortened all URLs");
            data.results.forEach((shortenedUrl, idx) => {
                const originalUrl = urls[idx];
                console.log(`[URL SHORTENER]   URL #${idx + 1}:`);
                console.log(`[URL SHORTENER]     Original (${originalUrl.length} chars):`, originalUrl);
                console.log(`[URL SHORTENER]     Shortened (${shortenedUrl.length} chars):`, shortenedUrl);
                console.log(`[URL SHORTENER]     Reduction: ${originalUrl.length - shortenedUrl.length} characters`);
            });
            console.log("[URL SHORTENER] ========================================");
            return data.results;
        }
        
        console.error("[URL SHORTENER] ❌ Invalid response format or length mismatch");
        console.log("[URL SHORTENER] Expected", urls.length, "results, got", data.results?.length || 0);
        throw new Error("Invalid response from shortening API");
    } catch (error) {
        console.error("[URL SHORTENER] ❌ Error shortening URLs:", error);
        console.error("[URL SHORTENER] Error name:", error.name);
        console.error("[URL SHORTENER] Error message:", error.message);
        console.log("[URL SHORTENER] ========================================");
        throw error;
    }
}

// REMOVED: Automatic URL shortening on blur/paste
// URLs will only be shortened when user clicks "Start Sniper" button

// ADD PRODUCT ROW
function addProduct(){
    console.log("[ADD PRODUCT] ========================================");
    console.log("[ADD PRODUCT] Adding new product row...");
    
    let div=document.createElement("div");
    div.className="product-row";
    div.innerHTML=`
        <div style="flex: 1;">
            <label class="form-label">Product URL *</label>
            <input type="text" name="product_url[]" placeholder="Enter product URL" required>
        </div>
        <div style="width: 120px;">
            <label class="form-label">Quantity *</label>
            <input type="number" name="product_qty[]" value="1" placeholder="Qty" required>
        </div>
        <button type="button" class="delete-product-btn" onclick="removeProduct(this)" title="Remove Product">🗑️</button>
    `;
    document.getElementById("product-list").appendChild(div);
    console.log("[ADD PRODUCT] ✅ Product row added to DOM");
    
    // No automatic URL shortening - URLs will be shortened when user clicks "Start Sniper"
    console.log("[ADD PRODUCT] ========================================");
}

// REMOVE PRODUCT ROW
function removeProduct(btn) {
    const productRow = btn.closest('.product-row');
    const productList = document.getElementById('product-list');
    
    // Don't allow removal if it's the last product
    if (productList.children.length <= 1) {
        // We can't use alert, let's flash the row
        productRow.style.background = 'var(--danger)';
        setTimeout(() => { productRow.style.background = 'transparent'; }, 500);
        return;
    }
    
    productRow.style.animation = 'fadeOut 0.3s ease-out';
    setTimeout(() => {
        productRow.remove();
    }, 300);
}

// UPDATE FILE NAME DISPLAY
function updateFileName(input, displayId) {
    const display = document.getElementById(displayId);
    if (input.files && input.files[0]) {
        display.textContent = '✓ ' + input.files[0].name;
    } else {
        display.textContent = '';
    }
}

// DRAG AND DROP FUNCTIONALITY
document.addEventListener('DOMContentLoaded', function() {
    // Setup drag and drop for mail file
    const mailUploadArea = document.querySelector('#mail-file').closest('.upload-area');
    if (mailUploadArea) {
        setupDragAndDrop(mailUploadArea, 'mail-file');
    }
    
    // Setup drag and drop for coupon file
    const couponUploadArea = document.querySelector('#coupon-file').closest('.upload-area');
    if (couponUploadArea) {
        setupDragAndDrop(couponUploadArea, 'coupon-file');
    }
});

function setupDragAndDrop(uploadArea, inputId) {
    const input = document.getElementById(inputId);
    
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.add('drag-over');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.remove('drag-over');
        }, false);
    });
    
    uploadArea.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        
        if (files.length > 0) {
            input.files = files;
            const displayId = inputId === 'mail-file' ? 'mail-name' : 'coupon-name';
            updateFileName(input, displayId);
        }
    }, false);
}

// LIVE LOGS
setInterval(()=>{
    if (serverOffline) return; // Skip polling when offline
    safeFetch("/logs").then(r=>r.json()).then(data=>{
        const el = document.getElementById("runlog");
        if (!el) return;
        el.innerText = data.join("\\n");
        el.scrollTop = el.scrollHeight;
    }).catch(e => {
        if (!isConnectionError(e)) {
            console.error("Failed to fetch logs:", e);
        }
    });
},1500);

// DEAL SELECTION MODAL FUNCTIONS
let selectedDealIndex = null;
let dealProducts = [];
let dealSessionId = null;

function showDealModal(products, sessionId, matchedIndex) {
    dealProducts = products;
    dealSessionId = sessionId;
    selectedDealIndex = matchedIndex !== null && matchedIndex !== undefined ? matchedIndex : null;
    
    const dealList = document.getElementById('dealList');
    dealList.innerHTML = '';
    
    products.forEach((product, index) => {
        const div = document.createElement('div');
        div.className = 'deal-item';
        if (index === matchedIndex) {
            div.classList.add('selected');
            div.innerHTML = `<strong>${index + 1}) ${product.name} ← MATCHED</strong>`;
        } else {
            div.textContent = `${index + 1}) ${product.name}`;
        }
        div.onclick = () => selectDeal(index);
        dealList.appendChild(div);
    });
    
    document.getElementById('dealModal').style.display = 'block';
}

function selectDeal(index) {
    selectedDealIndex = index;
    const items = document.querySelectorAll('.deal-item');
    items.forEach((item, i) => {
        if (i === index) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }
    });
}

function confirmDealSelection() {
    if (selectedDealIndex === null) {
        if (!confirm('No product selected. Skip deal application?')) {
            return;
        }
        selectedDealIndex = -1;
    }

    fetch('/deal-selection', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            session_id: dealSessionId,
            selected_index: selectedDealIndex === -1 ? null : selectedDealIndex
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeDealModal();
        } else {
            alert('Error submitting selection: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error submitting selection');
    });
}

function closeDealModal() {
    document.getElementById('dealModal').style.display = 'none';
    selectedDealIndex = null;
    dealProducts = [];
    dealSessionId = null;
}

// Poll for deal selection requests
function pollDealSelection() {
    if (serverOffline) return; // Skip polling when offline
    safeFetch('/deal-poll')
        .then(response => response.json())
        .then(data => {
            const modal = document.getElementById('dealModal');
            const isModalVisible = modal && modal.style.display !== 'none' && modal.style.display !== '';
            
            if (data.pending && !isModalVisible) {
                const products = data.products.map(p => ({name: p.name, index: p.index}));
                showDealModal(products, data.session_id, data.matched_index);
            }
        })
        .catch(error => {
            if (!isConnectionError(error)) {
                console.error('Deal poll error:', error);
            }
        });
}

// Poll for deal selection every 3 seconds
setInterval(pollDealSelection, 3000);

// ===========================
// ONBOARDING TOUR
// ===========================
function showTourPrompt(){
    const ov = document.getElementById('tourOverlay');
    const startBtn = document.getElementById('tourNextBtn');
    const skipBtn = document.getElementById('tourSkipBtn');
    if (!ov || !startBtn || !skipBtn) return;
    document.getElementById('tourBody').textContent = 'Want a quick guided tour of all key fields and sections?';
    startBtn.textContent = 'Start tour';
    startBtn.onclick = ()=> {
        try { localStorage.setItem('tourDone','1'); } catch(e){}
        ov.style.display = 'none';
        startGuidedTour();
    };
    skipBtn.onclick = ()=> {
        try { localStorage.setItem('tourDone','1'); } catch(e){}
        ov.style.display = 'none';
    };
    ov.style.display = 'flex';
}

function startGuidedTour(){
    document.body.classList.add('tour-lock');
    initGuidedElements();
    guidedSteps = [
        { page:'runorder', selector:'input[name="first_name"]', title:'First Name', desc:'Enter the customer first name used during checkout.' },
        { page:'runorder', selector:'input[name="surname"]', title:'Surname', desc:'Surname is required for address details.' },
        { page:'runorder', selector:'input[name="phone"]', title:'Phone Number', desc:'Phone number used for delivery contact and OTP if needed.' },
        { page:'runorder', selector:'input[name="pincode"]', title:'Pincode', desc:'Delivery pincode to locate serviceability and slots.' },
        { page:'runorder', selector:'input[name="address1"]', title:'Address Line 1', desc:'Street/building info for shipping address.' },
        { page:'runorder', selector:'input[name="address2"]', title:'Address Line 2', desc:'Apartment/suite/floor (optional but helps accuracy).' },
        { page:'runorder', selector:'input[name="limit"]', title:'Order Limit', desc:'Total orders to attempt this run (must not exceed available mails).' },
        { page:'runorder', selector:'input[name="max_price"]', title:'Max Price', desc:'Skip items priced above this threshold.' },
        { page:'runorder', selector:'input[name="parallel"]', title:'Parallel Orders', desc:'How many workers run simultaneously.' },
        { page:'runorder', selector:'input[name="deal_keyword"]', title:'Deal Keyword', desc:'Optional keyword to auto-pick matching products; otherwise you’ll choose manually.' },
        { page:'runorder', selector:'input[name="use_coupon"][value="true"]', title:'Use Coupon', desc:'Enable if you want coupons applied (checks coupon availability before start).' },
        { page:'runorder', selector:'#product-list .product-row input[name="product_url[]"]', title:'Product URL', desc:'Add product URLs to cart; use Add Product for multiples.' },
        { page:'runorder', selector:'#startBtn', title:'Start Sniper', desc:'Launch the run after all checks pass. Stop with the red button if needed.' },
        { page:'runorder', selector:'details summary', title:'Detailed Logs', desc:'Live terminal logs stream here during the run.' },
        { page:'reports', selector:'#reports .page-title', title:'Reports', desc:'Preview/download CSV and text reports from completed runs.' },
        { page:'logs', selector:'#logs .page-title', title:'Logs', desc:'Browse historic log files; latest.log streams the current run.' },
        { page:'accounts', selector:'#accounts', title:'Accounts', desc:'Upload/drag-drop mail & coupon files or edit them inline.' },
    ];
    guidedIndex = 0;
    renderGuidedStep();
}

function initGuidedElements(){
    if (guidedOverlay) return;
    guidedOverlay = document.createElement('div');
    guidedOverlay.className = 'guided-overlay';
    guidedSpot = document.createElement('div');
    guidedSpot.className = 'guided-spotlight';
    guidedTip = document.createElement('div');
    guidedTip.className = 'guided-tooltip';
    guidedTip.innerHTML = `
        <h4 id="guidedTitle"></h4>
        <p id="guidedDesc"></p>
        <div class="guided-controls">
            <button class="guided-btn" id="guidedSkip">Skip</button>
            <button class="guided-btn primary" id="guidedNext">Next</button>
        </div>
    `;
    guidedOverlay.appendChild(guidedSpot);
    guidedOverlay.appendChild(guidedTip);
    document.body.appendChild(guidedOverlay);
    document.getElementById('guidedSkip').onclick = endGuidedTour;
    document.getElementById('guidedNext').onclick = ()=> advanceGuided(true);
}

function renderGuidedStep(retries=0){
    if (!guidedSteps.length || guidedIndex >= guidedSteps.length){
        endGuidedTour();
        return;
    }
    const step = guidedSteps[guidedIndex];
    // Ensure correct page is open
    if (!document.getElementById(step.page) || document.getElementById(step.page).classList.contains('hidden')) {
        const link = Array.from(document.querySelectorAll('.menu-item')).find(el => el.getAttribute('onclick')?.includes(`openPage('${step.page}'`));
        if (link) openPage(step.page, link);
    }
    const el = document.querySelector(step.selector);
    if (!el) {
        if (guidedIndex < guidedSteps.length-1){
            guidedIndex++;
            renderGuidedStep();
            return;
        } else {
            endGuidedTour();
            return;
        }
    }
    el.scrollIntoView({behavior:'smooth', block:'center', inline:'center'});
    setTimeout(() => {
        const rect = el.getBoundingClientRect();
        const pad = 10;
        guidedSpot.style.display = 'block';
        guidedOverlay.style.display = 'block';
        guidedSpot.style.left = `${rect.left - pad}px`;
        guidedSpot.style.top = `${rect.top - pad}px`;
        guidedSpot.style.width = `${rect.width + pad*2}px`;
        guidedSpot.style.height = `${rect.height + pad*2}px`;
        // Tooltip content
        document.getElementById('guidedTitle').textContent = step.title;
        document.getElementById('guidedDesc').textContent = step.desc;
        const tipRect = guidedTip.getBoundingClientRect();
        let top = rect.bottom + 14;
        let left = rect.left;
        guidedTip.classList.remove('tip-above');
        if (left + tipRect.width > window.innerWidth - 24) {
            left = window.innerWidth - tipRect.width - 24;
        }
        if (top + tipRect.height > window.innerHeight - 20) {
            top = rect.top - tipRect.height - 14;
            guidedTip.classList.add('tip-above');
        }
        if (left < 12) left = 12;
        guidedTip.style.left = `${left}px`;
        guidedTip.style.top = `${top}px`;
        guidedTip.style.display = 'block';
        // Update next button label
        const nextBtn = document.getElementById('guidedNext');
        if (nextBtn) nextBtn.textContent = guidedIndex === guidedSteps.length-1 ? 'Finish' : 'Next';
    }, retries ? 120 : 220);
}

function advanceGuided(manual=false){
    guidedIndex++;
    renderGuidedStep(manual ? 0 : 1);
}

function endGuidedTour(){
    guidedIndex = 0;
    guidedSteps = [];
    if (guidedOverlay) guidedOverlay.style.display = 'none';
    document.body.classList.remove('tour-lock');
}

// FILE EDITOR MODAL FUNCTIONS
let currentEditingFile = null;

function openEditor(fileType) {
    currentEditingFile = fileType;
    const modal = document.getElementById('fileEditorModal');
    const title = fileType === 'mail' ? '📧 Edit Mail File' : '🏷️ Edit Coupon File';
    document.getElementById('fileEditorTitle').textContent = title;
    document.getElementById('fileEditorContent').value = '';
    document.getElementById('fileEditorStatus').textContent = 'Loading...';
    modal.style.display = 'block';
    
    // Load file content
    fetch(`/api/get-file/${fileType}`)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                document.getElementById('fileEditorStatus').textContent = 'Error: ' + data.error;
                document.getElementById('fileEditorStatus').style.color = 'var(--danger)';
            } else {
                document.getElementById('fileEditorContent').value = data.content || '';
                document.getElementById('fileEditorStatus').textContent = data.message || 'File loaded';
                document.getElementById('fileEditorStatus').style.color = 'var(--success)';
            }
        })
        .catch(e => {
            document.getElementById('fileEditorStatus').textContent = 'Failed to load file: ' + e;
            document.getElementById('fileEditorStatus').style.color = 'var(--danger)';
        });
}

function closeFileEditor() {
    document.getElementById('fileEditorModal').style.display = 'none';
    currentEditingFile = null;
}

function saveFileEditor() {
    if (!currentEditingFile) return;
    
    const content = document.getElementById('fileEditorContent').value;
    const statusEl = document.getElementById('fileEditorStatus');
    statusEl.textContent = 'Saving...';
    statusEl.style.color = 'var(--text-muted)';
    
    fetch(`/api/save-file/${currentEditingFile}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({content: content})
    })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                statusEl.textContent = 'Error: ' + data.error;
                statusEl.style.color = 'var(--danger)';
            } else {
                statusEl.textContent = data.message || 'File saved successfully!';
                statusEl.style.color = 'var(--success)';
                // Update status in accounts page
                const statusId = currentEditingFile === 'mail' ? 'mail-editor-status' : 'coupon-editor-status';
                const accountsStatus = document.getElementById(statusId);
                if (accountsStatus) {
                    accountsStatus.textContent = '✓ Last saved: ' + new Date().toLocaleTimeString();
                }
            }
        })
        .catch(e => {
            statusEl.textContent = 'Failed to save: ' + e;
            statusEl.style.color = 'var(--danger)';
        });
}


// DASHBOARD STATS WITH ANIMATIONS
function updateCircle(circleId, percent) {
    const circle = document.getElementById(circleId);
    if (!circle) return;
    const radius = circle.r.baseVal.value;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (percent / 100) * circumference;
    circle.style.strokeDashoffset = offset;
}

setInterval(()=>{
    if (serverOffline) return; // Skip polling when offline
    safeFetch("/stats").then(r=>r.json()).then(s=>{
        // Update stat cards
        document.getElementById("total").innerText=s.total;
        document.getElementById("success").innerText=s.success;
        document.getElementById("failure").innerText=s.failure;
        document.getElementById("mails_left").innerText=s.mails_left;
        document.getElementById("coupons_left").innerText=s.coupons_left;

        // Current order limit from form (fallback 1)
        const limitInput = document.querySelector('input[name="limit"]');
        const orderLimit = parseInt(limitInput?.value || "1", 10) || 1;

        // Warnings for low/zero mails
        if (s.mails_left === 0) {
            setAlertBox('dashAlert', '❌ No mails left. Add more mails to continue.', 'error');
            if (lastMailAlert !== 'zero') {
                showToast('error', 'No mails left. Please upload mail list.');
                lastMailAlert = 'zero';
                lastMailToastAt = Date.now();
            }
        } else if (s.mails_left <= 3) {
            setAlertBox('dashAlert', '⚠️ Mails are running low. Please add more mails soon.', 'warning');
            
            // Show popup on run orders section only (one time for 4 seconds)
            const runOrderPage = document.getElementById('runorder');
            if (runOrderPage && !runOrderPage.classList.contains('hidden') && !runOrderLowWarningShown) {
                showToast('error', '⚠️ Mails are running low. Please add more mails soon.', 4000);
                runOrderLowWarningShown = true;
            }
            
            if (lastMailAlert !== 'low' || Date.now() - lastMailToastAt > 15000) {
                // Don't show toast here if we already showed it on run orders section
                if (!(runOrderPage && !runOrderPage.classList.contains('hidden'))) {
                    showToast('error', 'Mails are running low.');
                }
                lastMailAlert = 'low';
                lastMailToastAt = Date.now();
            }
            lastMailShort = 0;
        } else {
            setAlertBox('dashAlert', '');
            lastMailAlert = 'none';
            lastMailShort = 0;
        }

        // Error if mails less than order limit
        if (s.mails_left < orderLimit) {
            const needed = orderLimit - s.mails_left;
            setAlertBox('dashAlert', `❌ Not enough mails. Add ${needed} more. Currently have ${s.mails_left}.`, 'error');
            if (lastMailShort !== needed || Date.now() - lastMailToastAt > 15000) {
                showToast('error', `Mails not enough. Need ${needed} more (have ${s.mails_left}).`);
                lastMailShort = needed;
                lastMailToastAt = Date.now();
            }
        }

        // Warnings for coupons if user chose to use coupons
        const useCouponYes = document.querySelector('input[name="use_coupon"][value="true"]:checked');
        if (useCouponYes) {
            if (s.coupons_left === 0) {
                setAlertBox('dashAlert', '❌ No coupons left. Upload coupons or switch off coupon usage.', 'error');
                if (lastCouponAlert !== 'zero' || Date.now() - lastCouponToastAt > 15000) {
                    showToast('error', 'No coupons left. Upload coupons or disable coupon usage.');
                    lastCouponAlert = 'zero';
                    lastCouponToastAt = Date.now();
                }
            } else if (s.coupons_left <= 3) {
                setAlertBox('dashAlert', '⚠️ Coupons are running low. Please upload more.', 'warning');
                
                // Show popup on run orders section only (one time for 4 seconds)
                const runOrderPage = document.getElementById('runorder');
                if (runOrderPage && !runOrderPage.classList.contains('hidden') && !runOrderLowWarningShown) {
                    showToast('error', '⚠️ Coupons are running low. Please upload more.', 4000);
                    runOrderLowWarningShown = true;
                }
                
                if (lastCouponAlert !== 'low' || Date.now() - lastCouponToastAt > 15000) {
                    // Don't show toast here if we already showed it on run orders section
                    if (!(runOrderPage && !runOrderPage.classList.contains('hidden'))) {
                        showToast('error', 'Coupons are running low.');
                    }
                    lastCouponAlert = 'low';
                    lastCouponToastAt = Date.now();
                }
                lastCouponShort = 0;
            } else {
                // only clear if not already set by mails error
                if (!(s.mails_left === 0 || s.mails_left <= 3)) {
                    setAlertBox('dashAlert', '');
                }
                lastCouponAlert = 'none';
                lastCouponShort = 0;
            }

            // Error if coupons less than order limit
            if (s.coupons_left < orderLimit) {
                const neededC = orderLimit - s.coupons_left;
                setAlertBox('dashAlert', `❌ Not enough coupons. Add ${neededC} more. Currently have ${s.coupons_left}.`, 'error');
                if (lastCouponShort !== neededC || Date.now() - lastCouponToastAt > 15000) {
                    showToast('error', `Coupons not enough. Need ${neededC} more (have ${s.coupons_left}).`);
                    lastCouponShort = neededC;
                    lastCouponToastAt = Date.now();
                }
            }
        } else {
            lastCouponShort = 0;
        }
        
        // Calculate percentages
        const total = (s.success + s.failure) || 1; // Base percentage on success+failure
        const successPercent = Math.round((s.success / total) * 100) || 0;
        const failurePercent = Math.round((s.failure / total) * 100) || 0;
        
        // Update success rate card
        document.getElementById("success-percent-text").innerText = successPercent + "%";
        document.getElementById("success-bar").style.width = successPercent + "%";
        document.getElementById("success-count").innerText = s.success;
        document.getElementById("total-count").innerText = s.success + s.failure;
        updateCircle("success-circle", successPercent);
        
        // Update failure rate card
        document.getElementById("failure-percent-text").innerText = failurePercent + "%";
        document.getElementById("failure-bar").style.width = failurePercent + "%";
        document.getElementById("failure-count").innerText = s.failure;
        document.getElementById("total-count-2").innerText = s.success + s.failure;
        updateCircle("failure-circle", failurePercent);
    }).catch(e => {
        if (!isConnectionError(e)) {
            console.error("Failed to fetch stats:", e);
        }
    });
},1500);

let lastReportsSig = null;

function loadReports() {
    const box = document.getElementById("report-list");
    const loadingEl = document.getElementById("reports-loading");
    
    loadingEl.style.display = "block";
    box.innerHTML = "";

    fetch("/api/list-reports")
        .then(r => r.json())
        .then(data => {
            loadingEl.style.display = "none";
            box.innerHTML = "";

            const mapping = {
                success: {
                    name: "Success Report",
                    icon: "✅",
                    description: "Successfully completed orders",
                    color: "var(--success)"
                },
                failure: {
                    name: "Failure Report",
                    icon: "❌",
                    description: "Failed orders and errors",
                    color: "var(--danger)"
                },
                failed_coupon: {
                    name: "Failed Coupons",
                    icon: "🔻",
                    description: "Coupons that failed (invalid / max usage)",
                    color: "var(--danger)"
                },
                used_coupon: {
                    name: "Used Coupons",
                    icon: "🏷️",
                    description: "Coupon codes that have been used",
                    color: "var(--warning)"
                },
                used_mail: {
                    name: "Used Mails",
                    icon: "📧",
                    description: "Email accounts that have been used",
                    color: "var(--blue)"
                },
                removed_mails: {
                    name: "Removed Mails",
                    icon: "🗑️",
                    description: "Successfully used emails (removed from mail.txt)",
                    color: "var(--success)"
                }
            };

            let hasReports = false;

            for (let key in mapping) {
                if (data[key]) {
                    hasReports = true;
                    fetch(`/api/report-info/${key}`)
                        .then(r => {
                            if (!r.ok) {
                                throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                            }
                            return r.json();
                        })
                        .then(info => {
                            const report = mapping[key];
                            const size = formatFileSize(info.size || 0);
                            const modified = info.modified ? new Date(info.modified * 1000).toLocaleString() : "Unknown";
                            const rowCount = info.rows || 0;
                            
                            const card = document.createElement("div");
                            card.className = "report-card";
                            card.innerHTML = `
                                <div class="report-card-header">
                                    <div class="report-icon" style="background: linear-gradient(135deg, ${report.color}20 0%, ${report.color}30 100%); border-color: ${report.color}50;">
                                        ${report.icon}
                                    </div>
                                    <div class="report-title">${report.name}</div>
                                </div>
                                <div style="color: var(--text-muted); font-size: 0.9em; margin-bottom: 15px;">
                                    ${report.description}
                                </div>
                                <div class="report-info">
                                    <div class="report-info-item">
                                        <strong>📊 Rows:</strong>
                                        <span>${rowCount.toLocaleString()}</span>
                                    </div>
                                    <div class="report-info-item">
                                        <strong>💾 Size:</strong>
                                        <span>${size}</span>
                                    </div>
                                    <div class="report-info-item">
                                        <strong>🕒 Modified:</strong>
                                        <span>${modified}</span>
                                    </div>
                                </div>
                                <div class="report-actions">
                                    <button onclick="viewReport('${key}')" class="report-btn report-btn-view">
                                        👁️ View
                                    </button>
                                    <a href="/download/${key}" class="report-btn report-btn-download" download>
                                        📥 Download
                                    </a>
                                </div>
                            `;
                            box.appendChild(card);
                        })
                        .catch(e => {
                            console.error(`Error loading info for ${key}:`, e);
                            // Fallback card without detailed info
                            const report = mapping[key];
                            const card = document.createElement("div");
                            card.className = "report-card";
                            card.innerHTML = `
                                <div class="report-card-header">
                                    <div class="report-icon" style="background: linear-gradient(135deg, ${report.color}20 0%, ${report.color}30 100%); border-color: ${report.color}50;">
                                        ${report.icon}
                                    </div>
                                    <div class="report-title">${report.name}</div>
                                </div>
                                <div style="color: var(--text-muted); font-size: 0.9em; margin-bottom: 15px;">
                                    ${report.description}
                                </div>
                                <div class="report-actions">
                                    <button onclick="viewReport('${key}')" class="report-btn report-btn-view">
                                        👁️ View
                                    </button>
                                    <a href="/download/${key}" class="report-btn report-btn-download" download>
                                        📥 Download
                                    </a>
                                </div>
                            `;
                            box.appendChild(card);
                        });
                }
            }

            if (!hasReports) {
                box.innerHTML = `
                    <div class="report-empty-state">
                        <div class="report-empty-icon">📭</div>
                        <div class="report-empty-text">No Reports Available</div>
                        <div class="report-empty-subtext">Reports will appear here once orders are processed</div>
                    </div>
                `;
            }
        })
        .catch(e => {
            loadingEl.style.display = "none";
            box.innerHTML = `
                <div class="report-empty-state">
                    <div class="report-empty-icon">⚠️</div>
                    <div class="report-empty-text">Error Loading Reports</div>
                    <div class="report-empty-subtext">${e.message || "Failed to fetch reports"}</div>
                </div>
            `;
        });
}

// Lightweight poller: refresh reports only when status changes
setInterval(() => {
    const reportsPage = document.getElementById("reports");
    if (!reportsPage || reportsPage.classList.contains("hidden")) return;
    fetch("/api/list-reports")
        .then(r => r.json())
        .then(data => {
            const sig = JSON.stringify(data);
            if (sig !== lastReportsSig) {
                lastReportsSig = sig;
                loadReports();
            }
        })
        .catch(()=>{});
}, 8000);

function formatFileSize(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + " " + sizes[i];
}

function viewReport(type) {
    const modalBody = document.getElementById("reportModalBody");
    const modal = document.getElementById("reportModal");
    const modalTitle = document.getElementById("reportModalTitle");
    const modalSubtitle = document.getElementById("reportModalSubtitle");
    const modalStats = document.getElementById("reportModalStats");
    
    // Set report name based on type
    const reportNames = {
        'success': 'Success Report',
        'failure': 'Failure Report',
        'failed_coupon': 'Failed Coupons',
        'used_coupon': 'Used Coupons',
        'used_mail': 'Used Mails',
        'removed_mails': 'Removed Mails'
    };
    const reportFileNames = {
        'success': 'success.csv',
        'failure': 'failure.csv',
        'failed_coupon': 'failed_coupon.csv',
        'used_coupon': 'used_coupon.csv',
        'used_mail': 'used_mail.csv',
        'removed_mails': 'removed_mails.txt'
    };
    
    modalTitle.textContent = reportNames[type] || 'Report Viewer';
    modalSubtitle.textContent = reportFileNames[type] || 'Loading...';
    modalStats.textContent = 'Loading...';
    modalBody.innerHTML = '<div style="text-align: center; padding: 60px; color: rgba(148, 163, 184, 1);"><div style="animation: spin 1s linear infinite; display: inline-block; font-size: 48px; margin-bottom: 16px;">⏳</div><div style="font-size: 16px;">Loading report...</div></div>';
    modal.style.display = "flex"; /* Use flex to center content */
    
    fetch(`/api/view-report/${type}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                modalBody.innerHTML = `
                    <div style="text-align: center; padding: 60px; color: rgba(248, 113, 113, 1);">
                        <div style="font-size: 64px; margin-bottom: 20px;">❌</div>
                        <div style="font-size: 20px; font-weight: 600; margin-bottom: 12px;">Error Loading Report</div>
                        <div style="color: rgba(148, 163, 184, 1);">${escapeHtml(data.error || "Failed to load report")}</div>
                    </div>
                `;
                modalStats.textContent = 'Error loading report';
                return;
            }

            if (!data.rows || data.rows.length === 0) {
                modalBody.innerHTML = `
                    <div style="text-align: center; padding: 60px; color: rgba(148, 163, 184, 1);">
                        <div style="font-size: 64px; margin-bottom: 20px;">📭</div>
                        <div style="font-size: 20px; font-weight: 600; margin-bottom: 12px; color: rgba(226, 232, 240, 1);">Empty Report</div>
                        <div>This report contains no data</div>
                    </div>
                `;
                modalStats.textContent = 'No entries found';
                return;
            }

            // Helper function to detect and convert URLs to clickable links (but not email domains)
            function makeLinksClickable(text) {
                if (!text) return '';
                const escaped = escapeHtml(text);
                
                // First, protect email addresses by replacing them with placeholders
                const emailRegex = /[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}/g;
                const emailPlaceholders = [];
                let emailIndex = 0;
                let protectedText = escaped.replace(emailRegex, (email) => {
                    const placeholder = `__EMAIL_${emailIndex}__`;
                    emailPlaceholders[emailIndex] = email;
                    emailIndex++;
                    return placeholder;
                });
                
                // Now match URLs: http://, https://, or www. URLs
                const urlRegex = /(https?:\/\/[^\s<>"']+|www\.[^\s<>"']+)/gi;
                protectedText = protectedText.replace(urlRegex, (url) => {
                    let href = url;
                    if (!url.startsWith('http://') && !url.startsWith('https://')) {
                        href = 'https://' + url;
                    }
                    return `<a href="${href}" target="_blank" rel="noopener noreferrer" style="color: #a855f7; text-decoration: underline; word-break: break-all;">${url}</a>`;
                });
                
                // Restore email addresses
                emailPlaceholders.forEach((email, idx) => {
                    protectedText = protectedText.replace(`__EMAIL_${idx}__`, email);
                });
                
                return protectedText;
            }
            
            let html = '<table class="report-table">';
            
            // Header row (first row as header)
            if (data.rows.length > 0) {
                html += "<thead><tr>";
                data.rows[0].forEach((col, colIdx) => {
                    html += `<th style="animation-delay: ${colIdx * 50}ms;">${escapeHtml(col)}</th>`;
                });
                html += "</tr></thead><tbody>";
                
                // Data rows (skip first row if it's the header)
                const startIdx = data.rows.length > 1 ? 1 : 0;
                const rowCount = data.rows.length - startIdx;
                for (let idx = startIdx; idx < data.rows.length; idx++) {
                    html += `<tr style="animation-delay: ${(idx - startIdx) * 50}ms;">`;
                    data.rows[idx].forEach(col => {
                        html += `<td>${makeLinksClickable(col)}</td>`;
                    });
                    html += "</tr>";
                }
                
                modalStats.textContent = `Showing all ${rowCount} entries`;
            }
            
            html += "</tbody></table>";

            modalBody.innerHTML = html;
            document.getElementById("downloadReportBtn").href = `/download/${type}`;
        })
        .catch(e => {
            modalBody.innerHTML = `
                <div style="text-align: center; padding: 60px; color: rgba(248, 113, 113, 1);">
                    <div style="font-size: 64px; margin-bottom: 20px;">⚠️</div>
                    <div style="font-size: 20px; font-weight: 600; margin-bottom: 12px;">Network Error</div>
                    <div style="color: rgba(148, 163, 184, 1);">${escapeHtml(e.message || "Failed to fetch report")}</div>
                </div>
            `;
            modalStats.textContent = 'Network error occurred';
        });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function closeReportModal() {
    document.getElementById("reportModal").style.display = "none";
}

// Load reports when opening Reports page
document.addEventListener("DOMContentLoaded", loadReports);

// ============================================================
// BOT COMPLETION POPUP SYSTEM
// ============================================================
let lastRunStatus = null;
let popupShown = false;

function showSummaryPopup(successCount, failedCount, stockWarnings = []) {
    const modal = document.createElement('div');
    modal.id = 'summaryPopup';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 10000;
        animation: fadeIn 0.3s ease;
    `;
    
    // Build stock warnings HTML if any exist
    let stockWarningsHtml = '';
    if (stockWarnings && stockWarnings.length > 0) {
        stockWarningsHtml = `
            <div style="margin-bottom: 20px; padding: 16px; background: linear-gradient(135deg, rgba(191,161,129,0.15) 0%, rgba(191,161,129,0.08) 100%); border-radius: 12px; border: 1.5px solid rgba(191,161,129,0.4);">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px; color: var(--warning); font-weight: 600;">
                    <span>⚠️</span>
                    <span>Stock Quantity Warnings</span>
                </div>
                ${stockWarnings.map(w => `
                    <div style="padding: 10px; margin-bottom: 8px; background: var(--card); border-radius: 8px; border-left: 3px solid var(--warning); font-size: 0.9em;">
                        <div style="font-weight: 600; color: var(--text); margin-bottom: 4px;">${escapeHtml(w.product_name || 'Unknown Product')}</div>
                        <div style="color: var(--text-muted);">Desired: ${w.desired_qty || 0} | Available: ${w.current_qty || 0}</div>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    modal.innerHTML = `
        <div style="
            background: var(--glass-strong);
            border: 1.5px solid var(--border);
            border-radius: 20px;
            padding: 30px;
            max-width: 520px;
            width: 90%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.45);
            backdrop-filter: blur(16px);
            animation: slideUp 0.35s ease;
        ">
            <div style="text-align: center; margin-bottom: 24px;">
                <div style="font-size: 3em; margin-bottom: 10px;">🎉</div>
                <h2 style="margin: 0; color: var(--text); letter-spacing:0.4px;">Bot Finished!</h2>
                <p style="margin:6px 0 0; color: var(--text-muted);">Here's your run summary</p>
            </div>
            
            <div style="display: flex; gap: 16px; margin-bottom: 24px;">
                <div style="flex: 1; text-align: center; padding: 18px; background: linear-gradient(135deg, rgba(23,133,130,0.18) 0%, rgba(23,133,130,0.1) 100%); border-radius: 14px; border: 1.5px solid rgba(23,133,130,0.35); box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);">
                    <div style="font-size: 2.6em; font-weight: bold; color: var(--success);">${successCount}</div>
                    <div style="color: var(--text-muted); margin-top: 6px; letter-spacing:0.2px;">Success</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 18px; background: linear-gradient(135deg, rgba(214,90,79,0.18) 0%, rgba(214,90,79,0.1) 100%); border-radius: 14px; border: 1.5px solid rgba(214,90,79,0.35); box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);">
                    <div style="font-size: 2.6em; font-weight: bold; color: var(--danger);">${failedCount}</div>
                    <div style="color: var(--text-muted); margin-top: 6px; letter-spacing:0.2px;">Failed</div>
                </div>
            </div>
            
            ${stockWarningsHtml}
            
            <button onclick="closeSummaryPopup(${successCount > 0})" style="
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, var(--blue) 0%, var(--blue-hover) 100%);
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 1.02em;
                font-weight: 700;
                letter-spacing: 0.3px;
                cursor: pointer;
                transition: all 0.25s ease;
                box-shadow: 0 12px 30px rgba(23,133,130,0.35);
            " onmouseover="this.style.transform='translateY(-1px) scale(1.01)'; this.style.boxShadow='0 16px 40px rgba(23,133,130,0.45)';" 
               onmouseout="this.style.transform=''; this.style.boxShadow='0 12px 30px rgba(23,133,130,0.35)';">
                ${successCount > 0 ? 'View Order IDs' : 'Close'}
            </button>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Add animations
    const style = document.createElement('style');
    style.textContent = `
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        @keyframes slideUp {
            from { transform: translateY(30px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
    `;
    document.head.appendChild(style);
}

function showOrderIdsPopup(orderIds) {
    const modal = document.createElement('div');
    modal.id = 'orderIdsPopup';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 10001;
        animation: fadeIn 0.3s ease;
    `;
    
    const orderListHtml = orderIds.map((id, idx) => 
        `<div style="padding: 12px; background: var(--bg-secondary); border-radius: 8px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: 600; color: var(--text-primary);">${idx + 1}. ${id}</span>
            <button onclick="copyToClipboard('${id}')" style="padding: 6px 12px; background: var(--primary); color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 0.85em;">Copy</button>
        </div>`
    ).join('');
    
    modal.innerHTML = `
        <div style="
            background: var(--bg-primary);
            border-radius: 15px;
            padding: 30px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            animation: slideUp 0.3s ease;
        ">
            <div style="text-align: center; margin-bottom: 25px;">
                <div style="font-size: 2.5em; margin-bottom: 10px;">📋</div>
                <h2 style="margin: 0; color: var(--text-primary);">Successful Order IDs</h2>
                <div style="color: var(--text-muted); margin-top: 5px;">Total: ${orderIds.length} orders</div>
            </div>
            
            <div style="margin-bottom: 20px;">
                ${orderListHtml}
            </div>
            
            <button onclick="copyAllOrderIds(${JSON.stringify(orderIds).replace(/"/g, '&quot;')})" style="
                width: 100%;
                padding: 12px;
                background: var(--success);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 1em;
                font-weight: 600;
                cursor: pointer;
                margin-bottom: 10px;
            ">Copy All Order IDs</button>
            
            <button onclick="closeOrderIdsPopup()" style="
                width: 100%;
                padding: 12px;
                background: var(--text-muted);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 1em;
                font-weight: 600;
                cursor: pointer;
            ">Close</button>
        </div>
    `;
    
    document.body.appendChild(modal);
}

function closeSummaryPopup(showOrderIds) {
    const modal = document.getElementById('summaryPopup');
    if (modal) {
        modal.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => modal.remove(), 300);
    }
    
    if (showOrderIds) {
        setTimeout(() => {
            safeFetch('/api/last-run-results')
                .then(r => r.json())
                .then(data => {
                    console.log('Order IDs data:', data);
                    if (data.order_ids && data.order_ids.length > 0) {
                        showOrderIdsPopup(data.order_ids);
                    } else {
                        alert('No order IDs found in results');
                    }
                })
                .catch(e => {
                    if (!isConnectionError(e)) {
                        console.error('Error fetching order IDs:', e);
                    }
                    if (!serverOffline) {
                        alert('Error fetching order IDs: ' + (e.message || 'Unknown error'));
                    }
                });
        }, 300);
    }
}

function closeOrderIdsPopup() {
    const modal = document.getElementById('orderIdsPopup');
    if (modal) {
        modal.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => modal.remove(), 300);
    }
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Order ID copied to clipboard!');
    }).catch(() => {
        // Fallback
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        alert('Order ID copied to clipboard!');
    });
}

function copyAllOrderIds(orderIds) {
    const text = orderIds.join('\\n');
    navigator.clipboard.writeText(text).then(() => {
        alert('All Order IDs copied to clipboard!');
    }).catch(() => {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        alert('All Order IDs copied to clipboard!');
    });
}

// Poll for bot completion
function checkBotCompletion() {
    if (serverOffline) return; // Skip polling when offline
    safeFetch('/check-status')
        .then(r => r.json())
        .then(data => {
            const wasRunning = lastRunStatus === true;
            const isRunning = data.running === true;
            lastRunStatus = isRunning;
            
            // Bot just finished
            if (wasRunning && !isRunning && !popupShown) {
                popupShown = true;
                console.log('Bot finished, fetching results...');
                // Reduced delay to 500ms for faster popup display
                setTimeout(() => {
                    safeFetch('/api/last-run-results')
                        .then(r => {
                            if (!r.ok) {
                                throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                            }
                            return r.json();
                        })
                        .then(results => {
                            console.log('Results received:', results);
                            const successCount = results.success_count || 0;
                            const failedCount = results.failed_count || 0;
                            const orderIds = results.order_ids || [];
                            const stockWarnings = results.stock_warnings || [];
                            console.log(`Summary: ${successCount} success, ${failedCount} failed, ${orderIds.length} order IDs, ${stockWarnings.length} stock warnings`);
                            showSummaryPopup(successCount, failedCount, stockWarnings);
                        })
                        .catch(e => {
                            if (!isConnectionError(e)) {
                                console.error('Error fetching results:', e);
                            }
                            // Retry once after a short delay if first attempt fails
                            setTimeout(() => {
                                safeFetch('/api/last-run-results')
                                    .then(r => r.json())
                                    .then(results => {
                                        const successCount = results.success_count || 0;
                                        const failedCount = results.failed_count || 0;
                                        const stockWarnings = results.stock_warnings || [];
                                        showSummaryPopup(successCount, failedCount, stockWarnings);
                                    })
                                    .catch(() => {
                                        // Still show popup with 0/0 if both attempts fail
                                        showSummaryPopup(0, 0, []);
                                    });
                            }, 1000);
                        });
                }, 500); // Reduced from 3000ms to 500ms for faster popup
            }
            
            // Reset popup flag when bot starts again
            if (isRunning) {
                popupShown = false;
            }
        })
        .catch(e => {
            if (!isConnectionError(e)) {
                console.error('Error checking bot status:', e);
            }
        });
}

// Check every 2 seconds
setInterval(checkBotCompletion, 2000);

// ============================================================
// STOP ALL WORKERS ACTION
// ============================================================
function stopAllWorkers() {
    // Show modal immediately for better UX
    showStopWorkersModal();
    
    // Verify bot status in background (non-blocking)
    fetch('/check-status')
        .then(r => r.json())
        .then(status => {
            if (!status.running) {
                // If bot is not running, close modal and show error
                closeStopWorkersModal();
                showToast('error', 'Bot is not running.');
            }
            // If running, modal stays open for user confirmation
        })
        .catch(() => {
            // On error, still allow user to try stopping (might be network issue)
            // Modal stays open for user to decide
        });
}

function showStopWorkersModal() {
    const modal = document.getElementById('stopWorkersModal');
    if (modal) {
        modal.style.display = 'flex'; // Use flex to center content properly
    }
}

function closeStopWorkersModal() {
    const modal = document.getElementById('stopWorkersModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function confirmStopWorkers() {
    closeStopWorkersModal();
    
    fetch('/api/stop-workers', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({all: true})
    })
        .then(async r => {
            // Gracefully handle non-JSON (e.g., auth redirect HTML)
            const ct = r.headers.get('content-type') || '';
            if (!ct.includes('application/json')) {
                throw new Error('Non-JSON response (are you logged in?)');
            }
            const data = await r.json();
            if (!r.ok) {
                throw new Error(data.error || 'Stop failed');
            }
            return data;
        })
        .then(data => {
            if (data.success) {
                showToast('success', `Stopped workers: ${data.stopped}`);
            } else {
                showToast('error', `Stop failed: ${data.error || 'Unknown error'}`);
            }
        })
        .catch(e => showToast('error', `Stop failed: ${e.message}`));
}

// ============================================================
// IMAP CONFIGURATION FUNCTIONS
// ============================================================
let originalImapConfig = {};

function loadImapConfig() {
    fetch('/api/get-imap-config')
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                showImapStatus('Error loading config: ' + data.error, 'error');
                return;
            }
            
            // Store original config for comparison
            originalImapConfig = {
                host: data.host || '',
                port: data.port || '',
                email: data.email || '',
                password: data.password || '',
                mailbox: data.mailbox || ''
            };
            
            // Populate form fields
            document.getElementById('imap_host').value = originalImapConfig.host;
            document.getElementById('imap_port').value = originalImapConfig.port;
            document.getElementById('imap_email').value = originalImapConfig.email;
            document.getElementById('imap_password').value = originalImapConfig.password;
            document.getElementById('imap_mailbox').value = originalImapConfig.mailbox;
        })
        .catch(e => {
            console.error('Error loading IMAP config:', e);
            showImapStatus('Failed to load IMAP configuration', 'error');
        });
}

function saveImapConfig(event) {
    event.preventDefault();
    
    // Validate port before proceeding
    const portValue = document.getElementById('imap_port').value.trim();
    const portNum = parseInt(portValue);
    if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
        showImapStatus('❌ Error: Port must be a valid number between 1 and 65535', 'error');
        return;
    }
    
    const newConfig = {
        host: document.getElementById('imap_host').value.trim(),
        port: portNum,
        email: document.getElementById('imap_email').value.trim(),
        password: document.getElementById('imap_password').value.trim(),
        mailbox: document.getElementById('imap_mailbox').value.trim()
    };
    
    // Validate all required fields
    if (!newConfig.host || !newConfig.email || !newConfig.password || !newConfig.mailbox) {
        showImapStatus('❌ Error: All fields are required', 'error');
        return;
    }
    
    // Check if there are any changes
    let hasChanges = false;
    const changes = [];
    
    const fields = [
        { key: 'host', label: 'IMAP Host' },
        { key: 'port', label: 'Port' },
        { key: 'email', label: 'Email' },
        { key: 'password', label: 'Password' },
        { key: 'mailbox', label: 'Mailbox' }
    ];
    
    fields.forEach(field => {
        const oldValue = String(originalImapConfig[field.key] || '');
        const newValue = String(newConfig[field.key] || '');
        
        if (oldValue !== newValue) {
            hasChanges = true;
            changes.push({
                label: field.label,
                old: oldValue,
                new: newValue,
                isPassword: field.key === 'password'
            });
        }
    });
    
    if (!hasChanges) {
        showImapStatus('ℹ️ No changes detected', 'info');
        return;
    }
    
    // Store new config for confirmation
    window.pendingImapConfig = newConfig;
    
    // Show confirmation modal with changes
    showImapConfirmModal(changes);
}

function showImapConfirmModal(changes) {
    const modal = document.getElementById('imapConfirmModal');
    const changesList = document.getElementById('imapChangesList');
    
    let html = '<div style="display: flex; flex-direction: column; gap: 15px;">';
    
    changes.forEach(change => {
        const oldDisplay = change.isPassword ? '••••••••' : (change.old || '<em>empty</em>');
        const newDisplay = change.isPassword ? '••••••••' : (change.new || '<em>empty</em>');
        
        html += `
            <div style="padding: 12px; background: var(--card); border-radius: 6px; border-left: 3px solid var(--blue);">
                <div style="font-weight: 600; margin-bottom: 8px; color: var(--blue);">${change.label}</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.9em;">
                    <div>
                        <div style="color: var(--text-muted); margin-bottom: 4px;">Old Value:</div>
                        <div style="color: var(--danger); word-break: break-all;">${oldDisplay}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-muted); margin-bottom: 4px;">New Value:</div>
                        <div style="color: var(--success); word-break: break-all;">${newDisplay}</div>
                    </div>
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    changesList.innerHTML = html;
    
    modal.style.display = 'block';
}

function closeImapConfirmModal() {
    document.getElementById('imapConfirmModal').style.display = 'none';
    window.pendingImapConfig = null;
}

function confirmImapSave() {
    // Store config before closing modal (to prevent race condition)
    const configToSave = window.pendingImapConfig;
    
    if (!configToSave) {
        closeImapConfirmModal();
        showImapStatus('❌ Error: No configuration data to save', 'error');
        return;
    }
    
    const statusEl = document.getElementById('imap-status');
    statusEl.style.display = 'block';
    statusEl.textContent = 'Saving...';
    statusEl.style.background = 'var(--card)';
    statusEl.style.color = 'var(--text)';
    
    closeImapConfirmModal();
    
    // Ensure all fields are present and valid
    const validatedConfig = {
        host: String(configToSave.host || '').trim(),
        port: parseInt(configToSave.port) || 993,
        email: String(configToSave.email || '').trim(),
        password: String(configToSave.password || '').trim(),
        mailbox: String(configToSave.mailbox || '').trim()
    };
    
    // Validate before sending
    if (!validatedConfig.host || !validatedConfig.email || !validatedConfig.password || !validatedConfig.mailbox) {
        showImapStatus('❌ Error: All fields are required', 'error');
        return;
    }
    
    if (isNaN(validatedConfig.port) || validatedConfig.port < 1 || validatedConfig.port > 65535) {
        showImapStatus('❌ Error: Port must be between 1 and 65535', 'error');
        return;
    }
    
    console.log('Sending IMAP config:', {...validatedConfig, password: '***'});
    
    fetch('/api/save-imap-config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify(validatedConfig)
    })
        .then(r => {
            if (!r.ok) {
                return r.json().then(err => {
                    throw new Error(err.error || `HTTP ${r.status}: ${r.statusText}`);
                });
            }
            return r.json();
        })
        .then(data => {
            if (data.success) {
                // Update original config to new values
                originalImapConfig = { ...validatedConfig };
                showImapStatus('✅ IMAP configuration saved successfully!', 'success');
            } else {
                showImapStatus('❌ Error: ' + (data.error || 'Failed to save'), 'error');
            }
            window.pendingImapConfig = null;
        })
        .catch(e => {
            console.error('Error saving IMAP config:', e);
            showImapStatus('❌ Error: ' + (e.message || 'Failed to save IMAP configuration'), 'error');
            window.pendingImapConfig = null;
        });
}

function showImapStatus(message, type) {
    const statusEl = document.getElementById('imap-status');
    statusEl.textContent = message;
    statusEl.style.display = 'block';
    
    if (type === 'success') {
        statusEl.style.background = 'linear-gradient(135deg, var(--success)20 0%, var(--success)30 100%)';
        statusEl.style.border = '2px solid var(--success)50';
        statusEl.style.color = 'var(--success)';
    } else if (type === 'info') {
        statusEl.style.background = 'linear-gradient(135deg, var(--blue)20 0%, var(--blue)30 100%)';
        statusEl.style.border = '2px solid var(--blue)50';
        statusEl.style.color = 'var(--blue)';
    } else {
        statusEl.style.background = 'linear-gradient(135deg, var(--danger)20 0%, var(--danger)30 100%)';
        statusEl.style.border = '2px solid var(--danger)50';
        statusEl.style.color = 'var(--danger)';
    }
    
    // Auto-hide after 5 seconds
    setTimeout(() => {
        statusEl.style.display = 'none';
    }, 5000);
}

</script>

</body>
</html>
"""



# ============================================================
# FILE SYSTEM PATHS (UNIVERSAL)
# ============================================================
ROOT = os.path.dirname(os.path.abspath(__file__))
# FIX: Paths are in the PARENT directory (../) according to your directory structure
FILES_DIR = os.path.join(ROOT, "../files")
DOWNLOAD_DIR = os.path.join(ROOT, "../download")
LOGS_DIR = os.path.join(ROOT, "../logs")

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

MAIL_FILE = os.path.join(FILES_DIR, "mail.txt")
COUPON_FILE = os.path.join(FILES_DIR, "coupon.txt")

SUCCESS_CSV = os.path.join(DOWNLOAD_DIR, "success.csv")
FAILURE_CSV = os.path.join(DOWNLOAD_DIR, "failure.csv")
USED_MAIL_FILE = os.path.join(DOWNLOAD_DIR, "success_coupon.csv")
USED_COUPON_FILE = os.path.join(DOWNLOAD_DIR, "failed_coupon.csv")
FAILED_COUPON = os.path.join(DOWNLOAD_DIR, "failed_coupon.csv")
STOCK_WARNING_FILE = os.path.join(DOWNLOAD_DIR, "stock_warning.json")
REMOVED_MAIL_FILE = os.path.join(DOWNLOAD_DIR, "removed_mails.txt")

# Ensure removed_mails.txt exists (create empty file if it doesn't exist)
if not os.path.exists(REMOVED_MAIL_FILE):
    try:
        with open(REMOVED_MAIL_FILE, 'w', encoding='utf-8') as f:
            pass  # Create empty file
    except Exception:
        pass


# ============================================================
# BOT STATE
# ============================================================
RUNNING = False
LOGS = []
LAST_STATS = {
    "total": 0,
    "success": 0,
    "failure": 0,
    "mails_left": 0,
    "coupons_left": 0
}
CURRENT_RUNNER = None
LAST_RUN_RESULTS = {
    "success_count": 0,
    "failed_count": 0,
    "order_ids": [],
    "stock_warnings": []
}
# Shared log file used by main.py BotLogger (latest.log)
LOG_FILE = os.path.join(LOGS_DIR, "latest.log")
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def log(msg):
    LOGS.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    print(msg)
    sys.stdout.flush()
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

# Custom stdout/stderr capture for real-time logs
class LogCapture:
    def __init__(self, original_stream):
        self.original_stream = original_stream
        self.buffer = io.StringIO()
    
    def write(self, text):
        if text.strip():  # Only log non-empty lines
            timestamp = datetime.now().strftime('%H:%M:%S')
            log_entry = f"[{timestamp}] {text.strip()}"
            LOGS.append(log_entry)
            # Keep only last 1000 log entries to prevent memory issues
            if len(LOGS) > 1000:
                LOGS.pop(0)
        self.original_stream.write(text)
        self.original_stream.flush()
    
    
    def flush(self):
        self.original_stream.flush()
    
    def __getattr__(self, name):
        return getattr(self.original_stream, name)

# Pass the log function to the mock runner
if 'ConnectRunner' in globals() and ConnectRunner.__module__ == __name__:
    log_func = log


# ============================================================
# BACKGROUND RUNNER
# ============================================================
def background_run(config):
    global RUNNING, LAST_RUN_RESULTS, CURRENT_RUNNER
    RUNNING = True
    LOGS.clear()
    # fresh log file for run
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        open(LOG_FILE, "w", encoding="utf-8").close()
    except Exception:
        pass
    log("🔥 Bot started")

    try:
        # This will now work because start_job creates the config dict
        # with the correct keys ('max_parallel' and 'toggle_retry')
        print(f"[APP DEBUG STEP 3] Creating ConnectRunner with config:")
        print(f"  - use_coupon in config: {config.get('use_coupon')}")
        print(f"  - use_coupon type: {type(config.get('use_coupon')).__name__}")
        print(f"  - Full config keys: {list(config.keys())}\n")
        # Clear old stock warnings at start of new run
        try:
            if os.path.exists(STOCK_WARNING_FILE):
                with open(STOCK_WARNING_FILE, 'w', encoding='utf-8') as f:
                    f.write('[]')
        except Exception as e:
            log(f"⚠️ Error clearing stock warnings: {e}")
        
        runner = ConnectRunner(**config)
        CURRENT_RUNNER = runner
        
        # run_all() now returns results directly
        # #region agent log
        import json
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cursor")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "debug.log")
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"pre-run","hypothesisId":"A","location":"app.py:7045","message":"Before run_all() call","data":{"mail_file_exists":os.path.exists(MAIL_FILE)},"timestamp":int(time.time()*1000)}) + "\n")
                if os.path.exists(MAIL_FILE):
                    with open(MAIL_FILE, 'r', encoding='utf-8') as mf:
                        mails_before = [l.strip() for l in mf if l.strip()]
                        f.write(json.dumps({"sessionId":"debug-session","runId":"pre-run","hypothesisId":"A","location":"app.py:7045","message":"Mails before run","data":{"mail_count":len(mails_before),"mails":mails_before[:5]},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        results = runner.run_all()
        # #region agent log
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"post-run","hypothesisId":"A","location":"app.py:7046","message":"After run_all() call","data":{"results":results,"results_type":type(results).__name__},"timestamp":int(time.time()*1000)}) + "\n")
                if os.path.exists(MAIL_FILE):
                    with open(MAIL_FILE, 'r', encoding='utf-8') as mf:
                        mails_after = [l.strip() for l in mf if l.strip()]
                        f.write(json.dumps({"sessionId":"debug-session","runId":"post-run","hypothesisId":"A","location":"app.py:7046","message":"Mails after run","data":{"mail_count":len(mails_after),"mails":mails_after[:5]},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        # Store results for popup
        if results:
            # Read stock warnings if file exists
            stock_warnings = []
            try:
                if os.path.exists(STOCK_WARNING_FILE):
                    import json
                    with open(STOCK_WARNING_FILE, 'r', encoding='utf-8') as f:
                        warning_data = json.load(f)
                        if isinstance(warning_data, dict):
                            stock_warnings = [warning_data]
                        elif isinstance(warning_data, list):
                            stock_warnings = warning_data
            except Exception as e:
                log(f"⚠️ Error reading stock warnings: {e}")
            
            LAST_RUN_RESULTS = {
                "success_count": results.get("success_count", 0),
                "failed_count": results.get("failed_count", 0),
                "order_ids": results.get("order_ids", []),
                "stock_warnings": stock_warnings
            }
            # #region agent log
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"post-run","hypothesisId":"B","location":"app.py:7063","message":"LAST_RUN_RESULTS set from results","data":{"last_run_results":LAST_RUN_RESULTS,"results_keys":list(results.keys()) if results else []},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            log(f"📊 Results: {LAST_RUN_RESULTS['success_count']} success, {LAST_RUN_RESULTS['failed_count']} failed, {len(LAST_RUN_RESULTS['order_ids'])} order IDs, {len(stock_warnings)} stock warnings")
        else:
            # Fallback: read from CSV files if run_all() didn't return results
            LAST_RUN_RESULTS = {
                "success_count": 0,
                "failed_count": 0,
                "order_ids": [],
                "stock_warnings": []
            }
            log("⚠️ No results returned from run_all(), using fallback CSV reading")
            # Fallback CSV reading (keep existing logic as backup)
            try:
                import csv
                success_count = 0
                failed_count = 0
                order_ids = []
                
                if os.path.exists(SUCCESS_CSV):
                    # #region agent log
                    try:
                        with open(log_path, 'a', encoding='utf-8') as logf:
                            logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7086","message":"Reading SUCCESS_CSV","data":{"file_exists":True},"timestamp":int(time.time()*1000)}) + "\n")
                    except: pass
                    # #endregion
                    with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                        try:
                            reader = csv.DictReader(f)
                            rows = list(reader)
                            success_count = len(rows)
                            # #region agent log
                            try:
                                with open(log_path, 'a', encoding='utf-8') as logf:
                                    logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7091","message":"SUCCESS_CSV rows counted","data":{"row_count":success_count,"rows":rows[:3]},"timestamp":int(time.time()*1000)}) + "\n")
                            except: pass
                            # #endregion
                            for row in rows:
                                order_id = (row.get('order_id', '') or row.get('Order ID', '') or 
                                           row.get('orderId', '') or row.get('ORDER_ID', '')).strip()
                                if order_id and (order_id.startswith('OD') or order_id.startswith('od')):
                                    order_ids.append(order_id)
                        except Exception as e:
                            # #region agent log
                            try:
                                with open(log_path, 'a', encoding='utf-8') as logf:
                                    logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7097","message":"SUCCESS_CSV DictReader failed, using fallback","data":{"error":str(e)},"timestamp":int(time.time()*1000)}) + "\n")
                            except: pass
                            # #endregion
                            f.seek(0)
                            lines = f.readlines()
                            success_count = len(lines) - 1 if len(lines) > 1 else 0
                            # #region agent log
                            try:
                                with open(log_path, 'a', encoding='utf-8') as logf:
                                    logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7100","message":"SUCCESS_CSV fallback count","data":{"line_count":len(lines),"success_count":success_count},"timestamp":int(time.time()*1000)}) + "\n")
                            except: pass
                            # #endregion
                            if len(lines) > 1:
                                for line in lines[1:]:
                                    parts = line.strip().split(',')
                                    if len(parts) > 3:
                                        order_id = parts[3].strip().strip('"').strip("'")
                                        if order_id and (order_id.startswith('OD') or order_id.startswith('od')):
                                            order_ids.append(order_id)
                
                if os.path.exists(FAILURE_CSV):
                    # #region agent log
                    try:
                        with open(log_path, 'a', encoding='utf-8') as logf:
                            logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7109","message":"Reading FAILURE_CSV","data":{"file_exists":True},"timestamp":int(time.time()*1000)}) + "\n")
                    except: pass
                    # #endregion
                    with open(FAILURE_CSV, 'r', encoding='utf-8') as f:
                        try:
                            reader = csv.DictReader(f)
                            failed_rows = list(reader)
                            failed_count = len(failed_rows)
                            # #region agent log
                            try:
                                with open(log_path, 'a', encoding='utf-8') as logf:
                                    logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7113","message":"FAILURE_CSV rows counted","data":{"row_count":failed_count,"rows":failed_rows[:3]},"timestamp":int(time.time()*1000)}) + "\n")
                            except: pass
                            # #endregion
                        except Exception as e:
                            # #region agent log
                            try:
                                with open(log_path, 'a', encoding='utf-8') as logf:
                                    logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7114","message":"FAILURE_CSV DictReader failed, using fallback","data":{"error":str(e)},"timestamp":int(time.time()*1000)}) + "\n")
                            except: pass
                            # #endregion
                            lines = f.readlines()
                            failed_count = len(lines) - 1 if len(lines) > 1 else 0
                            # #region agent log
                            try:
                                with open(log_path, 'a', encoding='utf-8') as logf:
                                    logf.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7116","message":"FAILURE_CSV fallback count","data":{"line_count":len(lines),"failed_count":failed_count},"timestamp":int(time.time()*1000)}) + "\n")
                            except: pass
                            # #endregion
                
                # Read stock warnings if file exists
                stock_warnings = []
                try:
                    if os.path.exists(STOCK_WARNING_FILE):
                        import json
                        with open(STOCK_WARNING_FILE, 'r', encoding='utf-8') as f:
                            warning_data = json.load(f)
                            if isinstance(warning_data, dict):
                                stock_warnings = [warning_data]
                            elif isinstance(warning_data, list):
                                stock_warnings = warning_data
                except Exception as e:
                    log(f"⚠️ Error reading stock warnings: {e}")
                
                LAST_RUN_RESULTS = {
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "order_ids": order_ids,
                    "stock_warnings": stock_warnings
                }
                # #region agent log
                try:
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"fallback","hypothesisId":"C","location":"app.py:7132","message":"LAST_RUN_RESULTS set from CSV fallback","data":{"last_run_results":LAST_RUN_RESULTS},"timestamp":int(time.time()*1000)}) + "\n")
                except: pass
                # #endregion
                log(f"📊 Fallback Results: {success_count} success, {failed_count} failed, {len(order_ids)} order IDs, {len(stock_warnings)} stock warnings")
            except Exception as e:
                log(f"⚠️ Error in fallback CSV reading: {e}")

    except Exception as e:
        log(f"❌ ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        # Set empty results on error
        LAST_RUN_RESULTS = {
            "success_count": 0,
            "failed_count": 0,
            "order_ids": [],
            "stock_warnings": []
        }

    RUNNING = False
    CURRENT_RUNNER = None
    log("✔ Bot finished")



# ============================================================
# SCREENSHOT SERVING (PUBLIC - No auth required)
# ============================================================

@app.route("/screenshots/<filename>")
def serve_screenshot(filename):
    """Serve screenshots from the screenshots directory"""
    try:
        # Get screenshots directory (same as main.py uses)
        screenshots_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "screenshots"))
        screenshot_path = os.path.join(screenshots_dir, filename)
        
        # Security: Ensure file is within screenshots directory (prevent path traversal)
        if not os.path.abspath(screenshot_path).startswith(os.path.abspath(screenshots_dir)):
            return "Forbidden", 403
        
        # Check if file exists
        if not os.path.exists(screenshot_path):
            return "Not Found", 404
        
        # Serve the image file
        return send_file(screenshot_path, mimetype='image/png')
    except Exception as e:
        print(f"Error serving screenshot {filename}: {e}")
        return "Error", 500


def get_screenshot_base_url():
    """
    Get the base URL for serving screenshots.
    Supports custom domain via SCREENSHOT_DOMAIN env var.
    Supports HTTPS via SCREENSHOT_HTTPS=true or if domain starts with https://
    Examples:
    - SCREENSHOT_DOMAIN=husan.shop -> https://husan.shop/screenshots (if HTTPS enabled)
    - SCREENSHOT_DOMAIN=husan.shop:8080 -> https://husan.shop:8080/screenshots
    - SCREENSHOT_DOMAIN=https://husan.shop -> https://husan.shop/screenshots
    - No env var -> http://localhost:5000/screenshots
    """
    custom_domain = os.environ.get("SCREENSHOT_DOMAIN", "").strip()
    use_https = os.environ.get("SCREENSHOT_HTTPS", "false").lower() == "true"
    
    if custom_domain:
        # Check if domain already includes protocol
        if custom_domain.startswith("http://") or custom_domain.startswith("https://"):
            # Full URL provided, extract domain and port
            from urllib.parse import urlparse
            parsed = urlparse(custom_domain)
            domain = parsed.netloc or parsed.path
            if not domain:
                domain = custom_domain.replace("http://", "").replace("https://", "")
            protocol = "https" if custom_domain.startswith("https://") else "http"
            # If no port in domain, add default port
            if ":" not in domain:
                port = os.environ.get("FLASK_PORT", "5000")
                domain_with_port = f"{domain}:{port}" if port != "443" and protocol == "https" else domain
            else:
                domain_with_port = domain
            return f"{protocol}://{domain_with_port}/screenshots"
        else:
            # Domain only, determine protocol
            protocol = "https" if use_https else "http"
            # If domain includes port, use it; otherwise default to 5000 (or 443 for HTTPS)
            if ":" in custom_domain:
                domain_with_port = custom_domain
            else:
                if use_https:
                    # HTTPS typically uses port 443 (no need to specify)
                    domain_with_port = custom_domain
                else:
                    port = os.environ.get("FLASK_PORT", "5000")
                    domain_with_port = f"{custom_domain}:{port}"
            return f"{protocol}://{domain_with_port}/screenshots"
    else:
        # Default to localhost
        port = os.environ.get("FLASK_PORT", "5000")
        return f"http://localhost:{port}/screenshots"


# ============================================================
# ROUTES (PROTECTED)
# ============================================================

@app.route("/")
@login_required
def index():
    return render_template_string(MAIN_TEMPLATE,
        success_exists=os.path.exists(SUCCESS_CSV),
        fail_exists=os.path.exists(FAILURE_CSV),
        used_coupon_exists=os.path.exists(USED_COUPON_FILE),
        used_mail_exists=os.path.exists(USED_MAIL_FILE),
        local_ip=get_local_ip(),
        screenshot_domain=os.environ.get("SCREENSHOT_DOMAIN", "")
    )


@app.route("/start", methods=["POST"])
@login_required
def start_job():
    global RUNNING
    if RUNNING:
        return jsonify({"success": False, "message": "Bot already running"})

    # Clean logs directory before starting to keep only latest run
    try:
        if os.path.exists(LOGS_DIR):
            for fname in os.listdir(LOGS_DIR):
                try:
                    os.remove(os.path.join(LOGS_DIR, fname))
                except Exception:
                    pass
        else:
            os.makedirs(LOGS_DIR, exist_ok=True)
        # Initialize latest log file (latest.log)
        open(LOG_FILE, "w", encoding="utf-8").close()
    except Exception as e:
        print(f"⚠️ Could not clean logs dir: {e}")

    # Read form data
    first_name = request.form.get("first_name", "").strip()
    surname = request.form.get("surname", "").strip()
    use_coupon = request.form.get("use_coupon")
    print(f"\n{'='*60}")
    print(f"[APP DEBUG STEP 1] Raw form data received:")
    print(f"  - use_coupon (raw): '{use_coupon}'")
    print(f"  - use_coupon type: {type(use_coupon).__name__}")
    print(f"  - All form keys: {list(request.form.keys())}")
    print(f"{'='*60}\n")
    
    # Validate required fields
    if not first_name:
        return jsonify({"success": False, "message": "First name is required!"})
    if not use_coupon:
        return jsonify({"success": False, "message": "Please select whether to use coupon or not!"})
    
    # Combine first name and surname
    full_name = f"{first_name} {surname}".strip() if surname else first_name
    
    # Convert string to boolean
    use_coupon_bool = use_coupon == "true"
    print(f"[APP DEBUG STEP 2] Converting to boolean:")
    print(f"  - use_coupon == 'true': {use_coupon_bool}")
    print(f"  - Result type: {type(use_coupon_bool).__name__}")
    print(f"  - Result value: {use_coupon_bool}\n")
    
    # Resource availability checks
    def count_lines(path):
        try:
            if not os.path.exists(path):
                return 0
            with open(path, "r", encoding="utf-8") as f:
                return len([ln for ln in f if ln.strip()])
        except Exception:
            return 0

    mail_count = count_lines(MAIL_FILE)
    coupon_count = count_lines(COUPON_FILE)
    order_limit = int(request.form.get("limit"))

    if mail_count < order_limit:
        deficit = order_limit - mail_count
        return jsonify({
            "success": False,
            "message": f"Mails are not enough. Add {deficit} more. Currently have {mail_count}."
        })

    if use_coupon_bool and coupon_count < order_limit:
        deficit = order_limit - coupon_count
        return jsonify({
            "success": False,
            "message": f"Coupons are not enough. Add {deficit} more. Currently have {coupon_count}."
        })
    
    cfg = {
        "name": full_name,
        "phone": request.form.get("phone"),
        "pincode": request.form.get("pincode"),
        "address1": request.form.get("address1"),
        "address2": request.form.get("address2"),
        "count_limit": int(request.form.get("limit")),
        "max_price": int(request.form.get("max_price")),
        # FIX: Renamed 'parallel' to 'max_parallel' to match connect.py
        "max_parallel": int(request.form.get("parallel")),
        # FIX: Renamed 'retry' to 'toggle_retry' to match connect.py
        "toggle_retry": request.form.get("retry") == "on",
        "allow_less_qty": request.form.get("allow_less_qty") == "on",
        "remove_mail_on_success": request.form.get("remove_mail_on_success") == "on",
        "deal_keyword": request.form.get("deal_keyword"),
        "screenshot_domain": request.form.get("screenshot_domain"),
        "use_coupon": use_coupon_bool,
        "auto_apply_deals": request.form.get("auto_apply_deals") == "on",  # New: Auto apply deals toggle
        "products_dict": {
            u: int(q)
            for u, q in zip(
                request.form.getlist("product_url[]"),
                request.form.getlist("product_qty[]")
            ) if u.strip()
        }
    }

    threading.Thread(target=background_run, args=(cfg,)).start()

    return jsonify({"success": True, "message": "Bot started!"})


@app.route("/upload-mail", methods=["POST"])
@login_required
def upload_mail():
    request.files["file"].save(MAIL_FILE)
    return redirect("/?page=accounts")


@app.route("/upload-coupon", methods=["POST"])
@login_required
def upload_coupon():
    request.files["file"].save(COUPON_FILE)
    return redirect("/?page=accounts")


@app.route("/api/get-file/<file_type>")
@login_required
def get_file(file_type):
    """Get file content for editing"""
    files = {
        "mail": MAIL_FILE,
        "coupon": COUPON_FILE,
    }
    if file_type not in files:
        return jsonify({"error": "Invalid file type"}), 400
    
    file_path = files[file_type]
    if not os.path.exists(file_path):
        return jsonify({"content": "", "message": "File does not exist"})
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content, "message": "File loaded successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/save-file/<file_type>", methods=["POST"])
@login_required
def save_file(file_type):
    """Save file content after editing"""
    files = {
        "mail": MAIL_FILE,
        "coupon": COUPON_FILE,
    }
    if file_type not in files:
        return jsonify({"error": "Invalid file type"}), 400
    
    data = request.get_json()
    content = data.get("content", "")
    
    file_path = files[file_type]
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"success": True, "message": "File saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/get-imap-config")
@login_required
def get_imap_config():
    """Get IMAP configuration from imap_config.json"""
    import json
    config_path = os.path.join(ROOT, "..", "imap_config.json")
    
    default_config = {
        "host": "imappro.zoho.in",
        "port": 993,
        "email": "work@clyro.sbs",
        "password": "7Kak6MZyimzB",
        "mailbox": "Notification"
    }
    
    if not os.path.exists(config_path):
        # Create default config file
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
            return jsonify(default_config)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Ensure config is a dictionary (not None or other type)
            if not isinstance(config, dict):
                config = default_config.copy()
            # Ensure all keys exist
            for key in default_config:
                if key not in config:
                    config[key] = default_config[key]
            return jsonify(config)
    except json.JSONDecodeError:
        # If JSON is corrupted, return default
        return jsonify(default_config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/save-imap-config", methods=["POST"])
@login_required
def save_imap_config():
    """Save IMAP configuration to imap_config.json"""
    import json
    config_path = os.path.join(ROOT, "..", "imap_config.json")
    
    try:
        # Try to get JSON data, force=True to handle cases where Content-Type might not be set correctly
        data = request.get_json(force=True, silent=True)
        
        # Validate data is not None
        if data is None:
            # Try to get raw data for debugging
            raw_data = request.get_data(as_text=True)
            return jsonify({
                "success": False, 
                "error": f"No data received. Raw data: {raw_data[:100] if raw_data else 'empty'}"
            }), 400
        
        # Validate required fields
        required_fields = ["host", "port", "email", "password", "mailbox"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400
        
        # Validate port is a number
        try:
            # Handle both string and integer port values
            port = int(data["port"]) if isinstance(data["port"], (int, str)) else None
            if port is None or port < 1 or port > 65535:
                return jsonify({"success": False, "error": "Port must be a valid number between 1 and 65535"}), 400
        except (ValueError, TypeError) as e:
            return jsonify({"success": False, "error": f"Port must be a valid number: {str(e)}"}), 400
        
        # Create config object
        config = {
            "host": str(data["host"]).strip(),
            "port": port,
            "email": str(data["email"]).strip(),
            "password": str(data["password"]).strip(),
            "mailbox": str(data["mailbox"]).strip()
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        # Save to file
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        
        return jsonify({"success": True, "message": "IMAP configuration saved successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/shorten-url", methods=["POST"])
@login_required
def shorten_url_proxy():
    """Proxy endpoint to shorten URLs (avoids CORS issues)"""
    try:
        data = request.get_json(force=True, silent=True)
        if not data or "urls" not in data:
            return jsonify({"error": "Missing 'urls' in request body"}), 400
        
        urls = data["urls"]
        if not isinstance(urls, list):
            return jsonify({"error": "'urls' must be a list"}), 400
        
        print(f"[URL SHORTENER PROXY] Received request to shorten {len(urls)} URL(s)")
        
        # Forward request to the shortening API
        api_url = "http://127.0.0.1:8000/shorten"
        payload = {"urls": urls}
        
        print(f"[URL SHORTENER PROXY] Forwarding to: {api_url}")
        print(f"[URL SHORTENER PROXY] Payload: {payload}")
        
        response = requests.post(api_url, json=payload, timeout=10)
        
        print(f"[URL SHORTENER PROXY] Response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"[URL SHORTENER PROXY] ✅ Success: {result}")
            return jsonify(result)
        else:
            error_msg = f"Shortening API returned status {response.status_code}"
            print(f"[URL SHORTENER PROXY] ❌ Error: {error_msg}")
            return jsonify({"error": error_msg}), response.status_code
            
    except requests.exceptions.ConnectionError:
        error_msg = "Could not connect to shortening API. Make sure it's running on http://127.0.0.1:8000"
        print(f"[URL SHORTENER PROXY] ❌ Connection Error: {error_msg}")
        return jsonify({"error": error_msg}), 503
    except requests.exceptions.Timeout:
        error_msg = "Shortening API request timed out"
        print(f"[URL SHORTENER PROXY] ❌ Timeout: {error_msg}")
        return jsonify({"error": error_msg}), 504
    except Exception as e:
        error_msg = f"Error shortening URL: {str(e)}"
        print(f"[URL SHORTENER PROXY] ❌ Exception: {error_msg}")
        return jsonify({"error": error_msg}), 500


@app.route("/api/get-notepad")
@login_required
def get_notepad():
    """Get notepad content"""
    notepad_file = os.path.join(FILES_DIR, "notepad.txt")
    if not os.path.exists(notepad_file):
        return jsonify({"content": "", "message": "Notepad is empty"})
    
    try:
        with open(notepad_file, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content, "message": "Notepad loaded successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/save-notepad", methods=["POST"])
@login_required
def save_notepad():
    """Save notepad content"""
    data = request.get_json()
    content = data.get("content", "")
    
    notepad_file = os.path.join(FILES_DIR, "notepad.txt")
    try:
        os.makedirs(os.path.dirname(notepad_file), exist_ok=True)
        with open(notepad_file, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"success": True, "message": "Notepad saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import csv

@app.route("/api/list-reports")
@login_required
def list_reports():
    files = {
        "success": SUCCESS_CSV,
        "failure": FAILURE_CSV,
        "failed_coupon": FAILED_COUPON,
        "used_coupon": USED_COUPON_FILE,
        "used_mail": USED_MAIL_FILE,
        "removed_mails": REMOVED_MAIL_FILE,
    }

    report_status = {}
    for key, path in files.items():
        # For removed_mails, show it even if empty (so user can see the file exists)
        # For other reports, only show if they have content
        if key == "removed_mails":
            report_status[key] = os.path.exists(path)
        else:
            report_status[key] = os.path.exists(path) and os.path.getsize(path) > 0

    return jsonify(report_status)


@app.route("/api/report-info/<report_type>")
@login_required
def report_info(report_type):
    """Get report file information (size, modified time, row count)"""
    import csv
    files = {
        "success": SUCCESS_CSV,
        "failure": FAILURE_CSV,
        "failed_coupon": FAILED_COUPON,
        "used_coupon": USED_COUPON_FILE,
        "used_mail": USED_MAIL_FILE,
        "removed_mails": REMOVED_MAIL_FILE,
    }
    
    file_path = files.get(report_type)
    if not file_path:
        return jsonify({"error": "Report not found"}), 404
    
    # For removed_mails, allow info even if file doesn't exist (will show 0 rows)
    # For other reports, return error if file doesn't exist
    if report_type != "removed_mails" and not os.path.exists(file_path):
        return jsonify({"error": "Report not found"}), 404
    
    # If file doesn't exist, return default values
    if not os.path.exists(file_path):
        return jsonify({"size": 0, "modified": 0, "rows": 0})
    
    try:
        size = os.path.getsize(file_path)
        modified_time = os.path.getmtime(file_path)
        
        # Count rows efficiently
        row_count = 0
        if report_type == "removed_mails":
            # Text file - count lines
            with open(file_path, 'r', encoding='utf-8') as f:
                row_count = sum(1 for line in f if line.strip())
        else:
            # CSV file - count rows excluding header
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                try:
                    next(reader)  # Skip header
                    row_count = sum(1 for _ in reader)
                except StopIteration:
                    row_count = 0
        
        return jsonify({"size": size, "modified": modified_time, "rows": row_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/view-report/<report_type>")
@login_required
def view_report(report_type):
    files = {
        "success": SUCCESS_CSV,
        "failure": FAILURE_CSV,
        "failed_coupon": FAILED_COUPON,
        "used_coupon": USED_COUPON_FILE,
        "used_mail": USED_MAIL_FILE,
        "removed_mails": REMOVED_MAIL_FILE,
    }

    if report_type not in files:
        return jsonify({"error": "Unknown report type"}), 400

    file_path = files[report_type]

    # For removed_mails, allow viewing even if empty
    # For other reports, return error if empty
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    
    if report_type != "removed_mails" and os.path.getsize(file_path) == 0:
        return jsonify({"error": "File empty"}), 404

    try:
        # Limit rows to prevent loading huge files into memory
        MAX_ROWS = 10000  # Limit to 10k rows for performance
        rows = []
        
        if report_type == "removed_mails":
            # Text file - read as lines and format as table rows
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Add header row
                rows.append(["Email"])
                for i, line in enumerate(lines):
                    if i >= MAX_ROWS:
                        rows.append([f"(Showing first {MAX_ROWS} rows)"])
                        break
                    email = line.strip()
                    if email:  # Only add non-empty lines
                        rows.append([email])
        else:
            # CSV file
            with open(file_path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i >= MAX_ROWS:
                        rows.append(["...", f"(Showing first {MAX_ROWS} rows)", "...", "..."])
                        break
                    rows.append(row)

        return jsonify({"success": True, "rows": rows, "truncated": len(rows) >= MAX_ROWS})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download/<typ>")
@login_required
def download(typ):
    files = {
        "success": SUCCESS_CSV,
        "failure": FAILURE_CSV,
        "used_coupon": USED_COUPON_FILE,
        "used_mail": USED_MAIL_FILE,
        "removed_mails": REMOVED_MAIL_FILE,
    }
    if typ in files and os.path.exists(files[typ]):
        return send_file(files[typ], as_attachment=True)
    return "File not found", 404


@app.route("/api/logs")
@login_required
def list_logs_api():
    """
    Return list of log files (sorted by modified desc) and optionally
    content of selected file (last 800 lines).
    """
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        files = []
        for fname in os.listdir(LOGS_DIR):
            fpath = os.path.join(LOGS_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            if not (fname.lower().endswith(".log") or fname.lower().endswith(".txt")):
                continue
            stat = os.stat(fpath)
            files.append({
                "name": fname,
                "size": stat.st_size,
                "modified": stat.st_mtime
            })
        files.sort(key=lambda x: x["modified"], reverse=True)

        selected = request.args.get("file")
        if not selected or selected not in [f["name"] for f in files]:
            selected = files[0]["name"] if files else None

        content = ""
        if selected:
            target = os.path.join(LOGS_DIR, os.path.basename(selected))
            if os.path.exists(target):
                with open(target, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                tail = lines[-800:] if len(lines) > 800 else lines
                content = "".join(tail)

        return jsonify({"files": files, "selected": selected, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download/log/<path:fname>")
@login_required
def download_log(fname):
    """Download a specific log file from logs directory."""
    safe_name = os.path.basename(fname)
    target = os.path.join(LOGS_DIR, safe_name)
    if os.path.exists(target) and os.path.isfile(target):
        return send_file(target, as_attachment=True)
    return "File not found", 404


@app.route("/logs")
@login_required
def logs_live():
    """Backward-compatible live logs for run-order detailed logs."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return jsonify([line.strip() for line in lines[-2000:]])
        return jsonify([])
    except Exception as e:
        return jsonify([f"Error reading logs: {e}"])


@app.route("/api/last-run-results")
@login_required
def last_run_results():
    """Get results from the last bot run"""
    global LAST_RUN_RESULTS
    return jsonify(LAST_RUN_RESULTS)


@app.route("/api/stop-workers", methods=["POST"])
@login_required
def stop_workers():
    """
    Stop worker processes. If payload has {"all": true}, stop all.
    """
    global CURRENT_RUNNER, RUNNING
    try:
        if not RUNNING or CURRENT_RUNNER is None:
            return jsonify({"success": False, "error": "No bot is currently running"}), 400

        data = request.get_json(force=True, silent=True) or {}
        stop_all = bool(data.get("all"))

        # Guard against CURRENT_RUNNER being None mid-call
        runner = CURRENT_RUNNER
        if runner is None:
            RUNNING = False
            return jsonify({"success": False, "error": "Runner not available"}), 400

        # Count alive processes
        alive = [p for p in runner.processes if p.is_alive()] if hasattr(runner, "processes") else []
        alive_count = len(alive)

        if stop_all:
            stopped = runner.stop_all_workers()
            # If nothing left alive, mark run as stopped
            if not any(p.is_alive() for p in runner.processes):
                RUNNING = False
                CURRENT_RUNNER = None
            return jsonify({"success": True, "stopped": stopped, "requested": "all", "running": RUNNING})

        try:
            count = int(data.get("count", 0))
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid count"}), 400

        if count <= 0:
            return jsonify({"success": False, "error": "Count must be greater than zero"}), 400

        if count > alive_count:
            count = alive_count

        stopped = runner.stop_workers(count)

        # If no workers remain alive after stopping, update flags
        if not any(p.is_alive() for p in runner.processes):
            RUNNING = False
            CURRENT_RUNNER = None

        return jsonify({"success": True, "stopped": stopped, "requested": count, "running": RUNNING})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/stats")
@login_required
def stats():
    global LAST_STATS
    try:
        if os.path.exists(MAIL_FILE):
            with open(MAIL_FILE, 'r', encoding='utf-8') as f:
                mails_left = sum(1 for line in f if line.strip())
        else:
            mails_left = 0
    except Exception:
        mails_left = 0
        
    try:
        if os.path.exists(COUPON_FILE):
            with open(COUPON_FILE, 'r', encoding='utf-8') as f:
                coupons_left = sum(1 for line in f if line.strip())
        else:
            coupons_left = 0
    except Exception:
        coupons_left = 0

    # Count success rows properly (excluding header)
    try:
        if os.path.exists(SUCCESS_CSV):
            with open(SUCCESS_CSV, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                try:
                    next(reader)  # Skip header
                    succ = sum(1 for _ in reader)
                except StopIteration:
                    succ = 0
        else:
            succ = 0
    except Exception:
        succ = 0
        
    # Count failure rows properly (excluding header)
    try:
        if os.path.exists(FAILURE_CSV):
            with open(FAILURE_CSV, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                try:
                    next(reader)  # Skip header
                    fail = sum(1 for _ in reader)
                except StopIteration:
                    fail = 0
        else:
            fail = 0
    except Exception:
        fail = 0

    LAST_STATS.update({
        "total": succ + fail,
        "success": succ,
        "failure": fail,
        "mails_left": mails_left,
        "coupons_left": coupons_left
    })

    return jsonify(LAST_STATS)

# ============================================================
# NEW ROUTES TO FIX 404 ERRORS
# ============================================================
@app.route("/check-resources")
@login_required
def check_resources():
    warnings = []
    if not os.path.exists(MAIL_FILE) or os.path.getsize(MAIL_FILE) == 0:
        warnings.append("📧 Mail file (mail.txt) is missing or empty!")
    if not os.path.exists(COUPON_FILE) or os.path.getsize(COUPON_FILE) == 0:
        warnings.append("🏷️ Coupon file (coupon.txt) is missing or empty!")
    return jsonify({"warnings": warnings})


@app.route("/check-status")
@login_required
def check_status():
    global RUNNING
    return jsonify({"running": RUNNING})

@app.route('/favicon.ico')
def favicon():
    # Return a 204 No Content response to stop the 404 error
    return '', 204

# Serve image assets (eye open/close) without hardcoding absolute paths
@app.route("/images/<path:filename>")
def images_static(filename):
    images_dir = os.path.join(ROOT, "..", "images")
    return send_from_directory(images_dir, filename)

# Deal selection endpoints
import json

DEAL_SELECTION_FILE = os.path.join(FILES_DIR, "deal_selection.json")
DEAL_RESPONSE_FILE = os.path.join(FILES_DIR, "deal_response.json")

@app.route("/deal-poll")
@login_required
def deal_poll():
    """Poll for deal selection requests from workers"""
    try:
        if os.path.exists(DEAL_SELECTION_FILE):
            with open(DEAL_SELECTION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Check if still pending (not older than 10 minutes)
            if data.get("status") == "pending" and (time.time() - data.get("timestamp", 0)) < 600:
                return jsonify({
                    "pending": True,
                    "session_id": data.get("session_id"),
                    "products": data.get("products", []),
                    "matched_index": data.get("matched_index")
                })
        
        return jsonify({"pending": False})
    except Exception as e:
        return jsonify({"pending": False, "error": str(e)})

@app.route("/deal-selection", methods=["POST"])
@login_required
def deal_selection():
    """Handle deal selection when matching name not found"""
    data = request.get_json()
    session_id = data.get("session_id")
    selected_index = data.get("selected_index")

    if not session_id:
        return jsonify({"error": "Invalid request"}), 400

    # Write response to file for worker to read
    try:
        response_data = {
            "session_id": session_id,
            "selected_index": selected_index,
            "timestamp": time.time()
        }
        with open(DEAL_RESPONSE_FILE, "w", encoding="utf-8") as f:
            json.dump(response_data, f, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================
# RUN FLASK
# ============================================================
if __name__ == "__main__":
    # Create empty files if they don't exist, to prevent read errors
    for f in [MAIL_FILE, COUPON_FILE, SUCCESS_CSV, FAILURE_CSV, USED_MAIL_FILE, USED_COUPON_FILE]:
        if not os.path.exists(f):
            open(f, 'w').close()
            
    # Get local IP address for network access (function already defined above)
    local_ip = get_local_ip()
    port = int(os.environ.get("FLASK_PORT", "5000"))
    custom_domain = os.environ.get("SCREENSHOT_DOMAIN", "").strip()
    
    print("🚀 FlipkartSniper 2.0 started!")
    print(f"   Local:   http://localhost:{port}")
    print(f"   Network: http://{local_ip}:{port}")
    if custom_domain:
        print(f"   Domain:  http://{custom_domain if ':' in custom_domain else f'{custom_domain}:{port}'}")
    print(f"   Mobile:  Access from your phone using the Network URL above")
    print(f"   Screenshots: {get_screenshot_base_url()}")
    app.run(host='0.0.0.0', port=port, debug=True)




