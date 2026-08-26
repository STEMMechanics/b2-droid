"""Contract tests for hardware-free text interpretation."""

import unittest

from b2.commands import (
    check_drive_command, clean_user_text, emotion_changes_for_request,
    extract_person_name, extract_wake_request, is_disengagement, is_noise,
)


class CommandTests(unittest.TestCase):
    def test_noise_labels(self):
        self.assertTrue(is_noise("[BLANK_AUDIO]"))
        self.assertTrue(is_noise("(birds chirping)"))
        self.assertFalse(is_noise("turn left"))

    def test_wake_phrase(self):
        self.assertEqual(extract_wake_request("Hey B2, look at me"), "look at me")
        self.assertEqual(clean_user_text("Bee two: hello"), "hello")

    def test_natural_motion_is_bounded(self):
        cases = {
            "Could you turn a little left?": "left",
            "please look right": "right",
            "turn around": "turn_around",
            "look at me": "find_person",
            "stop moving please": "stop",
            "drive forwards": "forward",
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(check_drive_command(phrase), expected)
        self.assertIsNone(check_drive_command("wander around the room"))

    def test_emotion_directions(self):
        self.assertIn(("happiness", 25), emotion_changes_for_request("cheer up"))
        self.assertIn(("concern", -30), emotion_changes_for_request("calm down"))
        self.assertEqual(emotion_changes_for_request("how are you feeling?"), ())

    def test_conversation_disengagement(self):
        self.assertTrue(is_disengagement("I'm talking to Carrie."))
        self.assertFalse(is_disengagement("I'm talking to you."))

    def test_name_does_not_consume_commands(self):
        self.assertEqual(extract_person_name("Just James"), "James")
        self.assertIsNone(extract_person_name("turn left"))


if __name__ == "__main__":
    unittest.main()
