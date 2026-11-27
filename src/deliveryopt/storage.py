"""Stockage SQLite (bibliothèque standard, aucune installation). Un seul fichier, sauvegardable par simple copie."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .config import AppSettings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'operateur')),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    created_by TEXT NOT NULL,
    label TEXT NOT NULL,
    plan_date TEXT,
    input_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geocode_cache (query TEXT PRIMARY KEY, result_json TEXT NOT NULL, created_at REAL NOT NULL);
"""


class Storage:
    def __init__(self, path: str | os.PathLike):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)

    def _run(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # utilisateurs
    def count_users(self) -> int:
        return self._run("SELECT COUNT(*) AS n FROM users")[0]["n"]

    def add_user(self, username: str, password_hash: str, role: str) -> None:
        self._run("INSERT INTO users VALUES (?, ?, ?, ?)", (username, password_hash, role, time.time()))

    def get_user(self, username: str) -> sqlite3.Row | None:
        rows = self._run("SELECT * FROM users WHERE username = ?", (username,))
        return rows[0] if rows else None

    def list_users(self) -> list[dict]:
        return [{"username": r["username"], "role": r["role"]} for r in self._run("SELECT username, role FROM users ORDER BY username")]

    def set_password(self, username: str, password_hash: str) -> None:
        self._run("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))

    def delete_user(self, username: str) -> None:
        self._run("DELETE FROM users WHERE username = ?", (username,))

    # sessions
    def add_session(self, token_hash: str, username: str, expires_at: float) -> None:
        self._run("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        self._run("INSERT INTO sessions VALUES (?, ?, ?)", (token_hash, username, expires_at))

    def get_session_user(self, token_hash: str) -> sqlite3.Row | None:
        rows = self._run(
            "SELECT u.username, u.role FROM sessions s JOIN users u ON u.username = s.username WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash, time.time()),
        )
        return rows[0] if rows else None

    def delete_session(self, token_hash: str) -> None:
        self._run("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    # paramètres
    def load_settings(self) -> AppSettings:
        rows = self._run("SELECT value FROM settings WHERE key = 'app'")
        return AppSettings.from_dict(json.loads(rows[0]["value"])) if rows else AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        self._run("INSERT INTO settings VALUES ('app', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(settings.to_dict()),))

    # plans
    def add_plan(self, created_by: str, label: str, plan_date: str | None, input_rows: list[dict], result: dict) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO plans (created_at, created_by, label, plan_date, input_json, result_json) VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), created_by, label, plan_date, json.dumps(input_rows), json.dumps(result)),
            )
            return int(cur.lastrowid)

    def list_plans(self, limit: int = 100) -> list[dict]:
        rows = self._run("SELECT id, created_at, created_by, label, plan_date, result_json FROM plans ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            totals = json.loads(r["result_json"])["totals"]
            out.append({"id": r["id"], "created_at": r["created_at"], "created_by": r["created_by"], "label": r["label"], "date": r["plan_date"], "totals": totals})
        return out

    def get_plan(self, plan_id: int) -> dict | None:
        rows = self._run("SELECT * FROM plans WHERE id = ?", (plan_id,))
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "created_at": r["created_at"], "created_by": r["created_by"], "label": r["label"], "date": r["plan_date"], "input": json.loads(r["input_json"]), "result": json.loads(r["result_json"])}

    # cache de géocodage
    def get_geocode(self, query: str) -> list[dict] | None:
        rows = self._run("SELECT result_json FROM geocode_cache WHERE query = ?", (query,))
        return json.loads(rows[0]["result_json"]) if rows else None

    def put_geocode(self, query: str, results: list[dict]) -> None:
        self._run("INSERT OR REPLACE INTO geocode_cache VALUES (?, ?, ?)", (query, json.dumps(results), time.time()))
