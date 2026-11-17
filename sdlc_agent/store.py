"""Transactional checkpoints, content-addressed response cache and audit events."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, config TEXT NOT NULL, base TEXT NOT NULL,
                    head TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    run_id TEXT, id TEXT, status TEXT NOT NULL, attempts INTEGER DEFAULT 0,
                    result TEXT, error TEXT, PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task_id TEXT,
                    kind TEXT, payload TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS budgets (
                    run_id TEXT PRIMARY KEY, prompt_bytes INTEGER NOT NULL DEFAULT 0);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create(self, run_id, config, base):
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",
                       (run_id, json.dumps(config), base, base, "pending", time.time()))
            db.executemany("INSERT INTO tasks(run_id,id,status) VALUES (?,?,?)",
                           [(run_id, t["id"], "pending") for t in config["tasks"]])

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError(f"Unknown run {run_id}")
            result = dict(row)
            result["config"] = json.loads(result["config"])
            result["tasks"] = [dict(r) for r in db.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY id", (run_id,))]
            for task in result["tasks"]:
                task["result"] = json.loads(task["result"]) if task["result"] else None
            return result

    def task(self, run_id, task_id, status, *, result=None, error=None, attempt=False):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status=?, result=?, error=?, attempts=attempts+? WHERE run_id=? AND id=?",
                       (status, json.dumps(result) if result else None, error, int(attempt), run_id, task_id))

    def checkpoint(self, run_id, head, completed):
        # Commit integration and task success become visible in one SQLite transaction.
        with self.connect() as db:
            db.execute("UPDATE runs SET head=? WHERE id=?", (head, run_id))
            for task_id, result in completed:
                db.execute("UPDATE tasks SET status='succeeded', result=?, error=NULL WHERE run_id=? AND id=?",
                           (json.dumps(result), run_id, task_id))

    def status(self, run_id, status):
        with self.connect() as db:
            db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))

    def event(self, run_id, task_id, kind, payload):
        with self.connect() as db:
            db.execute("INSERT INTO events(run_id,task_id,kind,payload,created) VALUES (?,?,?,?,?)",
                       (run_id, task_id, kind, json.dumps(payload), time.time()))

    def events(self, run_id):
        with self.connect() as db:
            return [{**dict(r), "payload": json.loads(r["payload"])} for r in db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,))]

    def cached(self, key, ttl=86400):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cache WHERE key=? AND created>?", (key, time.time()-ttl)).fetchone()
            return json.loads(row[0]) if row else None

    def cache(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))

    def reserve(self, run_id, amount, limit):
        from .contracts import ContractError
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO budgets VALUES (?,0)", (run_id,))
            used = db.execute("SELECT prompt_bytes FROM budgets WHERE run_id=?", (run_id,)).fetchone()[0]
            if used + amount > limit:
                raise ContractError(f"Run prompt budget exhausted: {used}+{amount}>{limit}")
            db.execute("UPDATE budgets SET prompt_bytes=prompt_bytes+? WHERE run_id=?", (amount, run_id))

    def reserved(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT prompt_bytes FROM budgets WHERE run_id=?", (run_id,)).fetchone()
            return row[0] if row else 0
