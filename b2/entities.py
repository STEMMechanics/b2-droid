"""Forward-compatible entities, metadata, and relationships."""

import json


class EntityRepository:
    """Store extensible facts without requiring columns for every new feature."""

    SCHEMA_CONTRACT = 1

    def __init__(self, database):
        self.database = database

    def ensure_schema(self):
        with self.database() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_contracts (
                    name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS entity_metadata (
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    namespace TEXT NOT NULL DEFAULT 'core',
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (entity_id, namespace, key)
                );
                CREATE TABLE IF NOT EXISTS entity_links (
                    source_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    relation TEXT NOT NULL,
                    target_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source_id, relation, target_id)
                );
            """)
            db.execute(
                """INSERT INTO schema_contracts(name, version) VALUES('entities', ?)
                   ON CONFLICT(name) DO UPDATE SET version = MAX(version, excluded.version),
                   updated_at = CURRENT_TIMESTAMP""",
                (self.SCHEMA_CONTRACT,),
            )

    def create(self, kind, label=None):
        with self.database() as db:
            cursor = db.execute(
                "INSERT INTO entities(kind, label) VALUES(?, ?)", (kind, label)
            )
            return cursor.lastrowid

    def find_or_create(self, kind, label):
        with self.database() as db:
            row = db.execute(
                """SELECT id FROM entities WHERE kind=? AND label=? COLLATE NOCASE
                   ORDER BY id LIMIT 1""",
                (kind, label),
            ).fetchone()
            if row:
                return row["id"]
            return db.execute(
                "INSERT INTO entities(kind, label) VALUES(?, ?)", (kind, label)
            ).lastrowid

    def ensure_legacy_person(self, db, person_id, name):
        """Bridge an existing people row without changing legacy face keys."""
        encoded_id = json.dumps(int(person_id))
        row = db.execute(
            """SELECT e.id FROM entities e JOIN entity_metadata m ON m.entity_id=e.id
               WHERE m.namespace='legacy' AND m.key='people_id' AND m.value_json=?""",
            (encoded_id,),
        ).fetchone()
        if row:
            db.execute("UPDATE entities SET label=? WHERE id=?", (name, row["id"]))
            return row["id"]
        entity_id = db.execute(
            "INSERT INTO entities(kind, label) VALUES('person', ?)", (name,)
        ).lastrowid
        db.execute(
            """INSERT INTO entity_metadata(entity_id, namespace, key, value_json)
               VALUES(?, 'legacy', 'people_id', ?)""",
            (entity_id, encoded_id),
        )
        return entity_id

    def recent(self, kind=None, limit=20):
        with self.database() as db:
            if kind:
                rows = db.execute(
                    """SELECT id, kind, label, created_at FROM entities
                       WHERE kind=? ORDER BY id DESC LIMIT ?""",
                    (kind, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT id, kind, label, created_at FROM entities
                       ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def set_metadata(self, entity_id, key, value, namespace="core"):
        encoded = json.dumps(value, ensure_ascii=False)
        with self.database() as db:
            db.execute(
                """INSERT INTO entity_metadata(entity_id, namespace, key, value_json)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(entity_id, namespace, key) DO UPDATE SET
                   value_json=excluded.value_json, updated_at=CURRENT_TIMESTAMP""",
                (entity_id, namespace, key, encoded),
            )

    def link(self, source_id, relation, target_id, metadata=None):
        with self.database() as db:
            db.execute(
                """INSERT INTO entity_links(source_id, relation, target_id, metadata_json)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(source_id, relation, target_id) DO UPDATE SET
                   metadata_json=excluded.metadata_json""",
                (source_id, relation, target_id, json.dumps(metadata or {})),
            )

    def get(self, entity_id):
        with self.database() as db:
            row = db.execute(
                "SELECT id, kind, label, created_at FROM entities WHERE id=?",
                (entity_id,),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["metadata"] = {
                f"{item['namespace']}.{item['key']}": json.loads(item["value_json"])
                for item in db.execute(
                    """SELECT namespace, key, value_json FROM entity_metadata
                       WHERE entity_id=?""",
                    (entity_id,),
                )
            }
            result["links"] = [
                {
                    "relation": item["relation"],
                    "target_id": item["target_id"],
                    "metadata": json.loads(item["metadata_json"]),
                }
                for item in db.execute(
                    """SELECT relation, target_id, metadata_json FROM entity_links
                       WHERE source_id=?""",
                    (entity_id,),
                )
            ]
            return result

    def context(self):
        with self.database() as db:
            count = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            people = [
                row["label"] for row in db.execute(
                    """SELECT label FROM entities WHERE kind='person' AND label IS NOT NULL
                       ORDER BY label LIMIT 50"""
                )
            ]
        return {
            "schema_contract": self.SCHEMA_CONTRACT,
            "entities": count,
            "known_people": people,
            "compatibility": "unknown metadata and links are preserved",
        }
