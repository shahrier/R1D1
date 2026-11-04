import unittest
from sam_client import decode_response, framing_advice


class FramingTests(unittest.TestCase):
    def candidate(self, left, right, score=.9):
        return {"object_id": "0", "box": [left, 100, right, 600], "confidence": score}

    def test_turn_sign_and_centering(self):
        self.assertEqual(framing_advice([self.candidate(832, 1280)], 1280)["turn_degrees"], -10)
        self.assertEqual(framing_advice([self.candidate(0, 300)], 1280)["turn_degrees"], 10)
        self.assertEqual(framing_advice([self.candidate(500, 780)], 1280)["status"], "centered")
        self.assertEqual(framing_advice([self.candidate(0, 1280)], 1280)["status"], "partial")

    def test_no_arbitrary_choice_between_matches_or_low_scores(self):
        self.assertEqual(framing_advice([], 1280)["status"], "not_found")
        self.assertEqual(framing_advice([self.candidate(0, 300, .3)], 1280)["status"], "not_found")
        self.assertEqual(framing_advice([self.candidate(0, 300), self.candidate(800, 1200)], 1280)["status"], "ambiguous")

    def test_empty_completed_response_is_valid_not_found(self):
        boxes, masks = decode_response({"status": "completed", "output": []}, (1280, 720))
        self.assertEqual((boxes, masks), ({}, {}))

    def test_incomplete_response_is_not_used_for_motion(self):
        with self.assertRaises(ValueError):
            decode_response({"status": "incomplete", "output": []}, (1280, 720))


if __name__ == "__main__":
    unittest.main()
