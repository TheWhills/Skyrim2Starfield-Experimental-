import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "interior_acceptance",
    Path(__file__).resolve().parents[1] / "scripts" / "oracles" / "interior_acceptance.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def observation(result="pass", kind="game", evidence="stood on the floor for 6s; no fall"):
    return {"result": result, "kind": kind, "evidence": evidence}


def pinned(**overrides):
    doc = {
        "revision": "a" * 40,
        "build_id": "staging-multi-1",
        "installed": [{"path": "Data/FO4Port.esm", "sha256": "ab" * 32}],
        "startup": observation(evidence="game reached the menu and loaded the plugin"),
        "single_model": observation(evidence="one transplanted stair spawned and did not crash the session"),
        "rollback": observation(evidence="uninstall removed the plugin and the game started clean"),
        "cells": {},
    }
    for name in oracle.CELLS:
        doc["cells"][name] = {criterion: observation() for criterion in oracle.CRITERIA}
    doc.update(overrides)
    return doc


class InteriorAcceptanceTests(unittest.TestCase):
    def test_pinned_game_evidence_is_the_only_pass(self):
        result = oracle.audit(pinned())
        self.assertFalse(oracle.failed(result))
        self.assertEqual(len(result["passed"]), len(oracle.GATES) + len(oracle.CELLS) * len(oracle.CRITERIA))
        self.assertEqual(result["unverified"], [])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["errors"], [])

    def test_missing_cell_stays_unverified(self):
        doc = pinned()
        del doc["cells"]["Parsons"]
        result = oracle.audit(doc)
        self.assertTrue(oracle.failed(result))
        self.assertEqual(len(result["unverified"]), len(oracle.CRITERIA))
        self.assertTrue(all(row.startswith("Parsons:") for row in result["unverified"]))
        self.assertNotIn("Parsons: walkable", result["passed"])

    def test_offline_parse_cannot_close_a_game_criterion(self):
        doc = pinned()
        doc["cells"]["Vault 111"]["walkable"] = observation(kind="offline", evidence="mesh round-trip matched")
        result = oracle.audit(doc)
        self.assertTrue(oracle.failed(result))
        self.assertIn("Vault 111: walkable: offline result cannot close a game criterion", result["errors"])
        self.assertIn("Vault 111: walkable", result["unverified"])
        self.assertNotIn("Vault 111: walkable", result["passed"])

    def test_unpinned_or_empty_pass_is_rejected(self):
        for doc in (
            pinned(revision="ABC" + "a" * 37),
            pinned(build_id="  "),
            pinned(installed=[]),
            pinned(installed=[{"path": "C:/Games/FO4Port.esm", "sha256": "ab" * 32}]),
            pinned(installed=[{"path": "Data/FO4Port.esm", "sha256": "AB" * 32}]),
        ):
            result = oracle.audit(doc)
            self.assertTrue(result["errors"])
            self.assertEqual(result["passed"], [])
        doc = pinned()
        doc["rollback"] = observation(evidence="  ")
        result = oracle.audit(doc)
        self.assertIn("rollback: evidence text required", result["errors"])
        self.assertNotIn("rollback", result["passed"])

    def test_machine_path_in_evidence_cannot_close_a_row(self):
        doc = pinned()
        win = "C:" + "\\Users\\someone\\shot.png"
        home = "/home" + "/someone/shot.png"
        doc["cells"]["Parsons"]["door_swing"] = observation(evidence="both sides opened; " + win)
        result = oracle.audit(doc)
        self.assertTrue(oracle.failed(result))
        self.assertIn("Parsons: door_swing", result["unverified"])
        self.assertNotIn("Parsons: door_swing", result["passed"])
        self.assertTrue(any("machine path" in error for error in result["errors"]))
        doc["cells"]["Parsons"]["door_swing"] = observation(evidence="both sides opened; " + home)
        result = oracle.audit(doc)
        self.assertIn("Parsons: door_swing", result["unverified"])
        doc["cells"]["Parsons"]["door_swing"] = observation(
            evidence="both sides opened; see C:\\Users\\<user>\\shot.png")
        result = oracle.audit(doc)
        self.assertIn("Parsons: door_swing", result["passed"])
        # a placeholder earlier in the note does not hide a later real path
        doc["cells"]["Parsons"]["door_swing"] = observation(
            evidence="see C:\\Users\\<user>\\shot.png and " + win)
        result = oracle.audit(doc)
        self.assertIn("Parsons: door_swing", result["unverified"])
        self.assertNotIn("Parsons: door_swing", result["passed"])

    def test_failure_is_not_counted_as_verified(self):
        doc = pinned()
        doc["startup"] = observation(result="fail", evidence="process exited before the menu")
        doc["cells"]["Hotel Rexford"]["door_swing"] = {"result": "unverified", "kind": "game",
                                                       "evidence": "not aimed this session"}
        result = oracle.audit(doc)
        self.assertEqual(result["failures"], [{"check": "startup", "evidence": "process exited before the menu"}])
        self.assertIn("Hotel Rexford: door_swing", result["unverified"])
        self.assertTrue(oracle.failed(result))

    def test_malformed_documents_cannot_pass(self):
        for doc in (None, [], {"cells": {"Somewhere": {}}}, {"cells": {"Vault 111": {"glow": observation()}}}):
            result = oracle.audit(doc)
            self.assertTrue(result["errors"])
            self.assertTrue(oracle.failed(result))
            self.assertEqual(result["passed"], [])
