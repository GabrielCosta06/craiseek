from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Iterable, List, Optional

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Listing:
    post_id: str
    title: str
    url: str
    price: Optional[str] = None
    neighborhood: Optional[str] = None
    created_at: Optional[str] = None
    notified_at: Optional[str] = None


@dataclass
class User:
    id: int
    email: str
    password_hash: str
    created_at: Optional[str] = None


@dataclass
class Subscriber:
    id: int
    tier: str
    channel_preferences: List[str]
    phone: Optional[str]
    email: Optional[str]
    whatsapp: Optional[str]
    created_at: Optional[str] = None


SETTINGS = get_settings()
DB_PATH = Path(SETTINGS.database_path)


def _ensure_directory(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with sensible defaults."""
    _ensure_directory(DB_PATH)
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,
        isolation_level=None,
        timeout=30,
    )
    try:
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create required tables if they do not exist."""
    schema = """
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS listings (
        post_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        price TEXT,
        neighborhood TEXT,
        url TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notified_at TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS subscribers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE,
        email TEXT UNIQUE,
        whatsapp TEXT,
        channel_preferences TEXT NOT NULL DEFAULT 'sms',
        tier TEXT NOT NULL DEFAULT 'FREE',
        email_verified INTEGER DEFAULT 0,
        verification_token TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """

    with get_connection() as conn:
        conn.executescript(schema)
        _ensure_subscriber_schema(conn)


def _ensure_subscriber_schema(conn: sqlite3.Connection) -> None:
    """Ensure subscriber table has expected columns and indexes."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(subscribers);")}
    if "email" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN email TEXT;")
    if "whatsapp" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN whatsapp TEXT;")
    if "channel_preferences" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN channel_preferences TEXT NOT NULL DEFAULT 'sms';")
    if "tier" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN tier TEXT NOT NULL DEFAULT 'FREE';")
    if "email_verified" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN email_verified INTEGER DEFAULT 0;")
    if "verification_token" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN verification_token TEXT;")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_subscribers_phone ON subscribers(phone) WHERE phone IS NOT NULL;"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_subscribers_email ON subscribers(email) WHERE email IS NOT NULL;"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_subscribers_whatsapp ON subscribers(whatsapp) WHERE whatsapp IS NOT NULL;"
    )
    conn.execute(
        "UPDATE subscribers SET channel_preferences = 'sms' WHERE channel_preferences IS NULL OR TRIM(channel_preferences) = '';"
    )
    conn.execute("UPDATE subscribers SET tier = COALESCE(tier, 'FREE');")
    conn.execute("UPDATE subscribers SET email_verified = 0 WHERE email_verified IS NULL;")


def insert_listing(listing: Listing) -> bool:
    """Insert a listing if new. Returns True when inserted."""
    query = """
    INSERT OR IGNORE INTO listings (post_id, title, price, neighborhood, url)
    VALUES (:post_id, :title, :price, :neighborhood, :url);
    """
    with get_connection() as conn:
        cursor = conn.execute(
            query,
            {
                "post_id": listing.post_id,
                "title": listing.title,
                "price": listing.price,
                "neighborhood": listing.neighborhood,
                "url": listing.url,
            },
        )
        inserted = cursor.rowcount > 0
    if inserted:
        logger.info("Inserted new listing", extra={"post_id": listing.post_id})
    return inserted


def list_unnotified_listings(limit: Optional[int] = 50) -> List[Listing]:
    """Return listings that have not yet triggered alerts."""
    base_query = """
    SELECT post_id, title, price, neighborhood, url, created_at, notified_at
    FROM listings
    WHERE notified_at IS NULL
    ORDER BY created_at ASC
    """
    params: tuple = ()
    if limit is not None:
        base_query += " LIMIT ?;"
        params = (limit,)
    with get_connection() as conn:
        rows = conn.execute(base_query, params).fetchall()
    return [
        Listing(
            post_id=row["post_id"],
            title=row["title"],
            price=row["price"],
            neighborhood=row["neighborhood"],
            url=row["url"],
            created_at=row["created_at"],
            notified_at=row["notified_at"],
        )
        for row in rows
    ]


def mark_listings_notified(post_ids: Iterable[str]) -> None:
    """Set notified_at for the provided listings."""
    post_ids = list(post_ids)
    if not post_ids:
        return
    query = """
    UPDATE listings
    SET notified_at = CURRENT_TIMESTAMP
    WHERE post_id = ?;
    """
    with get_connection() as conn:
        conn.executemany(query, [(post_id,) for post_id in post_ids])


def upsert_subscriber(
    *,
    tier: str,
    channels: Iterable[str],
    phone: Optional[str] = None,
    email: Optional[str] = None,
    whatsapp: Optional[str] = None,
) -> bool:
    """Insert or update a subscriber record."""
    channel_string = ",".join(sorted({channel.strip().lower() for channel in channels if channel})) or "sms"
    data = {
        "phone": phone,
        "email": email,
        "whatsapp": whatsapp,
        "channel_preferences": channel_string,
        "tier": tier,
    }

    conflict_field = None
    conflict_value = None
    if phone:
        conflict_field, conflict_value = "phone", phone
    elif email:
        conflict_field, conflict_value = "email", email
    elif whatsapp:
        conflict_field, conflict_value = "whatsapp", whatsapp

    if conflict_field is None:
        logger.error("Cannot upsert subscriber without a unique contact method.")
        return False

    placeholders = ", ".join([f"{key} = :{key}" for key in data.keys()])
    query = f"""
    INSERT INTO subscribers (phone, email, whatsapp, channel_preferences, tier)
    VALUES (:phone, :email, :whatsapp, :channel_preferences, :tier)
    ON CONFLICT({conflict_field}) DO UPDATE SET {placeholders};
    """
    with get_connection() as conn:
        cursor = conn.execute(query, data)
        updated = cursor.rowcount > 0

    if updated:
        logger.info(
            "Upserted subscriber",
            extra={"channel_preferences": channel_string, "tier": tier, "phone": phone, "email": email},
        )
    return updated


def get_all_subscribers() -> List[Subscriber]:
    """Return all subscribers with their preferences."""
    query = """
    SELECT id, phone, email, whatsapp, channel_preferences, tier, created_at
    FROM subscribers;
    """
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
    subscribers: List[Subscriber] = []
    for row in rows:
        channels = [channel.strip() for channel in (row["channel_preferences"] or "").split(",") if channel.strip()]
        if not channels:
            channels = ["sms"]
        subscribers.append(
            Subscriber(
                id=row["id"],
                tier=row["tier"] or "FREE",
                channel_preferences=channels,
                phone=row["phone"],
                email=row["email"],
                whatsapp=row["whatsapp"],
                created_at=row["created_at"],
            )
        )
    return subscribers


def get_subscriber_count() -> int:
    """Return count of subscribers."""
    query = "SELECT COUNT(*) FROM subscribers;"
    with get_connection() as conn:
        result = conn.execute(query).fetchone()
    return int(result[0]) if result else 0


def insert_user(email: str, password_hash: str) -> bool:
    """Insert a new user with hashed password."""
    query = """
    INSERT OR IGNORE INTO users (email, password_hash)
    VALUES (?, ?);
    """
    with get_connection() as conn:
        cursor = conn.execute(query, (email, password_hash))
        inserted = cursor.rowcount > 0
    if inserted:
        logger.info("Created user", extra={"email": email})
    return inserted


def get_user_by_email(email: str) -> Optional[User]:
    """Fetch a user by email."""
    query = """
    SELECT id, email, password_hash, created_at
    FROM users
    WHERE email = ?;
    """
    with get_connection() as conn:
        row = conn.execute(query, (email,)).fetchone()
    if not row:
        return None
    return User(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


def get_user_by_id(user_id: int) -> Optional[User]:
    """Fetch a user by id."""
    query = """
    SELECT id, email, password_hash, created_at
    FROM users
    WHERE id = ?;
    """
    with get_connection() as conn:
        row = conn.execute(query, (user_id,)).fetchone()
    if not row:
        return None
    return User(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


def create_session(user_id: int, token: str) -> None:
    """Persist a session token for a user."""
    query = """
    INSERT OR REPLACE INTO sessions (token, user_id)
    VALUES (?, ?);
    """
    with get_connection() as conn:
        conn.execute(query, (token, user_id))


def get_user_by_session(token: str) -> Optional[User]:
    """Return the user associated with a session token."""
    query = """
    SELECT u.id, u.email, u.password_hash, u.created_at
    FROM sessions s
    JOIN users u ON u.id = s.user_id
    WHERE s.token = ?;
    """
    with get_connection() as conn:
        row = conn.execute(query, (token,)).fetchone()
    if not row:
        return None
    return User(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


def delete_session(token: str) -> None:
    """Delete a session token."""
    query = "DELETE FROM sessions WHERE token = ?;"
    with get_connection() as conn:
        conn.execute(query, (token,))


def get_recent_listings(limit: int = 20) -> List[Listing]:
    """Return recent listings ordered by newest first."""
    query = """
    SELECT post_id, title, price, neighborhood, url, created_at, notified_at
    FROM listings
    ORDER BY datetime(created_at) DESC
    LIMIT ?;
    """
    with get_connection() as conn:
        rows = conn.execute(query, (limit,)).fetchall()
    return [
        Listing(
            post_id=row["post_id"],
            title=row["title"],
            price=row["price"],
            neighborhood=row["neighborhood"],
            url=row["url"],
            created_at=row["created_at"],
            notified_at=row["notified_at"],
        )
        for row in rows
    ]


def get_filtered_listings(
    *,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    neighborhood: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50
) -> List[Listing]:
    """Return listings filtered by price, neighborhood, and/or keyword search."""
    conditions = []
    params = []
    
    # Price filtering - extract numbers from price strings
    if min_price is not None:
        conditions.append("CAST(REPLACE(REPLACE(REPLACE(price, '$', ''), ',', ''), ' ', '') AS INTEGER) >= ?")
        params.append(min_price)
    
    if max_price is not None:
        conditions.append("CAST(REPLACE(REPLACE(REPLACE(price, '$', ''), ',', ''), ' ', '') AS INTEGER) <= ?")
        params.append(max_price)
    
    # Neighborhood filtering
    if neighborhood:
        conditions.append("LOWER(neighborhood) = LOWER(?)")
        params.append(neighborhood)
    
    # Keyword search in title
    if keyword:
        conditions.append("LOWER(title) LIKE LOWER(?)")
        params.append(f"%{keyword}%")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    query = f"""
    SELECT post_id, title, price, neighborhood, url, created_at, notified_at
    FROM listings
    WHERE {where_clause}
    ORDER BY datetime(created_at) DESC
    LIMIT ?;
    """
    
    params.append(limit)
    
    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    
    return [
        Listing(
            post_id=row["post_id"],
            title=row["title"],
            price=row["price"],
            neighborhood=row["neighborhood"],
            url=row["url"],
            created_at=row["created_at"],
            notified_at=row["notified_at"],
        )
        for row in rows
    ]


def get_listing_count() -> int:
    """Return total number of listings stored."""
    query = "SELECT COUNT(*) FROM listings;"
    with get_connection() as conn:
        result = conn.execute(query).fetchone()
    return int(result[0]) if result else 0


def get_unique_neighborhoods(limit: int = 6) -> List[str]:
    """Return a sample of distinct neighborhoods."""
    query = """
    SELECT DISTINCT neighborhood
    FROM listings
    WHERE neighborhood IS NOT NULL AND neighborhood != ''
    ORDER BY created_at DESC
    LIMIT ?;
    """
    with get_connection() as conn:
        rows = conn.execute(query, (limit,)).fetchall()
    return [row["neighborhood"] for row in rows if row["neighborhood"]]


def get_all_neighborhoods() -> List[str]:
    """Return all unique neighborhoods sorted alphabetically."""
    query = """
    SELECT DISTINCT neighborhood
    FROM listings
    WHERE neighborhood IS NOT NULL AND neighborhood != ''
    ORDER BY neighborhood ASC;
    """
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [row["neighborhood"] for row in rows if row["neighborhood"]]


def set_verification_token(email: str, token: str) -> bool:
    """Set verification token for a subscriber email."""
    query = """
    UPDATE subscribers
    SET verification_token = ?, email_verified = 0
    WHERE email = ?;
    """
    with get_connection() as conn:
        cursor = conn.execute(query, (token, email))
        updated = cursor.rowcount > 0
    return updated


def verify_email(token: str) -> bool:
    """Verify an email using the verification token."""
    query = """
    UPDATE subscribers
    SET email_verified = 1, verification_token = NULL
    WHERE verification_token = ? AND email_verified = 0;
    """
    with get_connection() as conn:
        cursor = conn.execute(query, (token,))
        updated = cursor.rowcount > 0
    if updated:
        logger.info("Email verified successfully", extra={"token": token[:8]})
    return updated


def get_subscriber_by_email(email: str) -> Optional[Subscriber]:
    """Fetch a subscriber by email."""
    query = """
    SELECT id, phone, email, whatsapp, channel_preferences, tier, created_at
    FROM subscribers
    WHERE email = ?;
    """
    with get_connection() as conn:
        row = conn.execute(query, (email,)).fetchone()
    if not row:
        return None
    
    channels = [channel.strip() for channel in (row["channel_preferences"] or "").split(",") if channel.strip()]
    if not channels:
        channels = ["email"]
    
    return Subscriber(
        id=row["id"],
        tier=row["tier"] or "FREE",
        channel_preferences=channels,
        phone=row["phone"],
        email=row["email"],
        whatsapp=row["whatsapp"],
        created_at=row["created_at"],
    )


# Ensure the database schema exists on import.
init_db()
