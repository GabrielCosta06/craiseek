from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Iterable, List, Optional, Any

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
    trial_ends_at: Optional[str] = None
    subscription_credits: int = 0
    referral_code: Optional[str] = None
    referred_by: Optional[str] = None
    successful_referrals: int = 0
    whatsapp_unlocked: bool = False
    last_digest_sent: Optional[str] = None
    is_lifetime: bool = False
    lifetime_purchased_at: Optional[str] = None


@dataclass
class Referral:
    id: int
    referrer_code: str
    referee_email: str
    referee_phone: Optional[str]
    reward_granted: bool
    created_at: Optional[str] = None
    rewarded_at: Optional[str] = None


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
        trial_ends_at TIMESTAMP,
        subscription_credits INTEGER DEFAULT 0,
        referral_code TEXT UNIQUE,
        referred_by TEXT,
        successful_referrals INTEGER DEFAULT 0,
        whatsapp_unlocked INTEGER DEFAULT 0,
        last_digest_sent TIMESTAMP,
        is_lifetime INTEGER DEFAULT 0,
        lifetime_purchased_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_code TEXT NOT NULL,
        referee_email TEXT NOT NULL,
        referee_phone TEXT,
        reward_granted INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        rewarded_at TIMESTAMP,
        FOREIGN KEY (referrer_code) REFERENCES subscribers(referral_code)
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
    if "trial_ends_at" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN trial_ends_at TIMESTAMP;")
    if "subscription_credits" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN subscription_credits INTEGER DEFAULT 0;")
    if "referral_code" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN referral_code TEXT UNIQUE;")
    if "referred_by" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN referred_by TEXT;")
    if "successful_referrals" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN successful_referrals INTEGER DEFAULT 0;")
    if "whatsapp_unlocked" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN whatsapp_unlocked INTEGER DEFAULT 0;")
    if "last_digest_sent" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN last_digest_sent TIMESTAMP;")
    if "is_lifetime" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN is_lifetime INTEGER DEFAULT 0;")
    if "lifetime_purchased_at" not in columns:
        conn.execute("ALTER TABLE subscribers ADD COLUMN lifetime_purchased_at TIMESTAMP;")

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
    SELECT id, phone, email, whatsapp, channel_preferences, tier, created_at,
           trial_ends_at, subscription_credits, referral_code, referred_by
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
        trial_ends_at=row["trial_ends_at"],
        subscription_credits=row["subscription_credits"] or 0,
        referral_code=row["referral_code"],
        referred_by=row["referred_by"],
    )


def generate_referral_code(email: str) -> str:
    """Generate a unique referral code for a user."""
    import hashlib
    import secrets
    # Create a deterministic but unique code based on email + random salt
    salt = secrets.token_hex(4)
    base = f"{email}{salt}"
    code = hashlib.sha256(base.encode()).hexdigest()[:8].upper()
    return f"MS{code}"


def set_referral_code(email: str) -> Optional[str]:
    """Generate and set a referral code for a subscriber."""
    max_attempts = 10
    for _ in range(max_attempts):
        code = generate_referral_code(email)
        query = """
        UPDATE subscribers
        SET referral_code = ?
        WHERE email = ? AND referral_code IS NULL;
        """
        with get_connection() as conn:
            cursor = conn.execute(query, (code, email))
            if cursor.rowcount > 0:
                logger.info("Referral code generated", extra={"email": email, "code": code})
                return code
    return None


def mark_subscriber_as_lifetime(email: str) -> bool:
    """Mark a subscriber as having purchased lifetime access."""
    query = """
    UPDATE subscribers
    SET is_lifetime = 1, lifetime_purchased_at = CURRENT_TIMESTAMP, tier = 'ELITE'
    WHERE email = ?;
    """
    with get_connection() as conn:
        cursor = conn.execute(query, (email,))
        success = cursor.rowcount > 0
    if success:
        logger.info("Subscriber marked as lifetime", extra={"email": email})
    return success


def get_subscriber_by_referral_code(code: str) -> Optional[Subscriber]:
    """Fetch a subscriber by their referral code."""
    query = """
    SELECT id, phone, email, whatsapp, channel_preferences, tier, created_at,
           trial_ends_at, subscription_credits, referral_code, referred_by
    FROM subscribers
    WHERE referral_code = ?;
    """
    with get_connection() as conn:
        row = conn.execute(query, (code,)).fetchone()
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
        trial_ends_at=row["trial_ends_at"],
        subscription_credits=row["subscription_credits"] or 0,
        referral_code=row["referral_code"],
        referred_by=row["referred_by"],
    )


