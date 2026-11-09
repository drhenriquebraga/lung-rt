import ctypes
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def local_directory(path):
    path = Path(path).resolve()
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("database_requires_local_disk")
    if os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
        raise ValueError("database_requires_local_disk")
    path.mkdir(parents=True, exist_ok=True)
    return path


class Store:
    COLLECTIONS = {"cases", "reports", "reviews", "settings", "links"}

    def __init__(self, directory):
        self.directory = local_directory(directory)
        self.path = self.directory / "lung.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entities(collection TEXT NOT NULL,key TEXT NOT NULL,
                    revision TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(collection,key));
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,source TEXT NOT NULL,
                    created REAL NOT NULL,collection TEXT NOT NULL,key TEXT NOT NULL,
                    parent TEXT,body TEXT NOT NULL,digest TEXT NOT NULL,applied INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS conflicts(id TEXT PRIMARY KEY,event TEXT NOT NULL,
                    current_revision TEXT,created REAL NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO meta VALUES('station',?)", (uuid.uuid4().hex,))
            self.station = db.execute("SELECT value FROM meta WHERE key='station'").fetchone()[0]

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, collection, key):
        with self.connect() as db:
            row = db.execute("SELECT body,revision FROM entities WHERE collection=? AND key=?", (collection,key)).fetchone()
        if row is None:
            return None
        return {**json.loads(row["body"]), "_revision": row["revision"]}

    def list(self, collection, limit=1000):
        with self.connect() as db:
            rows = db.execute("SELECT key,body,revision FROM entities WHERE collection=? ORDER BY rowid DESC LIMIT ?", (collection,min(int(limit),10000))).fetchall()
        return [{**json.loads(r["body"]), "_key":r["key"], "_revision":r["revision"]} for r in rows]

    def put(self, collection, key, body, expected_revision=None):
        if collection not in self.COLLECTIONS or not isinstance(body,dict):
            raise ValueError("invalid_event")
        body = {k:v for k,v in body.items() if not k.startswith("_")}
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM entities WHERE collection=? AND key=?", (collection,key)).fetchone()
            parent = row[0] if row else None
            if expected_revision is not None and parent != expected_revision:
                raise ValueError("revision_conflict")
            event = {"id":uuid.uuid4().hex,"source":self.station,"created":time.time(),
                     "collection":collection,"key":str(key),"parent":parent,"body":body}
            event["digest"] = hashlib.sha256(canonical(event).encode()).hexdigest()
            self._apply(db,event)
        return self.get(collection,key)

    def _apply(self, db, event):
        if set(event) != {"id","source","created","collection","key","parent","body","digest"}:
            raise ValueError("invalid_event")
        body = dict(event)
        digest = body.pop("digest")
        if hashlib.sha256(canonical(body).encode()).hexdigest() != digest:
            raise ValueError("invalid_event_hash")
        if event["collection"] not in self.COLLECTIONS or not isinstance(event["body"],dict):
            raise ValueError("invalid_event")
        if not all(isinstance(event[x],str) and 0 < len(event[x]) <= 200 for x in ("id","source","key")):
            raise ValueError("invalid_event")
        found = db.execute("SELECT digest FROM events WHERE id=?", (event["id"],)).fetchone()
        if found:
            if found[0] != digest:
                raise ValueError("event_identity_collision")
            return "duplicate"
        row = db.execute("SELECT revision FROM entities WHERE collection=? AND key=?", (event["collection"],event["key"])).fetchone()
        current = row[0] if row else None
        apply = current == event["parent"]
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)", (event["id"],event["source"],event["created"],event["collection"],event["key"],event["parent"],canonical(event["body"]),digest,int(apply)))
        if apply:
            db.execute("INSERT OR REPLACE INTO entities VALUES(?,?,?,?)", (event["collection"],event["key"],event["id"],canonical(event["body"])))
        else:
            db.execute("INSERT INTO conflicts VALUES(?,?,?,?)", (event["id"],canonical(event),current,time.time()))
        return "applied" if apply else "conflict"

    def conflicts(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,current_revision,created FROM conflicts")]

    def sync(self, directory):
        destination = Path(directory).resolve()
        if destination == self.directory:
            raise ValueError("sync_folder_must_differ")
        destination.mkdir(parents=True,exist_ok=True)
        result = {"applied":0,"duplicate":0,"conflict":0,"rejected":0,"exported":0}
        with self.lock, self.connect() as db:
            rows = db.execute("SELECT * FROM events ORDER BY rowid").fetchall()
            for row in rows:
                event = {k:row[k] for k in ("id","source","created","collection","key","parent","digest")}
                event["body"] = json.loads(row["body"])
                final = destination / (event["id"] + ".lung-event.json")
                if final.exists():
                    continue
                temp = destination / (event["id"] + "." + self.station + ".tmp")
                temp.write_text(canonical(event),encoding="utf-8")
                os.replace(temp,final)
                result["exported"] += 1
            pending = []
            for path in destination.glob("*.lung-event.json"):
                try:
                    if path.stat().st_size > 4*1024*1024 or path.is_symlink():
                        raise ValueError("invalid_event")
                    pending.append(json.loads(path.read_text(encoding="utf-8")))
                except (ValueError,OSError):
                    result["rejected"] += 1
            # Preserve causality even if station clocks differ.
            while pending:
                ids = {e.get("id") for e in pending if isinstance(e,dict)}
                ready = [e for e in pending if isinstance(e,dict) and e.get("parent") not in ids]
                if not ready:
                    result["rejected"] += len(pending)
                    break
                for event in ready:
                    pending.remove(event)
                    try:
                        outcome = self._apply(db,event)
                        result[outcome] += 1
                    except (ValueError,TypeError,KeyError,sqlite3.Error):
                        result["rejected"] += 1
        return result

    def backup(self, directory):
        destination = Path(directory).resolve()
        destination.mkdir(parents=True,exist_ok=True)
        name = "lung-backup-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".sqlite3"
        temp = self.directory / (name + ".tmp")
        with self.lock, self.connect() as source:
            target=sqlite3.connect(temp)
            try:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("backup_integrity_failed")
            finally:
                target.close()
        import shutil
        output = destination / name
        partial = destination / (name + ".partial")
        shutil.copyfile(temp,partial)
        os.replace(partial,output)
        temp.unlink()
        return {"file":name,"sha256":hashlib.sha256(output.read_bytes()).hexdigest(),"size":output.stat().st_size}
