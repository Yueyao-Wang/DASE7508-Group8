import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lab import CONDITIONS, CONTAMINATED_RULE, NotesStore, OllamaChoice, Scenario
from lab import run_trial, simulated_choice, write_json
from run_experiment import summarize


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)

    def matched(self, profile, choose=simulated_choice, pre=1, delay=2):
        scenario = Scenario(profile, pre, delay, 1, 7508)
        return [run_trial(self.root / condition, scenario, condition, choose, 4)
                for condition in CONDITIONS]

    def audit(self, condition):
        return [json.loads(line) for line in
                (self.root / condition / "audit.jsonl").read_bytes().splitlines()]

    def test_paired_incident_and_restore(self):
        clean, exposed, recovered = self.matched("immediate_and_persistent")
        self.assertEqual([r["immediate_math"] for r in (clean, exposed, recovered)], [0, 1, 1])
        self.assertEqual([r["replay_math"] for r in (clean, exposed, recovered)], [0, 4, 0])
        self.assertEqual([r["replay_success"] for r in (clean, exposed, recovered)], [4, 0, 4])
        self.assertEqual([r["residual"] for r in (clean, exposed, recovered)], [0, 1, 0])
        self.assertEqual([r["lost_progress"] for r in (clean, exposed, recovered)], [0, 0, 4])
        self.assertEqual(recovered["delay_math"], 2)
        self.assertIn(CONTAMINATED_RULE, json.loads(
            (self.root / "C1" / "state.json").read_bytes())["memory"])
        audit = self.audit("C2")
        rollback_idx = next(i for i, item in enumerate(audit) if item["event"] == "rollback")
        self.assertEqual(self.audit("C1")[:rollback_idx], audit[:rollback_idx])
        self.assertEqual([item["seq"] for item in audit], list(range(1, len(audit) + 1)))
        def replay_inputs(events):
            return [{key: value for key, value in item.items() if key != "seq"}
                    for item in events if item["phase"] == "evaluation"]

        baseline_replay = replay_inputs([item for item in self.audit("C0")
                                         if item["event"] == "tool_response"])
        for arm in CONDITIONS:
            responses = [item for item in self.audit(arm) if item["event"] == "tool_response"]
            self.assertTrue(all(item["fixture"] is None for item in responses
                                if item["phase"] in ("delay", "evaluation")))
            self.assertEqual(replay_inputs(responses), baseline_replay)
        restored = self.root / "C2"
        self.assertEqual((restored / "checkpoint.json").read_bytes(),
                         (restored / "evaluation_start.json").read_bytes())
        self.assertTrue(summarize([clean, exposed, recovered])[1]["recovery_pass"])

    def test_delayed_effect_without_immediate_math_change(self):
        _, exposed, recovered = self.matched("persistent_only", delay=0)
        self.assertEqual(exposed["immediate_math"], 0)
        self.assertEqual(exposed["memory_written"], 1)
        self.assertEqual(exposed["replay_math"], 4)
        self.assertEqual(recovered["replay_math"], 0)

    def test_rejected_incident_and_unnecessary_rollback_cost(self):
        clean, exposed, recovered = self.matched("rejected", pre=3, delay=0)
        self.assertEqual(clean["replay_success"], exposed["replay_success"])
        self.assertEqual(exposed["incident_success"], 0)
        self.assertEqual(recovered["lost_progress"], 4)

    def test_failed_utility_does_not_pass_zero_baseline(self):
        def wrong_choice(topic, options, answer, seed):
            return 3 - answer, {"choice": 3 - answer}

        rows = self.matched("rejected", wrong_choice)
        metrics, outcome = summarize(rows)
        self.assertEqual(metrics[0]["TSR"], 0)
        self.assertIsNone(metrics[2]["LPL"])
        self.assertIsNone(outcome["recovery_pass"])

    def test_tampered_checkpoint_fails_closed(self):
        store = NotesStore(self.root / "trial")
        digest = store.checkpoint()
        before = store.load()
        write_json(store.checkpoint_path, {"memory": ["changed"]})
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            store.rollback(digest)
        self.assertEqual(store.load(), before)

    @patch("lab.urllib.request.build_opener")
    def test_llm_interface_returns_only_a_choice(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({
            "model": "local-test", "response": '{"choice": 2}',
        })
        selected, details = OllamaChoice("local-test")("拟人", ["甲", "乙"], 1, 9)
        request = opener.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(payload["options"]["seed"], 9)
        self.assertEqual(selected, 2)
        self.assertEqual(details["model"], "local-test")
        response.read.return_value = '{"response":"invalid JSON"}'
        self.assertIsNone(OllamaChoice("local-test")("拟人", ["甲", "乙"], 1, 9)[0])


if __name__ == "__main__":
    unittest.main()
