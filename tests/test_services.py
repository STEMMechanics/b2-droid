"""Contract tests for modular state, context, persistence, and motion services."""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from b2.context import ContextDirectory, ContextRegistry, FeatureCatalog
from b2.display import DisplayService
from b2.emotions import EmotionController
from b2.emotion_effects import EmotionEffects
from b2.emotion_model import EmotionScorer
from b2.entities import EntityRepository
from b2.learning import LearningStore
from b2.motion import MotionController
from b2.observations import ObservationService
from b2.skills import SkillRegistry, SkillResult
from b2.storage import DatabaseService
from b2.updater import _stage_source_tree
from b2.runtime_config import _validate
from b2.web import PAGE


class ServiceTests(unittest.TestCase):
    def test_context_registry_isolates_failed_provider(self):
        registry = ContextRegistry()
        registry.register("working", lambda: {"value": 1})

        def broken():
            raise RuntimeError("test failure")

        registry.register("broken", broken)
        snapshot = registry.snapshot()
        self.assertEqual(snapshot["working"], {"value": 1})
        self.assertEqual(snapshot["broken"]["status"], "unavailable")

    def test_drop_in_context_and_feature_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "weather.json").write_text(
                json.dumps({"description": "local weather sensor"}), encoding="utf-8"
            )
            self.assertIn("weather", ContextDirectory(root).snapshot())
            catalog = root / "features.json"
            catalog.write_text(
                json.dumps({"features": [{"name": "test", "description": "works"}]}),
                encoding="utf-8",
            )
            self.assertIn("test: works", FeatureCatalog(catalog).render())

    def test_emotions_are_bounded(self):
        emotions = EmotionController()
        emotions.adjust("happiness", 1000)
        emotions.adjust("concern", -1000)
        self.assertEqual(emotions.snapshot()["happiness"], 100.0)
        self.assertEqual(emotions.snapshot()["concern"], 0.0)

    def test_emotion_events_have_named_bounded_causes(self):
        scorer = EmotionScorer()
        result = scorer.event("user_interaction")
        self.assertEqual(result["happiness"], 63.0)
        self.assertEqual(result["loneliness"], 0.0)
        self.assertEqual(scorer.last_cause, "user_interaction")
        with self.assertRaises(KeyError):
            scorer.event("invented_by_model")

    def test_emotion_passive_rates_are_owned_by_model(self):
        scorer = EmotionScorer()
        absent = scorer.advance(
            elapsed=5, person_visible=False, person_identified=False,
            inactive_seconds=100, exploration_idle_seconds=45,
        )
        self.assertGreater(absent["loneliness"], 5)
        present = scorer.advance(
            elapsed=5, person_visible=True, person_identified=True,
            inactive_seconds=100, exploration_idle_seconds=45,
        )
        self.assertGreater(present["curiosity"], absent["curiosity"])
        self.assertEqual(scorer.last_cause, "person_visible_idle")

    def test_emotion_effect_thresholds_and_cooldown(self):
        effects = EmotionEffects()
        scores = {"happiness": 55, "curiosity": 76, "loneliness": 5, "concern": 0}
        self.assertEqual(effects.face_for(scores, person_visible=True), "curious")
        self.assertEqual(effects.curiosity_cooldown(scores, 600), 300)
        scores["concern"] = 60
        self.assertEqual(effects.face_for(scores, person_visible=True), "concerned")
        self.assertTrue(effects.should_play_transition_sound("idle", "concerned", 20, 20))

    def test_motion_learns_only_from_recent_explicit_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            learning = LearningStore(Path(directory) / "learning.json")
            states = []
            controller = MotionController(
                states.append, threading.Lock(), learning,
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1,
            )
            controller.execute("left")
            result = controller.apply_feedback("That went too far")
            self.assertEqual(result["direction"], "shorter")
            self.assertAlmostEqual(controller.duration("left"), 0.17)
            self.assertEqual(states, ["left", "stop"])
            self.assertIsNone(controller.apply_feedback("nice weather"))

    def test_motion_learns_bounded_power_from_stall_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            learning = LearningStore(Path(directory) / "learning.json")
            speeds = []
            controller = MotionController(
                lambda state: None, threading.Lock(), learning,
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1, send_speed=speeds.append,
                default_speed=110, maximum_speed=125,
            )
            controller.note_action("left", 0.2, source="centering")
            first = controller.apply_feedback("You didn't move")
            second = controller.apply_feedback("Your wheels are stalled")
            self.assertEqual(first["motor_speed"], 125)
            self.assertEqual(second["motor_speed"], 125)
            self.assertEqual(speeds, [125])

    def test_not_stuck_confirms_motion_without_increasing_power(self):
        with tempfile.TemporaryDirectory() as directory:
            learning = LearningStore(Path(directory) / "learning.json")
            speeds = []
            controller = MotionController(
                lambda state: None, threading.Lock(), learning,
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1, send_speed=speeds.append,
                default_speed=110, maximum_speed=200,
            )
            controller.note_action("left", 0.2, source="centering")
            result = controller.apply_feedback("No, it's not stuck")
            self.assertEqual(result["direction"], "movement_confirmed")
            self.assertEqual(result["motor_speed"], 110)
            self.assertEqual(speeds, [])

    def test_repeated_camera_stalls_increase_power_once(self):
        class StallProbe:
            @staticmethod
            def begin():
                return "before"

            @staticmethod
            def finish(before, after_frame=None):
                return {"verdict": "stalled", "difference": 0.1}

        with tempfile.TemporaryDirectory() as directory:
            learning = LearningStore(Path(directory) / "learning.json")
            speeds = []
            controller = MotionController(
                lambda state: None, threading.Lock(), learning,
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1, send_speed=speeds.append,
                default_speed=110, maximum_speed=150,
                motion_probe=StallProbe(), visual_stalls_required=2,
            )
            for _ in range(2):
                controller.note_action(
                    "left", 0.2, probe=controller.start_probe(),
                    defer_verification=True,
                )
                for _ in range(3):
                    controller.finish_pending_probe(object())
            self.assertEqual(controller.speed(), 130)
            self.assertEqual(speeds, [130])

    def test_pending_camera_frame_is_not_coerced_to_boolean(self):
        class ArrayLikeFrame:
            def __bool__(self):
                raise ValueError("ambiguous frame truth value")

        class Probe:
            settle_seconds = 0

            @staticmethod
            def begin():
                return ArrayLikeFrame()

            @staticmethod
            def finish(before, after_frame=None):
                return {"verdict": "moved"}

        with tempfile.TemporaryDirectory() as directory:
            controller = MotionController(
                lambda state: None, threading.Lock(),
                LearningStore(Path(directory) / "learning.json"),
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1, motion_probe=Probe(),
            )
            controller.note_action(
                "left", 0.2, probe=controller.start_probe(),
                defer_verification=True,
            )
            result = None
            for _ in range(3):
                result = controller.finish_pending_probe(object())
            self.assertEqual(result["verdict"], "moved")

    def test_conflicting_camera_frames_are_uncertain(self):
        class Probe:
            settle_seconds = 0

            def __init__(self):
                self.verdicts = iter(("moved", "stalled", "uncertain"))

            @staticmethod
            def begin():
                return "before"

            def finish(self, before, after_frame=None):
                return {"verdict": next(self.verdicts)}

        with tempfile.TemporaryDirectory() as directory:
            controller = MotionController(
                lambda state: None, threading.Lock(),
                LearningStore(Path(directory) / "learning.json"),
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1, motion_probe=Probe(),
            )
            controller.note_action(
                "left", 0.2, probe=controller.start_probe(),
                defer_verification=True,
            )
            result = None
            for _ in range(3):
                result = controller.finish_pending_probe(object())
            self.assertEqual(result["verdict"], "uncertain")
            self.assertTrue(controller.automatic_motion_allowed())

    def test_maximum_power_stalls_pause_automatic_motion(self):
        class StallProbe:
            settle_seconds = 0

            @staticmethod
            def begin():
                return "before"

            @staticmethod
            def finish(before, after_frame=None):
                return {"verdict": "stalled"}

        with tempfile.TemporaryDirectory() as directory:
            states = []
            controller = MotionController(
                states.append, threading.Lock(),
                LearningStore(Path(directory) / "learning.json"),
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1, motion_probe=StallProbe(),
                default_speed=110, maximum_speed=110, stall_cooldown=30,
            )
            for _ in range(2):
                controller.note_action(
                    "left", 0.2, probe=controller.start_probe(),
                    defer_verification=True,
                )
                for _ in range(3):
                    controller.finish_pending_probe(object())
            self.assertFalse(controller.automatic_motion_allowed())
            self.assertEqual(states, ["stop"])

    def test_startup_motor_floor_overrides_older_learned_power(self):
        with tempfile.TemporaryDirectory() as directory:
            learning = LearningStore(Path(directory) / "learning.json")
            learning.set_bounded("motion", "motor_speed", 200, 70, 240)
            controller = MotionController(
                lambda state: None, threading.Lock(), learning,
                defaults={
                    "forward": 0, "reverse": 0, "left": 0.2,
                    "right": 0.2, "turn_around": 1.0,
                },
                minimum_turn=0.1, default_speed=220,
                minimum_speed=110, maximum_speed=240,
            )
            self.assertEqual(controller.speed(), 220)

    def test_database_connections_commit_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            service = DatabaseService(Path(directory) / "b2.sqlite3")
            with service.connection() as database:
                database.execute("CREATE TABLE sample(value TEXT)")
                database.execute("INSERT INTO sample VALUES ('ok')")
            with service.connection() as database:
                value = database.execute("SELECT value FROM sample").fetchone()[0]
            self.assertEqual(value, "ok")

    def test_entity_extensions_survive_older_readers(self):
        with tempfile.TemporaryDirectory() as directory:
            database = DatabaseService(Path(directory) / "b2.sqlite3")
            entities = EntityRepository(database.connection)
            entities.ensure_schema()
            james = entities.create("person", "James")
            cat = entities.create("animal.cat", "Mittens")
            entities.set_metadata(cat, "colour", "black")
            entities.set_metadata(cat, "temperament", "curious", namespace="v2")
            entities.link(cat, "owned_by", james, {"source": "James"})

            # A v1-style reader understands core colour but ignores rather than
            # rewrites unknown v2 metadata and relationships.
            with database.connection() as connection:
                colour = connection.execute(
                    """SELECT value_json FROM entity_metadata
                       WHERE entity_id=? AND namespace='core' AND key='colour'""",
                    (cat,),
                ).fetchone()[0]
            self.assertEqual(json.loads(colour), "black")
            restored = entities.get(cat)
            self.assertEqual(restored["metadata"]["v2.temperament"], "curious")
            self.assertEqual(restored["links"][0]["relation"], "owned_by")

    def test_legacy_person_is_bridged_without_changing_face_key(self):
        with tempfile.TemporaryDirectory() as directory:
            database = DatabaseService(Path(directory) / "b2.sqlite3")
            entities = EntityRepository(database.connection)
            entities.ensure_schema()
            with database.connection() as connection:
                connection.execute(
                    "CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT)"
                )
                connection.execute("INSERT INTO people VALUES(7, 'James')")
                entity_id = entities.ensure_legacy_person(connection, 7, "James")
            self.assertEqual(entities.get(entity_id)["metadata"]["legacy.people_id"], 7)

    def test_observations_store_labels_time_person_and_place(self):
        with tempfile.TemporaryDirectory() as directory:
            database = DatabaseService(Path(directory) / "b2.sqlite3")
            entities = EntityRepository(database.connection)
            entities.ensure_schema()
            observations = ObservationService(
                entities, lambda: "2026-08-26T10:00:00+10:00", "workshop"
            )
            observation_id = observations.maybe_record(["cat", "chair"], "James")
            saved = entities.get(observation_id)
            self.assertEqual(saved["metadata"]["core.person"], "James")
            self.assertEqual(saved["metadata"]["core.location"], "workshop")
            self.assertEqual(saved["metadata"]["core.objects"], ["cat", "chair"])
            anonymous = observations.maybe_record(["cat"], None)
            self.assertEqual(observations.resolve_recent_unknown("James"), 1)
            self.assertEqual(
                entities.get(anonymous)["metadata"]["core.person"], "James"
            )

    def test_display_encodes_validated_dynamic_frame(self):
        commands = []
        display = DisplayService(commands.append)
        payload = display.show(["10000001"] * 8)
        self.assertEqual(payload, "81" * 8)
        self.assertEqual(commands, ["matrix:" + "81" * 8])
        with self.assertRaises(ValueError):
            display.show([0] * 7)

    def test_skills_share_one_discoverable_entrypoint(self):
        class EchoSkill:
            name = "echo"
            description = "repeat a request"

            @staticmethod
            def available():
                return True

            @staticmethod
            def run(request, context):
                return SkillResult("echo", request, [])

        registry = SkillRegistry()
        registry.register(EchoSkill())
        call = registry.extract('<skill name="echo">hello</skill>')
        self.assertEqual(call, ("echo", "hello"))
        self.assertEqual(registry.run(*call).content, "hello")
        self.assertTrue(registry.context()["echo"]["available"])

    def test_marked_source_tree_is_staged_without_local_runtime_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "B2-Droid"
            (source / "scripts").mkdir(parents=True)
            (source / "b2").mkdir()
            (source / ".venv" / "bin").mkdir(parents=True)
            (source / "data").mkdir()
            (source / "scripts" / "install.sh").write_text("#!/bin/sh\n")
            (source / "pyproject.toml").write_text("[project]\n")
            (source / "droid.py").write_text("# droid\n")
            (source / "b2" / "__init__.py").write_text("")
            (source / "data" / "b2.sqlite3").write_text("do not install")
            (source / ".venv" / "bin" / "python").symlink_to("python3")
            marker = source / "b2-source-update.json"
            marker.write_text(json.dumps({
                "source_update_format": 1,
                "version": "test",
            }))

            staging = root / "staging"
            _stage_source_tree(marker, staging)

            self.assertTrue((staging / "scripts" / "install.sh").is_file())
            self.assertFalse((staging / ".venv").exists())
            self.assertFalse((staging / "data").exists())

    def test_dashboard_runtime_config_is_allow_listed(self):
        self.assertEqual(_validate("B2_AUDIO_DEVICE", "plughw:0,0"), "plughw:0,0")
        self.assertEqual(
            _validate("B2_AUDIO_DEVICE", "plughw:CARD=Webcam,DEV=0"),
            "plughw:CARD=Webcam,DEV=0",
        )
        self.assertEqual(_validate("B2_MOTOR_SPEED_MAX", 240), "240")
        with self.assertRaises(ValueError):
            _validate("B2_AUDIO_DEVICE", "../../etc/passwd")
        self.assertIn(b"/api/audio/devices", PAGE)
        self.assertNotIn(b"B2_WEB_PASSWORD", PAGE)


if __name__ == "__main__":
    unittest.main()
