"""A transactionally stored tournament snapshot with revision checks and history."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .domain import RuleError


class Conflict(RuleError):
    pass


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "tournament.sqlite3"
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tournament (
                    id INTEGER PRIMARY KEY CHECK (id=1), revision INTEGER NOT NULL, body TEXT);
                INSERT OR IGNORE INTO tournament VALUES (1, 0, NULL);
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                    action TEXT NOT NULL, before_state TEXT, after_state TEXT);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def read(self):
        with closing(self.connect()) as db:
            row = db.execute("SELECT revision, body FROM tournament WHERE id=1").fetchone()
            return json.loads(row["body"]) if row["body"] else None, row["revision"]

    def backup(self, state):
        if state is not None:
            folder = self.directory / "backups"
            folder.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            target = folder / f"before-replacement-{stamp}.json"
            with target.open("x", encoding="utf-8") as output:
                json.dump(state, output, ensure_ascii=False, indent=2)

    def change(self, revision, operation, payload, callback, backup=False):
        if type(revision) is not int or revision < 0:
            raise RuleError("A current tournament revision is required.")
        if not isinstance(operation, str) or not 8 <= len(operation) <= 100:
            raise RuleError("A submission identifier is required.")
        canonical = json.dumps(payload, sort_keys=True)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT payload FROM operations WHERE id=?", (operation,)).fetchone()
            if prior:
                if prior["payload"] != canonical:
                    raise Conflict("This submission identifier was already used for another change.")
                return
            row = db.execute("SELECT revision, body FROM tournament WHERE id=1").fetchone()
            if row["revision"] != revision:
                raise Conflict("Someone saved a change while you were editing. Review the latest data before saving again.")
            old = json.loads(row["body"]) if row["body"] else None
            new = callback(json.loads(row["body"]) if row["body"] else None)
            if backup:
                self.backup(old)
            encoded = json.dumps(new, ensure_ascii=False) if new is not None else None
            db.execute("UPDATE tournament SET revision=revision+1, body=? WHERE id=1", (encoded,))
            db.execute("INSERT INTO history(created_at, action, before_state, after_state) VALUES (?, ?, ?, ?)",
                       (datetime.now(timezone.utc).isoformat(), canonical, row["body"], encoded))
            db.execute("INSERT INTO operations VALUES (?, ?)", (operation, canonical))

    def history(self):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM history ORDER BY id DESC LIMIT 40").fetchall()
        result = []
        for row in rows:
            before = json.loads(row["before_state"]) if row["before_state"] else {}
            after = json.loads(row["after_state"]) if row["after_state"] else {}
            old_games = {g["id"]: g for g in before.get("games", [])}
            changes = [dict(game=g["id"], before=old_games.get(g["id"]), after=g)
                       for g in after.get("games", []) if old_games.get(g["id"]) != g]
            action = json.loads(row["action"])
            result.append(dict(id=row["id"], at=row["created_at"], type=action.get("type"),
                               game=action.get("game"), changes=changes))
        return result
