"""Commands that need a name, given none (2026-11-06, samples through the
remaining departments): they said "There is no None in the Theatre", "no
story called None", "no '' in the Storeroom", or, for the Narrator, that "the
story has no chapters written yet". Each now asks which one, and says where
the list is."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import cli


class TestWhichOne(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.t.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(list(argv))
        return rc, out.getvalue()

    def test_each_asks_which_and_never_says_none(self):
        for argv, which in ((["theatre", "check"], "Which one?"),
                            (["theatre", "play"], "Which one?"),
                            (["store", "remove"], "Which part?"),
                            (["store", "take"], "Which part?"),
                            (["film", "make"], "Which story?"),
                            (["film", "plan"], "Which story?"),
                            (["games", "play"], "Which game?"),
                            (["audio", "narrate"], "Which story?")):
            rc, text = self.run_cli(*argv)
            self.assertEqual(rc, 1, argv)
            self.assertIn(which, text, argv)
            self.assertNotIn("None", text, argv)
            self.assertNotIn("''", text, argv)

    def test_a_story_that_is_not_there_is_said_so(self):
        rc, text = self.run_cli("audio", "narrate", "no-such-story")
        self.assertEqual(rc, 1)
        self.assertIn("no story called 'no-such-story'", text)
        self.assertNotIn("no chapters written", text)


if __name__ == "__main__":
    unittest.main()
