#!/usr/bin/env python3
"""Tests for core/action_log.py — belief-linked action log with outcome feedback."""

import json
import os
import subprocess
import sys

import pytest

# Make core/ + pcis/ importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


# -----------------------------------------------------------------------
# Fixture — minimal tree at <tmp>/data/tree.json with one belief leaf
# in branch 'lessons' at confidence 0.7. Journal path also set up.
# -----------------------------------------------------------------------


@pytest.fixture
def tmp_action(tmp_path, monkeypatch):
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    from knowledge_tree import (
        DEFAULT_BRANCHES,
        add_knowledge,
        compute_branch_hash,
        compute_root_hash,
        now_utc,
    )

    tree = {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": "",
        "instance": "action-test",
        "branches": {},
    }
    for branch in DEFAULT_BRANCHES:
        tree["branches"][branch] = {"hash": "", "leaves": []}

    leaf_id = add_knowledge(tree, "lessons", "Always verify before trusting",
                             confidence=0.7)

    for bname in tree["branches"]:
        tree["branches"][bname]["hash"] = compute_branch_hash(
            tree["branches"][bname]["leaves"]
        )
    tree["root_hash"] = compute_root_hash(tree)

    tree_path = data_dir / "tree.json"
    with open(tree_path, "w") as f:
        json.dump(tree, f, indent=2)

    return {
        "base": tmp_path,
        "data": data_dir,
        "tree_path": str(tree_path),
        "journal_path": str(data_dir / "action_log.jsonl"),
        "belief_id": leaf_id,
        "initial_confidence": 0.7,
    }


def _read_tree(tree_path):
    with open(tree_path, "r") as f:
        return json.load(f)


def _find_leaf(tree, leaf_id):
    for branch in tree["branches"].values():
        for leaf in branch.get("leaves", []):
            if leaf["id"] == leaf_id:
                return leaf
    return None


# -----------------------------------------------------------------------
# 1. emit_action — basic event shape
# -----------------------------------------------------------------------


def test_emit_action_returns_valid_event(tmp_action):
    from action_log import emit_action

    ev = emit_action(
        agent_id="gardener",
        tool_name="adversarial_pass",
        parameters_summary="gap_scan=False",
        belief_id=tmp_action["belief_id"],
        journal_path=tmp_action["journal_path"],
    )

    assert ev["event_id"]
    assert ev["event_type"] == "ACTION_STARTED"
    assert ev["agent_id"] == "gardener"
    assert ev["tool_name"] == "adversarial_pass"
    assert ev["parameters_summary"] == "gap_scan=False"
    assert ev["belief_id"] == tmp_action["belief_id"]
    assert ev["prev_event_hash"] is None  # first event
    assert ev["event_hash"]
    assert len(ev["event_hash"]) == 64


# -----------------------------------------------------------------------
# 2. record_outcome — finds STARTED, creates COMPLETED with action_id
# -----------------------------------------------------------------------


def test_record_outcome_links_to_started(tmp_action):
    from action_log import emit_action, record_outcome

    started = emit_action(
        agent_id="gardener",
        tool_name="adversarial_pass",
        journal_path=tmp_action["journal_path"],
    )

    completed = record_outcome(
        action_id=started["event_id"],
        outcome_severity=0.4,
        agent_id="gardener",
        description="completed cleanly",
        journal_path=tmp_action["journal_path"],
    )

    assert completed["event_type"] == "ACTION_COMPLETED"
    assert completed["action_id"] == started["event_id"]
    assert completed["event_id"] != started["event_id"]
    assert completed["outcome_severity"] == 0.4
    assert completed["prev_event_hash"] == started["event_hash"]


def test_record_outcome_unknown_action_id_raises(tmp_action):
    from action_log import record_outcome

    with pytest.raises(ValueError):
        record_outcome(
            action_id="does-not-exist",
            outcome_severity=0.5,
            agent_id="gardener",
            journal_path=tmp_action["journal_path"],
        )


# -----------------------------------------------------------------------
# 3. Good outcome (severity=0.1) boosts confidence
# -----------------------------------------------------------------------


