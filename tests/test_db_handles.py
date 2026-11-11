"""A command that opens a search index must close it before it returns.

D114, found on the real AH531 (Windows 11). `nemo datasheet`, `nemo story
refs` and the offline readiness list each opened a SQLite index and never
closed it. Linux lets you delete an open file, so nothing showed. Windows
does not: the index stayed locked for the life of the process, and six
tests failed when their temporary folder could not be removed. In the
desktop interface, which is one long-lived process, the same lock outlives
the command that took it.

These record every connection a command opens and ask each one afterwards
whether it is closed, so they fail on the old code on any platform.
"""
from __future__ import annotations

import io, os, sqlite3, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import cli
from nemo.config import Config
from nemo.parts import PartsLibrary


def is_closed(conn) -> bool:
    try:
        conn.execute("select 1")
        return False
    except sqlite3.ProgrammingError:
        return True


class HandleCase(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, _sandbox.home_env(self.t.name))
        self._env.start()
        self.opened = []
        real = sqlite3.connect

        def spy(*a, **k):
            conn = real(*a, **k)
            self.opened.append(conn)
            return conn
        self._spy = mock.patch("sqlite3.connect", spy)
        self._spy.start()

    def tearDown(self):
        self._spy.stop(); self._env.stop()
        for conn in self.opened:
            conn.close()
        # On Windows this is itself the test: an open index cannot be removed.
        self.t.cleanup()

    def run_cli(self, *a):
        with redirect_stdout(io.StringIO()):
            try:
                return cli.main(list(a))
            except SystemExit as e:
                return e.code

    def assert_all_closed(self):
        self.assertTrue(self.opened, "the command never opened an index at all")
        self.assertEqual([is_closed(c) for c in self.opened],
                         [True] * len(self.opened))


class TestDatasheets(HandleCase):
    def test_list(self):
        self.run_cli("datasheet", "list")
        self.assert_all_closed()

    def test_search(self):
        self.run_cli("datasheet", "search", "voltage")
        self.assert_all_closed()


class TestOfflineReadiness(HandleCase):
    def test_readiness_closes_the_datasheet_index(self):
        from nemo import offline
        offline.readiness(Config.load(Path("/nonexistent")), PartsLibrary.load())
        self.assert_all_closed()


if __name__ == "__main__":
    unittest.main(verbosity=2)
