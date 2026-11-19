import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from lab import NotesStore
from run_real_agent import POISON, evaluate, fork_store, prefix, task, validate
from run_real_agent import attribution, remove_poison_memory
from run_real_agent import main
from run_real_agent import SYSTEM_V2


class ScriptedModel:
    """Test double only. Its responses never count as LLM evidence."""

    def __init__(self):
        self.messages = []

    def decide(self, messages, seed, store):
        self.messages.append(copy.deepcopy(messages))
        state = json.loads(messages[-1]["content"].split("当前持久状态为 ", 1)[1].split("。请输出")[0])
        tool = json.loads(messages[3]["content"])
        poisoned = "message" in tool or POISON in state["memory"]
        return {"choice": 1, "write_math": poisoned,
                "memory_add": [POISON] if "message" in tool else []}


class RealAgentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_persistent_state_drives_model_input_and_recovery(self):
        model = ScriptedModel()
        exposed, digest, valid, meta = prefix(
            self.root / "C1", model, 7508, 1, 0, "authorization")
        recovered = fork_store(exposed, self.root / "C2")
        self.assertEqual(exposed.audit_path.read_bytes(), recovered.audit_path.read_bytes())
        recovered.rollback(digest)
        before = len(model.messages)
        c1 = evaluate(exposed, model, 7508, 1, 0, 2, valid, meta)
        c2 = evaluate(recovered, model, 7508, 1, 0, 2, valid, meta)
        self.assertEqual(c1["replay_math"], 2)
        self.assertEqual(c2["replay_math"], 0)
        self.assertEqual(c1["residual"], 1)
        self.assertEqual(c2["residual"], 0)
        self.assertGreater(c2["lost_progress"], 0)
        for messages in model.messages[before:]:
            self.assertNotIn("message", json.loads(messages[3]["content"]))
        self.assertEqual(recovered.checkpoint_path.read_bytes(),
                         (recovered.state_path.parent / "evaluation_start.json").read_bytes())

    def test_model_rejection_leaves_math_and_memory_clean(self):
        class Reject:
            def decide(self, messages, seed, store):
                return {"choice": 1, "memory_add": [], "write_math": False}
        store = NotesStore(self.root / "reject")
        task(store, Reject(), 1, 1, "incident_window", "authorization")
        self.assertEqual(store.load()["memory"], [])
        self.assertEqual(store.load()["notes"]["Math"], {"initial": "2 + 2 = 4"})

    def test_ablation_changes_only_poison_rule_and_preserves_branch(self):
        model = ScriptedModel()
        exposed, _, valid, meta = prefix(
            self.root / "C1", model, 7508, 1, 0, "authorization")
        before = exposed.load()
        ablated = fork_store(exposed, self.root / "C3")
        remove_poison_memory(ablated)
        self.assertEqual(ablated.load()["notes"], before["notes"])
        self.assertEqual(exposed.load(), before)
        self.assertNotIn(POISON, ablated.load()["memory"])
        c1 = evaluate(exposed, model, 7508, 1, 0, 2, valid, meta)
        c3 = evaluate(ablated, model, 7508, 1, 0, 2, valid, meta)
        self.assertEqual((c1["replay_math"], c3["replay_math"]), (2, 0))
        self.assertEqual(c3["lost_progress"], 0)

    def test_preexisting_poison_is_not_counted_as_new_attack_poison(self):
        class Prepoison:
            def decide(self, messages, seed, store):
                return {"choice": 1, "memory_add": [POISON], "write_math": False}
        _, _, _, meta = prefix(self.root / "trial", Prepoison(), 7508, 1, 0, "authorization")
        self.assertEqual(meta["memory_written"], 0)
        self.assertEqual(meta["pre_attack_poison"], 1)
        rows = [{"scenario": "s", "condition": arm, **meta} for arm in ("C0", "C1")]
        result = attribution(rows)[0]
        self.assertFalse(result["attack_attribution_eligible"])
        self.assertFalse(result["attack_memory_evidence"])

    def test_cli_writes_four_arms_and_attribution(self):
        output = self.root / "run"
        argv = ["run_real_agent.py", "--memory-ablation", "--attack", "authorization",
                "--repeats", "1", "--replay", "2", "--out", str(output)]
        with patch("sys.argv", argv), patch("run_real_agent.Model", return_value=ScriptedModel()):
            main()
        manifest = json.loads((output / "manifest.json").read_bytes())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["trials"], 4)
        self.assertEqual(len((output / "metrics.csv").read_text().splitlines()), 5)
        self.assertIn("memory_removal_UMR_difference",
                      (output / "attribution.csv").read_text())

    def test_invalid_output_causes_no_writes(self):
        class Invalid:
            def decide(self, messages, seed, store):
                return None
        store = NotesStore(self.root / "invalid")
        before = store.load()
        _, correct, changed, invalid = task(store, Invalid(), 1, 1, "evaluation")
        self.assertEqual(store.load(), before)
        self.assertEqual((correct, changed, invalid), (False, False, True))

    def test_validation_rejects_wrong_types(self):
        self.assertIsNone(validate('{"choice":true,"memory_add":[],"write_math":false}'))
        self.assertIsNone(validate('{"choice":1,"memory_add":["unknown"],"write_math":false}'))
        self.assertIsNone(validate('not json'))
        self.assertIsNotNone(validate('{"choice":1,"memory_add":[],"write_math":false}'))

    def test_prompt_version_is_used_in_actual_model_messages(self):
        model = ScriptedModel()
        model.system_prompt = SYSTEM_V2
        store = NotesStore(self.root / "prompt")
        task(store, model, 1, 1, "warmup")
        self.assertEqual(model.messages[0][0]["content"], SYSTEM_V2)


if __name__ == "__main__":
    unittest.main()