def record_referral(referrer_code: str, referee_email: str, referee_phone: Optional[str] = None) -> bool:
    """Record a referral when someone signs up using a referral code."""
    query = """
    INSERT INTO referrals (referrer_code, referee_email, referee_phone)
    VALUES (?, ?, ?);
    """
    with get_connection() as conn:
        try:
            conn.execute(query, (referrer_code, referee_email, referee_phone))
            logger.info("Referral recorded", extra={"referrer_code": referrer_code, "referee": referee_email})
            return True
        except sqlite3.IntegrityError:
            logger.warning("Duplicate referral attempt", extra={"referrer_code": referrer_code, "referee": referee_email})
            return False


def grant_referral_reward(referral_id: int) -> bool:
    """
    Grant 1 month Elite tier to BOTH the referrer and referee for a successful referral.
    Also increments successful_referrals counter and potentially unlocks WhatsApp.
    """
    # First, mark the referral as rewarded
    update_referral = """
    UPDATE referrals
    SET reward_granted = 1, rewarded_at = CURRENT_TIMESTAMP
    WHERE id = ? AND reward_granted = 0;
    """
    
    # Get the referrer code and referee email
    get_referral_info = """
    SELECT referrer_code, referee_email FROM referrals WHERE id = ?;
    """
    
    # Add 1 Elite credit (1 month Elite tier) to the referrer
    add_credit_referrer = """
    UPDATE subscribers
    SET subscription_credits = subscription_credits + 1
    WHERE referral_code = ?;
    """
    
    # Add 1 Elite credit to the referee (new subscriber)
    add_credit_referee = """
    UPDATE subscribers
    SET subscription_credits = subscription_credits + 1
    WHERE email = ?;
    """
    
    with get_connection() as conn:
        cursor = conn.execute(update_referral, (referral_id,))
        if cursor.rowcount == 0:
            return False
        
        row = conn.execute(get_referral_info, (referral_id,)).fetchone()
        if not row:
            return False
        
        referrer_code = row["referrer_code"]
        referee_email = row["referee_email"]
        
        # Grant Elite credit to referrer
        conn.execute(add_credit_referrer, (referrer_code,))
        
        # Grant Elite credit to referee
        conn.execute(add_credit_referee, (referee_email,))
        
        # Increment successful referrals (this also unlocks WhatsApp at 3)
        increment_successful_referrals(referrer_code)
        
        logger.info("Referral reward granted to BOTH parties", extra={
            "referral_id": referral_id,
            "referrer_code": referrer_code,
            "referee_email": referee_email
        })
        return True


def get_pending_referrals(referrer_code: str) -> List[Referral]:
    """Get all referrals that haven't been rewarded yet for a given referrer."""
    query = """
    SELECT id, referrer_code, referee_email, referee_phone, reward_granted, created_at, rewarded_at
    FROM referrals
    WHERE referrer_code = ? AND reward_granted = 0;
    """
    with get_connection() as conn:
        rows = conn.execute(query, (referrer_code,)).fetchall()
    
    return [
        Referral(
            id=row["id"],
            referrer_code=row["referrer_code"],
            referee_email=row["referee_email"],
            referee_phone=row["referee_phone"],
            reward_granted=bool(row["reward_granted"]),
            created_at=row["created_at"],
            rewarded_at=row["rewarded_at"],
        )
        for row in rows
    ]


def get_all_referrals(referrer_code: str) -> List[Referral]:
    """Get all referrals (both pending and rewarded) for a given referrer."""
    query = """
    SELECT id, referrer_code, referee_email, referee_phone, reward_granted, created_at, rewarded_at
    FROM referrals
    WHERE referrer_code = ?
    ORDER BY created_at DESC;
    """
    with get_connection() as conn:
        rows = conn.execute(query, (referrer_code,)).fetchall()
    
    return [
        Referral(
            id=row["id"],
            referrer_code=row["referrer_code"],
            referee_email=row["referee_email"],
            referee_phone=row["referee_phone"],
            reward_granted=bool(row["reward_granted"]),
            created_at=row["created_at"],
            rewarded_at=row["rewarded_at"],
        )
        for row in rows
    ]


