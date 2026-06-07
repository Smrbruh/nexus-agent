"""
memory/database.py — SQLite-backed memory system for NEXUS Agent

Schema:
  - conversations: full chat history per user
  - tool_logs:     every tool call and its result
  - agent_decisions: reasoning trace per request
  - queries:        searchable index of user queries

Supports simple RAG-like retrieval via keyword search on stored content.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from utils.logger import setup_logger

log = setup_logger("memory")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    role        TEXT    NOT NULL CHECK(role IN ('user','assistant','system')),
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS tool_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    session_id  TEXT,
    tool_name   TEXT    NOT NULL,
    tool_input  TEXT,
    tool_output TEXT,
    success     INTEGER NOT NULL DEFAULT 1,
    duration_ms INTEGER,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tool_user ON tool_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_logs(tool_name);

CREATE TABLE IF NOT EXISTS agent_decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    session_id  TEXT,
    query       TEXT    NOT NULL,
    plan        TEXT,
    tools_used  TEXT,
    final_response TEXT,
    iterations  INTEGER DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_decision_user ON agent_decisions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS queries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    query_hash  TEXT    NOT NULL,
    query_text  TEXT    NOT NULL,
    category    TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_query_hash ON queries(query_hash);
CREATE INDEX IF NOT EXISTS idx_query_user ON queries(user_id);

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    is_admin    INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    first_seen  TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# Database Manager
# ---------------------------------------------------------------------------
class DatabaseManager:
    """Thread-safe SQLite database manager with connection pooling."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._init_schema()
        log.info(f"Database initialized at: {db_path}")

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------
    def upsert_user(self, user_id: int, username: str = None, first_name: str = None, is_admin: bool = False):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, first_name, is_admin, first_seen, last_seen)
                VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    username   = excluded.username,
                    first_name = excluded.first_name,
                    last_seen  = datetime('now'),
                    message_count = message_count + 1
                """,
                (user_id, username, first_name, int(is_admin)),
            )
            conn.commit()

    def get_all_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY last_seen DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------
    def add_message(self, user_id: int, role: str, content: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content),
            )
            conn.commit()

    def get_history(self, user_id: int, limit: int = 20) -> list[dict]:
        """Return last `limit` messages for a user in chronological order."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at FROM conversations
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_history(self, user_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_all_conversations(self, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT c.*, u.username, u.first_name
                FROM conversations c
                LEFT JOIN users u ON c.user_id = u.id
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Tool logs
    # ------------------------------------------------------------------
    def log_tool_call(
        self,
        user_id: int,
        tool_name: str,
        tool_input: str,
        tool_output: str,
        success: bool = True,
        duration_ms: int = None,
        session_id: str = None,
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO tool_logs
                    (user_id, session_id, tool_name, tool_input, tool_output, success, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, session_id, tool_name, tool_input, tool_output, int(success), duration_ms),
            )
            conn.commit()

    def get_tool_stats(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) as total_calls,
                    SUM(success) as successful,
                    COUNT(*) - SUM(success) as failed,
                    AVG(duration_ms) as avg_duration_ms,
                    MAX(created_at) as last_used
                FROM tool_logs
                GROUP BY tool_name
                ORDER BY total_calls DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_tool_logs(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT t.*, u.username
                FROM tool_logs t
                LEFT JOIN users u ON t.user_id = u.id
                ORDER BY t.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Agent decisions
    # ------------------------------------------------------------------
    def log_decision(
        self,
        user_id: int,
        query: str,
        plan: str,
        tools_used: list[str],
        final_response: str,
        iterations: int,
        session_id: str = None,
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_decisions
                    (user_id, session_id, query, plan, tools_used, final_response, iterations)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    session_id,
                    query,
                    plan,
                    json.dumps(tools_used),
                    final_response,
                    iterations,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Query index + simple RAG retrieval
    # ------------------------------------------------------------------
    def index_query(self, user_id: int, query_text: str, category: str = None, query_hash: str = None):
        from utils.helpers import sha256
        h = query_hash or sha256(query_text)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO queries (user_id, query_hash, query_text, category) VALUES (?, ?, ?, ?)",
                (user_id, h, query_text, category),
            )
            conn.commit()

    def search_memory(self, keyword: str, limit: int = 10) -> list[dict]:
        """
        Simple keyword-based RAG retrieval across conversations + tool logs.
        Returns most relevant past entries for context injection.
        """
        keyword_like = f"%{keyword}%"
        results = []

        with self._conn() as conn:
            # Search conversations
            rows = conn.execute(
                """
                SELECT 'conversation' as source, user_id, content as text, created_at
                FROM conversations
                WHERE content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (keyword_like, limit),
            ).fetchall()
            results.extend([dict(r) for r in rows])

            # Search tool outputs
            rows = conn.execute(
                """
                SELECT 'tool_output' as source, user_id, tool_output as text, created_at
                FROM tool_logs
                WHERE tool_output LIKE ? AND success = 1
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (keyword_like, limit // 2),
            ).fetchall()
            results.extend([dict(r) for r in rows])

        # Sort combined results by recency
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Dashboard stats
    # ------------------------------------------------------------------
    def get_dashboard_stats(self) -> dict:
        with self._conn() as conn:
            stats = {}

            stats["total_users"] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            stats["total_messages"] = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            stats["total_tool_calls"] = conn.execute("SELECT COUNT(*) FROM tool_logs").fetchone()[0]
            stats["total_decisions"] = conn.execute("SELECT COUNT(*) FROM agent_decisions").fetchone()[0]

            row = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE created_at >= datetime('now','-1 day')"
            ).fetchone()
            stats["messages_today"] = row[0]

            row = conn.execute(
                "SELECT COUNT(*) FROM tool_logs WHERE created_at >= datetime('now','-1 day')"
            ).fetchone()
            stats["tool_calls_today"] = row[0]

            return stats
