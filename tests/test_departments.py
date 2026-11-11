"""The six departments (owner, 2026-10-21).

The owner's words: "each department works alone but writer will have role in
all departments, designer in the computer lab and art studio for 3d models
for printing", with the Designer kept in the Workshop too, and five
employees added to save the model work. These tests hold the roster to
what was agreed, and the steps, the window and the work log to it.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import review, staff, steps


def titles(dept: str) -> list[str]:
    return [e.title for e in staff.team(dept)]


class TestTheRoster(unittest.TestCase):
    def test_sixteen_departments(self):
        # The Storeroom, the Theatre, Gaming and the Doctors were asked for
        # the same day, after the first four.
        self.assertEqual([d.name for d in staff.DEPARTMENTS.values()],
                         ["Library", "Art Studio", "Workshop", "Computer Lab", "Storeroom",
                          "Theatre", "Gaming", "Music Room", "Audio", "Test Bench", "Print Shop", "Film Studio", "Home", "Communications", "Science", "Doctors",
                          "Game Studio"])

    def test_each_team(self):
        self.assertEqual(titles("library"), ["Researcher", "Writer", "Artist", "Linguist", "Editor",
                                             "Archivist", "Foreman", "Timekeeper"])
        self.assertEqual(titles("art_studio"), ["Writer", "Artist", "Designer", "Editor",
                                                "Clerk", "Foreman", "Timekeeper"])
        self.assertEqual(titles("workshop"), ["Researcher", "Writer", "Designer", "Inspector",
                                              "Clerk", "Datasheet Reader", "Second Opinion", "PCB Designer",
                                              "Woodworker", "Foreman", "Timekeeper"])
        self.assertEqual(titles("computer_lab"), ["Writer", "Designer", "Coder", "Tester",
                                                  "Technician", "Reverse Engineer", "Quality Inspector",
                                                  "Foreman", "Timekeeper"])
        self.assertEqual(titles("storeroom"), ["Storekeeper", "Writer", "Researcher"])
        self.assertTrue(staff.STAFF["storeroom.storekeeper"].working)

    def test_the_writer_is_in_every_department(self):
        for d in staff.DEPARTMENTS:
            self.assertIn("Writer", titles(d), d)

    def test_the_designer_makes_models_in_three(self):
        have = [d for d in staff.DEPARTMENTS if "Designer" in titles(d)]
        self.assertEqual(have, ["art_studio", "workshop", "computer_lab"])
        for d in ("art_studio", "computer_lab"):
            self.assertIn("3D", staff.STAFF[f"{d}.designer"].job)

    def test_a_key_is_department_and_role(self):
        for key, e in staff.STAFF.items():
            self.assertEqual(key.split(".")[0], e.department, key)
            self.assertIn(e.department, staff.DEPARTMENTS, key)

    def test_the_speed_jobs_working_only_where_built(self):
        # Said plainly, so nothing claims a job is done before it is. The
        # Library's three were built when it was gone through (2026-10-21),
        # the Art Studio's three on 2026-10-22.
        built = {"library.timekeeper", "library.archivist", "library.foreman",
                 "workshop.foreman", "workshop.timekeeper", "workshop.clerk",
                 "computer_lab.technician",
                 "art_studio.foreman", "art_studio.timekeeper", "art_studio.clerk"}
        for title in ("Timekeeper", "Archivist", "Foreman", "Clerk", "Technician"):
            found = [e for e in staff.STAFF.values() if e.title == title]
            self.assertTrue(found, title)
            for e in found:
                self.assertEqual(e.working, e.key in built, e.key)
                self.assertFalse(e.steps, e.key)

    def test_every_employee_s_tools_are_checked(self):
        # Gone through department by department (2026-10-21); an employee
        # added later must say what it needs too (nemo/toolkit.py).
        from nemo import toolkit
        self.assertEqual(set(staff.STAFF) - set(toolkit.NEEDS), set())
        self.assertEqual(set(toolkit.NEEDS) - set(staff.STAFF), set())
        for key, needs in toolkit.NEEDS.items():
            built = not any("not built yet" in n.check(None)[1] for n in needs
                            if n.name == "its job")
            self.assertEqual(built, staff.STAFF[key].working, key)

    def test_an_unknown_department_says_which_there_are(self):
        with self.assertRaises(KeyError) as cm:
            staff.team("kitchen")
        self.assertIn("workshop", str(cm.exception))


class TestTheSteps(unittest.TestCase):
    def test_who_does_each_step(self):
        self.assertEqual({s.key: staff.owner(s.key).label for s in steps.STEPS}, {
            "brief": "Workshop Writer", "parts": "Workshop Designer",
            "electrical": "Workshop Designer", "wiring": "Workshop Designer",
            "concept": "Art Studio Artist", "enclosure": "Workshop Designer",
            "firmware": "Computer Lab Coder", "pack": "Workshop Writer"})

    def test_only_working_employees_own_steps(self):
        for s in steps.STEPS:
            self.assertTrue(staff.owner(s.key).working, s.key)

    def test_every_inspector_stop_names_an_employee(self):
        # review._stop's second argument is a STAFF key; an old bare key
        # ("designer") would fail here rather than in the window.
        src = (Path(review.__file__)).read_text(encoding="utf-8")
        import re
        keys = re.findall(r'_stop\([^,]+, "([a-z_.]+)"', src)
        self.assertTrue(keys)
        for k in keys:
            self.assertIn(k, staff.STAFF, k)


class TestTheWorkLog(unittest.TestCase):
    def test_a_line_says_the_department(self):
        with tempfile.TemporaryDirectory() as t:
            review.record(Path(t), "concept", "started")
            review.record(Path(t), "no-such-step", "reviewed")
            lines = [json.loads(l) for l in
                     (Path(t) / ".nemo" / "work.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((lines[0]["who"], lines[0]["department"]), ("Artist", "Art Studio"))
        self.assertEqual((lines[1]["who"], lines[1]["department"]), ("Inspector", "Workshop"))


if __name__ == "__main__":
    unittest.main()
