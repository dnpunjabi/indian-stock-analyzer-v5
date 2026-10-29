"""
backend/whatsapp_memory.py — Multi-Turn Conversational Memory & Context Engine

Maintains user-isolated, session-aware conversation history with sliding TTL,
active symbol inheritance for pronouns ("it", "its", "the company"), and
multi-stock comparative context tracking.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import pytz

logger = logging.getLogger("whatsapp_memory")

IST = pytz.timezone("Asia/Kolkata")

def _get_db():
    from backend.main import get_db
    return get_db()


def init_chat_history_db() -> None:
    """Initializes the whatsapp_chat_history SQLite table and indexes."""
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_phone TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    active_symbols_json TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_history_lookup 
                ON whatsapp_chat_history(user_phone, created_at)
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Error initializing whatsapp_chat_history table: {e}", exc_info=True)


def get_recent_conversation_history(
    user_phone: Optional[str] = None,
    max_turns: int = 4,
    ttl_minutes: int = 15
) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    Retrieves recent non-expired conversation turns for the user.
    Returns:
        (history_messages, active_symbols)
        where history_messages is [{"role": "user"|"assistant", "content": ...}]
        and active_symbols is list of symbols discussed in the most recent turn.
    """
    init_chat_history_db()
    phone = user_phone or os.environ.get("WHATSAPP_RECIPIENT", "")
    if not phone:
        return [], []

    cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            # Fetch recent turns within the active TTL window
            cursor.execute("""
                SELECT role, content, active_symbols_json, created_at
                FROM whatsapp_chat_history
                WHERE user_phone = ? AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (phone, cutoff, max_turns * 2))
            rows = cursor.fetchall()

            if not rows:
                return [], []

            # Re-order to chronological order
            ordered_rows = list(reversed(rows))
            history_messages: List[Dict[str, str]] = []
            latest_symbols: List[str] = []

            for r in ordered_rows:
                history_messages.append({
                    "role": r["role"],
                    "content": r["content"]
                })
                syms_raw = r["active_symbols_json"]
                if syms_raw:
                    try:
                        syms = json.loads(syms_raw)
                        if isinstance(syms, list) and syms:
                            latest_symbols = syms
                    except Exception:
                        pass

            return history_messages, latest_symbols

    except Exception as e:
        logger.error(f"Error retrieving conversation history: {e}", exc_info=True)
        return [], []


def save_chat_turn(
    user_phone: Optional[str],
    user_query: str,
    assistant_reply: str,
    active_symbols: List[str]
) -> None:
    """
    Saves a completed user-assistant conversation turn with active stock symbols.
    Maintains a rolling window by pruning records older than 24 hours.
    """
    init_chat_history_db()
    phone = user_phone or os.environ.get("WHATSAPP_RECIPIENT", "")
    if not phone:
        return

    syms_json = json.dumps(active_symbols) if active_symbols else "[]"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Clean assistant reply for concise context storage (strip buttons/signatures)
    clean_reply = assistant_reply.split("────────────────────────")[0].strip()
    clean_reply = clean_reply.replace("• Not SEBI financial advice.", "").strip()
    if len(clean_reply) > 400:
        clean_reply = clean_reply[:397] + "..."

    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            # 1. Insert User Query
            cursor.execute("""
                INSERT INTO whatsapp_chat_history (user_phone, role, content, active_symbols_json, created_at)
                VALUES (?, 'user', ?, ?, ?)
            """, (phone, user_query.strip(), syms_json, now_str))

            # 2. Insert Assistant Reply
            cursor.execute("""
                INSERT INTO whatsapp_chat_history (user_phone, role, content, active_symbols_json, created_at)
                VALUES (?, 'assistant', ?, ?, ?)
            """, (phone, clean_reply, syms_json, now_str))

            # 3. Prune old records (> 24 hours) to keep SQLite small and fast
            prune_cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                DELETE FROM whatsapp_chat_history 
                WHERE created_at < ?
            """, (prune_cutoff,))

            conn.commit()

    except Exception as e:
        logger.error(f"Error saving chat turn: {e}", exc_info=True)


def clear_chat_history(user_phone: Optional[str] = None) -> bool:
    """Manually resets the conversation memory for a user."""
    init_chat_history_db()
    phone = user_phone or os.environ.get("WHATSAPP_RECIPIENT", "")
    if not phone:
        return False
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM whatsapp_chat_history WHERE user_phone = ?", (phone,))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error clearing chat history: {e}")
        return False