def test_good_outcome_boosts_belief_confidence(tmp_action):
    from action_log import emit_action, record_outcome

    started = emit_action(
        agent_id="gardener",
        tool_name="adversarial_pass",
        belief_id=tmp_action["belief_id"],
        journal_path=tmp_action["journal_path"],
    )

    completed = record_outcome(
        action_id=started["event_id"],
        outcome_severity=0.1,
        agent_id="gardener",
        journal_path=tmp_action["journal_path"],
    )

    # Confidence should boost from 0.7 to 0.73 (cap 0.98)
    tree = _read_tree(tmp_action["tree_path"])
    leaf = _find_leaf(tree, tmp_action["belief_id"])
    assert leaf["confidence"] == pytest.approx(0.73, abs=1e-6)
    assert completed["confidence_delta"] == pytest.approx(0.03, abs=1e-6)
    assert completed["counter_leaf_id"] is None


# -----------------------------------------------------------------------
# 4. Bad outcome (severity=0.7) penalizes confidence
# -----------------------------------------------------------------------


def test_bad_outcome_penalizes_belief_confidence(tmp_action):
    from action_log import emit_action, record_outcome

    started = emit_action(
        agent_id="gardener",
        tool_name="adversarial_pass",
        belief_id=tmp_action["belief_id"],
        journal_path=tmp_action["journal_path"],
    )

    completed = record_outcome(
        action_id=started["event_id"],
        outcome_severity=0.7,
        agent_id="gardener",
        journal_path=tmp_action["journal_path"],
    )

    # 0.7 -> 0.7 - (0.10 * 0.7) = 0.63
    tree = _read_tree(tmp_action["tree_path"])
    leaf = _find_leaf(tree, tmp_action["belief_id"])
    assert leaf["confidence"] == pytest.approx(0.63, abs=1e-6)
    assert completed["confidence_delta"] == pytest.approx(-0.07, abs=1e-6)
    assert completed["counter_leaf_id"] is None  # 0.7 not > 0.8


# -----------------------------------------------------------------------
# 5. Catastrophic outcome (severity=0.9) generates COUNTER leaf
# -----------------------------------------------------------------------


def test_catastrophic_outcome_generates_counter_leaf(tmp_action):
    from action_log import emit_action, record_outcome

    started = emit_action(
        agent_id="gardener",
        tool_name="adversarial_pass",
        belief_id=tmp_action["belief_id"],
        journal_path=tmp_action["journal_path"],
    )

    completed = record_outcome(
        action_id=started["event_id"],
        outcome_severity=0.9,
        agent_id="gardener",
        description="catastrophic regression — staging dropped under load",
        journal_path=tmp_action["journal_path"],
    )

    # Confidence penalty: 0.7 -> 0.7 - (0.10 * 0.9) = 0.61
    tree = _read_tree(tmp_action["tree_path"])
    leaf = _find_leaf(tree, tmp_action["belief_id"])
    assert leaf["confidence"] == pytest.approx(0.61, abs=1e-6)

    # Counter leaf must exist in the same branch as the original belief
    assert completed["counter_leaf_id"] is not None
    counter_leaf = _find_leaf(tree, completed["counter_leaf_id"])
    assert counter_leaf is not None
    # Should be in the 'lessons' branch (same as the original belief)
    found_branch = None
    for bname, bdata in tree["branches"].items():
        if any(l["id"] == completed["counter_leaf_id"] for l in bdata.get("leaves", [])):
            found_branch = bname
    assert found_branch == "lessons"
    # Content should reference the belief id and severity
    assert tmp_action["belief_id"] in counter_leaf["content"]
    assert "0.9" in counter_leaf["content"]
    assert counter_leaf["confidence"] == 0.65


# -----------------------------------------------------------------------
# 6. Neutral outcome (severity=0.4) leaves confidence unchanged
# -----------------------------------------------------------------------


def test_neutral_outcome_leaves_confidence_unchanged(tmp_action):
    from action_log import emit_action, record_outcome

    started = emit_action(
        agent_id="gardener",
        tool_name="adversarial_pass",
        belief_id=tmp_action["belief_id"],
        journal_path=tmp_action["journal_path"],
    )

    completed = record_outcome(
        action_id=started["event_id"],
        outcome_severity=0.4,
        agent_id="gardener",
        journal_path=tmp_action["journal_path"],
    )

    tree = _read_tree(tmp_action["tree_path"])
    leaf = _find_leaf(tree, tmp_action["belief_id"])
    assert leaf["confidence"] == pytest.approx(0.7, abs=1e-6)
    assert completed["confidence_delta"] == 0.0
    assert completed["counter_leaf_id"] is None


