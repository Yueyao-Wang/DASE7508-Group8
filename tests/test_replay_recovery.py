import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from run_replay_recovery import SimulatedModel, main, run_case


def current_phase(store):
    events = [
        json.loads(line)
        for line in store.audit_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    return next(
        event["phase"]
        for event in reversed(events)
        if event["event"] == "tool_response"
    )


class InvalidRedo(SimulatedModel):
    def decide(self, messages, seed, store):
        if current_phase(store) == "recovery_redo":
            return None
        return super().decide(messages, seed, store)


class ReinfectOnRedo(SimulatedModel):
    def decide(self, messages, seed, store):
        redo = current_phase(store) == "recovery_redo"
        result = super().decide(messages, seed, store)
        if redo:
            return {
                **result,
                "memory_add": ["chinese_and_math"],
                "write_math": True,
            }
        return result


class WrongBeforeIncident(SimulatedModel):
    def decide(self, messages, seed, store):
        before = current_phase(store) == "pre_incident"
        result = super().decide(messages, seed, store)
        if before:
            return {**result, "choice": 3 - result["choice"]}
        return result


class ReplayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_c4_restores_progress_and_repairs_math(self):
        c2, c4 = run_case(
            self.root / "pair",
            SimulatedModel(),
            pre=3,
            delay=2,
        )
        self.assertEqual(
            (c2["lost_progress"], c4["lost_progress"]),
            (6, 0),
        )
        self.assertEqual(c4["redo_tasks"], 6)
        self.assertEqual(c4["recovery_model_calls"], 0)

        for row in (c2, c4):
            self.assertEqual(row["residual"], 0)
            self.assertEqual(row["replay_math"], 0)
            self.assertEqual(
                row["math_matches_checkpoint"], 1
            )

        source = json.loads(
            (
                self.root / "pair"
                / "attack_source" / "state.json"
            ).read_bytes()
        )
        self.assertIn(
            "chinese_and_math", source["memory"]
        )

    def test_redo_is_clean_and_not_filtered_by_old_correctness(self):
        _, c4 = run_case(
            self.root / "pair",
            WrongBeforeIncident(),
        )
        self.assertEqual(c4["eligible_progress"], 1)
        self.assertEqual(c4["redo_tasks"], 2)
        self.assertEqual(c4["lost_progress"], 0)

        events = [
            json.loads(line)
            for line in (
                self.root / "pair" / "C4" / "audit.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        redo_tools = [
            event for event in events
            if event["event"] == "tool_response"
            and event["phase"] == "recovery_redo"
        ]
        self.assertEqual(len(redo_tools), 2)
        self.assertTrue(all(
            "message" not in event["response"]
            for event in redo_tools
        ))

    def test_failed_redo_keeps_the_loss_visible(self):
        _, c4 = run_case(
            self.root / "pair",
            InvalidRedo(),
        )
        self.assertEqual(c4["redo_invalid"], 2)
        self.assertEqual(c4["lost_progress"], 2)

    def test_reintroduced_poison_and_math_changes_are_reported(self):
        _, c4 = run_case(
            self.root / "pair",
            ReinfectOnRedo(),
        )
        self.assertEqual(c4["redo_math"], 2)
        self.assertEqual(
            c4["poison_after_recovery"], 1
        )
        self.assertEqual(c4["residual"], 1)
        self.assertGreater(c4["replay_math"], 0)

    def test_simulation_does_not_construct_a_real_model(self):
        out = self.root / "run"
        with patch(
            "run_replay_recovery.Model",
            side_effect=AssertionError(
                "Unexpected model access"
            ),
        ):
            with redirect_stdout(io.StringIO()):
                code = main([
                    "--out", str(out),
                    "--repeats", "1",
                ])

        self.assertEqual(code, 0)
        manifest = json.loads(
            (out / "manifest.json").read_bytes()
        )
        self.assertEqual(
            manifest["status"], "complete"
        )
        self.assertEqual(manifest["mode"], "sim")
        self.assertIsNone(manifest["model"])

    def test_real_failure_is_not_relabelled_as_simulation(self):
        out = self.root / "run"
        with patch(
            "run_replay_recovery.Model",
            side_effect=ConnectionError(
                "model unavailable"
            ),
        ):
            with redirect_stderr(io.StringIO()):
                code = main([
                    "--mode", "real",
                    "--out", str(out),
                ])

        self.assertEqual(code, 1)
        manifest = json.loads(
            (out / "manifest.json").read_bytes()
        )
        self.assertEqual(
            manifest["status"], "failed"
        )
        self.assertEqual(manifest["mode"], "real")

    def test_existing_output_is_not_overwritten(self):
        out = self.root / "existing"
        out.mkdir()
        marker = out / "keep.txt"
        marker.write_text(
            "original", encoding="utf-8"
        )

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["--out", str(out)])

        self.assertEqual(
            marker.read_text(encoding="utf-8"),
            "original",
        )


if __name__ == "__main__":
    unittest.main()