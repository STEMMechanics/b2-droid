"""Throttled persistent observations built on the extensible entity store."""

import json
import threading
import time


class ObservationService:
    def __init__(self, entities, clock, location="unknown", interval=30,
                 maximum_events=5000):
        self.entities = entities
        self.clock = clock
        self.location = location
        self.interval = max(5.0, float(interval))
        self.maximum_events = max(100, int(maximum_events))
        self._lock = threading.Lock()
        self._last_signature = None
        self._last_recorded = 0.0

    def maybe_record(self, objects, person=None):
        labels = tuple(sorted(set(str(item) for item in objects if item)))
        signature = (labels, person or "unknown")
        now = time.monotonic()
        with self._lock:
            if signature == self._last_signature and now - self._last_recorded < self.interval:
                return None
            self._last_signature = signature
            self._last_recorded = now
        observation = self.entities.create("observation", self.clock())
        self.entities.set_metadata(observation, "observed_at", self.clock())
        self.entities.set_metadata(observation, "location", self.location)
        self.entities.set_metadata(observation, "person", person or "unknown")
        self.entities.set_metadata(observation, "objects", list(labels))
        for label in labels:
            target = self.entities.find_or_create("observed_object", label)
            self.entities.link(observation, "saw", target)
        with self.entities.database() as db:
            db.execute(
                """DELETE FROM entities WHERE kind='observation' AND id NOT IN
                   (SELECT id FROM entities WHERE kind='observation'
                    ORDER BY id DESC LIMIT ?)""",
                (self.maximum_events,),
            )
        return observation

    def resolve_recent_unknown(self, person, maximum=20):
        """Attribute only the current run of anonymous single-person sightings."""
        encoded_unknown = '"unknown"'
        encoded_person = json.dumps(person, ensure_ascii=False)
        with self.entities.database() as db:
            rows = db.execute(
                """SELECT e.id, m.value_json FROM entities e
                   JOIN entity_metadata m ON m.entity_id=e.id
                   WHERE e.kind='observation' AND m.namespace='core' AND m.key='person'
                   ORDER BY e.id DESC LIMIT ?""",
                (maximum,),
            ).fetchall()
            unknown_ids = []
            for row in rows:
                if row["value_json"] != encoded_unknown:
                    break
                unknown_ids.append(row["id"])
            if unknown_ids:
                placeholders = ",".join("?" for _ in unknown_ids)
                db.execute(
                    f"""UPDATE entity_metadata SET value_json=?, updated_at=CURRENT_TIMESTAMP
                        WHERE namespace='core' AND key='person'
                        AND entity_id IN ({placeholders})""",
                    (encoded_person, *unknown_ids),
                )
        return len(unknown_ids)

    def context(self):
        recent = self.entities.recent("observation", 5)
        return {
            "location": self.location,
            "recent_observations": [
                self.entities.get(item["id"]) for item in recent
            ],
            "privacy": "labels and timestamps only; camera images are not stored",
        }
