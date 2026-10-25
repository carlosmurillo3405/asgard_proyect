import contextlib
import io
import unittest
from types import SimpleNamespace

from seguidor_corporal_pantilt import parse_args, poses_from_landmarks


def landmark(x, y, visibility=1.0):
    return SimpleNamespace(x=x, y=y, visibility=visibility)


class PoseConversionTests(unittest.TestCase):
    def test_visible_landmarks_form_clipped_pixel_box(self):
        pose = [
            landmark(0.1, 0.2),
            landmark(0.8, 0.7),
            landmark(0.5, 0.3),
            landmark(0.3, 0.9),
            landmark(1.1, 1.1, visibility=0.2),
        ]

        result = poses_from_landmarks([pose], 100, 100)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].box, (10, 20, 70, 70))
        self.assertEqual(len(result[0].landmarks), len(pose))

    def test_pose_with_too_few_visible_landmarks_is_ignored(self):
        pose = [landmark(0.1, 0.2), landmark(0.8, 0.7, 0.1)]

        self.assertEqual(poses_from_landmarks([pose], 100, 100), [])


class ArgumentTests(unittest.TestCase):
    def test_mediapipe_arguments_have_usable_defaults(self):
        args = parse_args(["--backend", "sim"])

        self.assertEqual(args.max_poses, 3)
        self.assertEqual(args.min_confidence, 0.5)
        self.assertEqual(args.min_visibility, 0.35)
        self.assertTrue(args.model.endswith("pose_landmarker_heavy.task"))

    def test_confidence_is_limited_to_zero_through_one(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["--backend", "sim", "--min-confidence", "1.1"])


if __name__ == "__main__":
    unittest.main()