def use_subscription_credit(email: str) -> bool:
    """Use one subscription credit (1 month free) for a subscriber."""
    query = """
    UPDATE subscribers
    SET subscription_credits = subscription_credits - 1
    WHERE email = ? AND subscription_credits > 0;
    """
    with get_connection() as conn:
        cursor = conn.execute(query, (email,))
        if cursor.rowcount > 0:
            logger.info("Subscription credit used", extra={"email": email})
            return True
    return False


def get_free_users_for_digest() -> List[Subscriber]:
    """Get all free tier users who should receive weekly digest (7+ days since last digest)."""
    query = """
    SELECT * FROM subscribers
    WHERE tier = 'FREE'
    AND email IS NOT NULL
    AND (last_digest_sent IS NULL OR last_digest_sent < datetime('now', '-7 days'));
    """
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
    
    return [
        Subscriber(
            id=row["id"],
            tier=row["tier"],
            channel_preferences=row["channel_preferences"].split(",") if row["channel_preferences"] else ["sms"],
            phone=row["phone"],
            email=row["email"],
            whatsapp=row["whatsapp"],
            created_at=row["created_at"],
            trial_ends_at=row["trial_ends_at"],
            subscription_credits=row.get("subscription_credits", 0),
            referral_code=row.get("referral_code"),
            referred_by=row.get("referred_by"),
            successful_referrals=row.get("successful_referrals", 0),
            whatsapp_unlocked=bool(row.get("whatsapp_unlocked", 0)),
            last_digest_sent=row.get("last_digest_sent"),
        )
        for row in rows
    ]


def update_digest_sent(subscriber_id: int) -> None:
    """Mark that a digest email was sent to this subscriber."""
    query = """
    UPDATE subscribers
    SET last_digest_sent = CURRENT_TIMESTAMP
    WHERE id = ?;
    """
    with get_connection() as conn:
        conn.execute(query, (subscriber_id,))
        logger.info("Digest timestamp updated", extra={"subscriber_id": subscriber_id})


def increment_successful_referrals(referral_code: str) -> int:
    """Increment successful referrals count and return new count. Unlocks WhatsApp at 3."""
    update_count = """
    UPDATE subscribers
    SET successful_referrals = successful_referrals + 1
    WHERE referral_code = ?;
    """
    
    get_count = """
    SELECT successful_referrals FROM subscribers WHERE referral_code = ?;
    """
    
    unlock_whatsapp = """
    UPDATE subscribers
    SET whatsapp_unlocked = 1
    WHERE referral_code = ? AND successful_referrals >= 3;
    """
    
    with get_connection() as conn:
        conn.execute(update_count, (referral_code,))
        row = conn.execute(get_count, (referral_code,)).fetchone()
        count = row["successful_referrals"] if row else 0
        
        if count >= 3:
            conn.execute(unlock_whatsapp, (referral_code,))
            logger.info("WhatsApp unlocked", extra={"referral_code": referral_code, "count": count})
        
        return count


def get_listings_from_past_week(keywords: str, max_price: int | None = None, min_bedrooms: int | None = None, limit: int = 10) -> List[Listing]:
    """Get recent listings from the past 7 days matching criteria."""
    conditions = ["first_seen > datetime('now', '-7 days')"]
    params: List[Any] = []
    
    # Split keywords and create LIKE conditions
    if keywords:
        keyword_list = [k.strip().lower() for k in keywords.split(",")]
        keyword_conditions = " OR ".join(["LOWER(title) LIKE ?" for _ in keyword_list])
        conditions.append(f"({keyword_conditions})")
        params.extend([f"%{k}%" for k in keyword_list])
    
    if max_price is not None:
        conditions.append("price <= ?")
        params.append(max_price)
    
    if min_bedrooms is not None:
        conditions.append("bedrooms >= ?")
        params.append(min_bedrooms)
    
    where_clause = " AND ".join(conditions)
    query = f"""
    SELECT * FROM listings
    WHERE {where_clause}
    ORDER BY first_seen DESC
    LIMIT ?;
    """
    params.append(limit)
    
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    
    return [
        Listing(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            price=row["price"],
            bedrooms=row.get("bedrooms"),
            location=row.get("location"),
            first_seen=row["first_seen"],
        )
        for row in rows
    ]


# Ensure the database schema exists on import.
init_db()

