"""SQLite database layer for the reselling marketplace."""
import hashlib
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "marketplace.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                password    TEXT NOT NULL,
                salt        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                title       TEXT NOT NULL,
                description TEXT,
                price       REAL NOT NULL,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
                                                                        CREATE TABLE IF NOT EXISTS images (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id  INTEGER NOT NULL,
                filename    TEXT NOT NULL,
                FOREIGN KEY (listing_id) REFERENCES listings (id)
            );
            CREATE TABLE IF NOT EXISTS purchase_requests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id  INTEGER NOT NULL,
                buyer_id    INTEGER,
                buyer_email TEXT NOT NULL,
                message     TEXT,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (listing_id) REFERENCES listings (id),
                FOREIGN KEY (buyer_id) REFERENCES users (id)
            );
            """
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def create_user(username: str, password: str) -> Optional[int]:
    salt = uuid.uuid4().hex
    pw_hash = _hash_password(password, salt)
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password, salt, created_at) VALUES (?, ?, ?, ?)",
                (username, pw_hash, salt, datetime.utcnow().isoformat()),
            )
            conn.commit()
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def verify_user(username: str, password: str) -> Optional[int]:
    with get_db() as conn:
        row = conn.execute("SELECT id, password, salt FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    if _hash_password(password, row["salt"]) == row["password"]:
        return row["id"]
    return None


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# --------------------------------------------------------------------------- #
# Listing helpers
# --------------------------------------------------------------------------- #
def create_listing(user_id: int, title: str, description: str, price: float, image_filenames: list[str]) -> int:
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO listings (user_id, title, description, price, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, title, description, price, now),
        )
        listing_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO images (listing_id, filename) VALUES (?, ?)",
            [(listing_id, fn) for fn in image_filenames],
        )
        conn.commit()
    return listing_id


def get_listings_for_user(user_id: int) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM listings WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def get_listing_by_id(listing_id: int) -> Optional[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()


def get_all_listings() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM listings ORDER BY created_at DESC"
        ).fetchall()


def get_images_for_listing(listing_id: int) -> list[str]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT filename FROM images WHERE listing_id = ? ORDER BY id", (listing_id,)
        ).fetchall()
    return [r["filename"] for r in rows]


def get_listing_owner(listing_id: int) -> Optional[int]:
    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return row["user_id"] if row else None


def delete_listing(listing_id: int) -> None:
    with get_db() as conn:
        rows = conn.execute("SELECT filename FROM images WHERE listing_id = ?", (listing_id,)).fetchall()
        filenames = [r["filename"] for r in rows]
        conn.execute("DELETE FROM images WHERE listing_id = ?", (listing_id,))
        conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        conn.commit()
    for fn in filenames:
        path = os.path.join(UPLOAD_DIR, fn)
        if os.path.exists(path):
            os.remove(path)


# --------------------------------------------------------------------------- #
# Purchase request helpers
# --------------------------------------------------------------------------- #
def create_purchase_request(listing_id: int, buyer_id: Optional[int], buyer_email: str, message: str) -> int:
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO purchase_requests (listing_id, buyer_id, buyer_email, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (listing_id, buyer_id, buyer_email, message, now),
        )
        conn.commit()
        return cur.lastrowid


def get_requests_for_listing(listing_id: int) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM purchase_requests WHERE listing_id = ? ORDER BY created_at DESC", (listing_id,)
        ).fetchall()


def get_requests_for_seller(user_id: int) -> list[sqlite3.Row]:
    """All purchase requests for listings owned by *user_id*."""
    with get_db() as conn:
        return conn.execute(
            "SELECT pr.*, l.title as listing_title FROM purchase_requests pr "
            "JOIN listings l ON pr.listing_id = l.id "
            "WHERE l.user_id = ? ORDER BY pr.created_at DESC",
            (user_id,),
        ).fetchall()


def count_requests_for_seller(user_id: int) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM purchase_requests pr "
            "JOIN listings l ON pr.listing_id = l.id "
            "WHERE l.user_id = ?",
            (user_id,),
        ).fetchone()
    return row["cnt"] if row else 0