# -----------------------------------------------------------------------
# 7. load_action_log — empty/missing file → []
# -----------------------------------------------------------------------


def test_load_action_log_missing_file_returns_empty(tmp_action):
    from action_log import load_action_log

    nonexistent = str(tmp_action["base"] / "no" / "such" / "log.jsonl")
    assert not os.path.exists(nonexistent)
    assert load_action_log(nonexistent) == []


# -----------------------------------------------------------------------
# 8. verify_chain — intact chain
# -----------------------------------------------------------------------


def test_verify_chain_passes_on_intact_log(tmp_action):
    from action_log import emit_action, record_outcome, verify_chain

    a = emit_action(
        agent_id="gardener", tool_name="adversarial_pass",
        journal_path=tmp_action["journal_path"],
    )
    record_outcome(
        action_id=a["event_id"], outcome_severity=0.2, agent_id="gardener",
        journal_path=tmp_action["journal_path"],
    )

    result = verify_chain(tmp_action["journal_path"])
    assert result["valid"] is True
    assert result["length"] == 2
    assert result["broken_at"] is None


# -----------------------------------------------------------------------
# 9. Tamper detection — modified event hash
# -----------------------------------------------------------------------


def test_tamper_detection_marks_chain_invalid(tmp_action):
    from action_log import emit_action, record_outcome, verify_chain

    a = emit_action(
        agent_id="gardener", tool_name="adversarial_pass",
        journal_path=tmp_action["journal_path"],
    )
    record_outcome(
        action_id=a["event_id"], outcome_severity=0.2, agent_id="gardener",
        journal_path=tmp_action["journal_path"],
    )

    # Tamper: rewrite event 0 with a wrong stored event_hash
    with open(tmp_action["journal_path"], "r") as f:
        lines = f.readlines()
    ev = json.loads(lines[0])
    ev["event_hash"] = "0" * 64
    lines[0] = json.dumps(ev) + "\n"
    with open(tmp_action["journal_path"], "w") as f:
        f.writelines(lines)

    result = verify_chain(tmp_action["journal_path"])
    assert result["valid"] is False
    assert result["broken_at"] == 0


# -----------------------------------------------------------------------
# 10. CLI actions list — subprocess, exit 0
# -----------------------------------------------------------------------


def test_cli_actions_list_subprocess(tmp_action):
    from action_log import emit_action, record_outcome

    a = emit_action(
        agent_id="gardener", tool_name="adversarial_pass",
        journal_path=tmp_action["journal_path"],
    )
    record_outcome(
        action_id=a["event_id"], outcome_severity=0.2, agent_id="gardener",
        journal_path=tmp_action["journal_path"],
    )

    cli_script = os.path.join(_ROOT, "pcis", "cli.py")
    result = subprocess.run(
        [sys.executable, cli_script, "--dir", str(tmp_action["base"]),
         "actions", "list"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "STARTED" in result.stdout
    assert "COMPLETED" in result.stdout


# -----------------------------------------------------------------------
# 11. CLI actions verify-chain — subprocess on valid log, exit 0
# -----------------------------------------------------------------------


def test_cli_actions_verify_chain_subprocess(tmp_action):
    from action_log import emit_action, record_outcome

    a = emit_action(
        agent_id="gardener", tool_name="adversarial_pass",
        journal_path=tmp_action["journal_path"],
    )
    record_outcome(
        action_id=a["event_id"], outcome_severity=0.2, agent_id="gardener",
        journal_path=tmp_action["journal_path"],
    )

    cli_script = os.path.join(_ROOT, "pcis", "cli.py")
    result = subprocess.run(
        [sys.executable, cli_script, "--dir", str(tmp_action["base"]),
         "actions", "verify-chain"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "Chain valid" in result.stdout
    assert "True" in result.stdout
