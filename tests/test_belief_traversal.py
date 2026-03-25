#!/usr/bin/env python3
"""Tests for belief_traversal.py"""

import pytest
from core.belief_traversal import assess_belief, SUPPORT_WEIGHT, CONTRADICTION_WEIGHT, DEPTH_DECAY


def _make_tree(leaves_by_branch):
    """Build a minimal tree dict from {branch: [leaf_dicts]}."""
    branches = {}
    for branch, leaves in leaves_by_branch.items():
        branches[branch] = {
            "hash": "test",
            "leaves": leaves,
        }
    return {"version": 1, "branches": branches}


def _make_leaf(lid, content="test leaf", confidence=0.8):
    return {
        "id": lid,
        "hash": "h_" + lid,
        "content": content,
        "source": "test",
        "confidence": confidence,
        "created": "2026-01-01",
        "promoted_to": None,
    }


def _make_synapses(edges):
    """Build synapses dict from list of (from, to, relation) tuples."""
    synapses_list = []
    for i, edge in enumerate(edges):
        from_leaf, to_leaf, relation = edge[:3]
        synapses_list.append({
            "id": f"syn_{i}",
            "from_leaf": from_leaf,
            "to_leaf": to_leaf,
            "relation": relation,
            "note": "",
            "source": "test",
            "created": "2026-01-01",
            "hash": f"hash_{i}",
        })
    return {"version": 1, "synapses": synapses_list}


class TestNoSynapses:
    def test_base_confidence_returned(self):
        tree = _make_tree({"phil": [_make_leaf("a1", confidence=0.85)]})
        synapses = _make_synapses([])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        assert result["net_confidence"] == 0.85
        assert result["base_confidence"] == 0.85

    def test_stance_confident(self):
        tree = _make_tree({"phil": [_make_leaf("a1", confidence=0.85)]})
        synapses = _make_synapses([])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        assert result["stance"] == "CONFIDENT"

    def test_stance_uncertain_low_base(self):
        tree = _make_tree({"phil": [_make_leaf("a1", confidence=0.50)]})
        synapses = _make_synapses([])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        assert result["stance"] == "UNCERTAIN"

    def test_reasoning_string(self):
        tree = _make_tree({"phil": [_make_leaf("a1", confidence=0.70)]})
        synapses = _make_synapses([])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        assert "No supporting or contradicting evidence" in result["reasoning"]
        assert "0.70" in result["reasoning"]


class TestSupports:
    def test_support_raises_confidence(self):
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.80),
            _make_leaf("a2", confidence=0.90),
        ]})
        synapses = _make_synapses([("a2", "a1", "SUPPORTS")])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        expected = 0.80 + 0.90 * SUPPORT_WEIGHT
        assert result["net_confidence"] == pytest.approx(expected, abs=1e-6)
        assert result["support_count"] == 1

    def test_multiple_supports(self):
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.60),
            _make_leaf("a2", confidence=0.80),
            _make_leaf("a3", confidence=0.90),
        ]})
        synapses = _make_synapses([
            ("a2", "a1", "SUPPORTS"),
            ("a3", "a1", "SUPPORTS"),
        ])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        expected = 0.60 + 0.80 * SUPPORT_WEIGHT + 0.90 * SUPPORT_WEIGHT
        assert result["net_confidence"] == pytest.approx(expected, abs=1e-6)
        assert result["support_count"] == 2


class TestContradicts:
    def test_contradiction_lowers_confidence(self):
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.80),
            _make_leaf("c1", confidence=0.70),
        ]})
        synapses = _make_synapses([("c1", "a1", "CONTRADICTS")])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        expected = 0.80 - 0.70 * CONTRADICTION_WEIGHT
        assert result["net_confidence"] == pytest.approx(expected, abs=1e-6)
        assert result["contradiction_count"] == 1

    def test_contested_threshold(self):
        """Contradicted + net < 0.7 = CONTESTED."""
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.70),
            _make_leaf("c1", confidence=0.90),
        ]})
        synapses = _make_synapses([("c1", "a1", "CONTRADICTS")])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        # net = 0.70 - 0.90*0.15 = 0.70 - 0.135 = 0.565
        assert result["net_confidence"] < 0.7
        assert result["contradiction_count"] > 0
        assert result["stance"] == "CONTESTED"


class TestSupersedes:
    def test_superseded_stance(self):
        tree = _make_tree({"phil": [
            _make_leaf("old1", confidence=0.95),
            _make_leaf("new1", confidence=0.90),
        ]})
        synapses = _make_synapses([("new1", "old1", "SUPERSEDES")])
        result = assess_belief("old1", tree=tree, synapses=synapses)
        assert result["stance"] == "SUPERSEDED"
        assert result["superseded"] is True
        assert "superseded" in result["reasoning"].lower()

    def test_superseded_ignores_confidence(self):
        """Even with perfect confidence, superseded = SUPERSEDED."""
        tree = _make_tree({"phil": [
            _make_leaf("old1", confidence=1.0),
            _make_leaf("new1", confidence=0.50),
        ]})
        synapses = _make_synapses([("new1", "old1", "SUPERSEDES")])
        result = assess_belief("old1", tree=tree, synapses=synapses)
        assert result["stance"] == "SUPERSEDED"


class TestDepthLimit:
    def test_depth_respected(self):
        """Chain: a1 <- a2 <- a3 <- a4. With max_depth=2, a4 should not be reached."""
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.60),
            _make_leaf("a2", confidence=0.80),
            _make_leaf("a3", confidence=0.80),
            _make_leaf("a4", confidence=0.80),
        ]})
        synapses = _make_synapses([
            ("a2", "a1", "SUPPORTS"),
            ("a3", "a2", "SUPPORTS"),
            ("a4", "a3", "SUPPORTS"),
        ])
        result_depth2 = assess_belief("a1", tree=tree, synapses=synapses, max_depth=2)
        result_depth3 = assess_belief("a1", tree=tree, synapses=synapses, max_depth=3)

        # At depth 2, only a2 (depth 1) and a3 (depth 2) contribute
        expected_d2 = (0.60
                       + 0.80 * SUPPORT_WEIGHT * DEPTH_DECAY ** 0
                       + 0.80 * SUPPORT_WEIGHT * DEPTH_DECAY ** 1)
        assert result_depth2["net_confidence"] == pytest.approx(expected_d2, abs=1e-6)
        assert result_depth2["depth_reached"] == 2

        # At depth 3, a4 also contributes
        expected_d3 = expected_d2 + 0.80 * SUPPORT_WEIGHT * DEPTH_DECAY ** 2
        assert result_depth3["net_confidence"] == pytest.approx(expected_d3, abs=1e-6)


class TestCycleSafety:
    def test_cycle_no_infinite_loop(self):
        """A SUPPORTS B SUPPORTS A — must not loop forever."""
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.80),
            _make_leaf("a2", confidence=0.70),
        ]})
        synapses = _make_synapses([
            ("a1", "a2", "SUPPORTS"),
            ("a2", "a1", "SUPPORTS"),
        ])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        # Should complete without hanging; a2 supports a1
        expected = 0.80 + 0.70 * SUPPORT_WEIGHT
        assert result["net_confidence"] == pytest.approx(expected, abs=1e-6)
        assert result["support_count"] == 1


class TestNotFound:
    def test_missing_leaf(self):
        tree = _make_tree({"phil": [_make_leaf("a1")]})
        synapses = _make_synapses([])
        result = assess_belief("nonexistent", tree=tree, synapses=synapses)
        assert result["stance"] == "NOT_FOUND"
        assert result["net_confidence"] == 0.0
        assert "not found" in result["reasoning"].lower()


class TestWeakRelations:
    def test_refines_half_weight(self):
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.70),
            _make_leaf("a2", confidence=0.80),
        ]})
        synapses = _make_synapses([("a2", "a1", "REFINES")])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        expected = 0.70 + 0.80 * SUPPORT_WEIGHT * 0.5
        assert result["net_confidence"] == pytest.approx(expected, abs=1e-6)

    def test_derives_from_half_weight(self):
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.70),
            _make_leaf("a2", confidence=0.80),
        ]})
        synapses = _make_synapses([("a2", "a1", "DERIVES_FROM")])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        expected = 0.70 + 0.80 * SUPPORT_WEIGHT * 0.5
        assert result["net_confidence"] == pytest.approx(expected, abs=1e-6)


class TestClamping:
    def test_clamp_to_one(self):
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.95),
            _make_leaf("a2", confidence=1.0),
            _make_leaf("a3", confidence=1.0),
            _make_leaf("a4", confidence=1.0),
        ]})
        synapses = _make_synapses([
            ("a2", "a1", "SUPPORTS"),
            ("a3", "a1", "SUPPORTS"),
            ("a4", "a1", "SUPPORTS"),
        ])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        assert result["net_confidence"] <= 1.0

    def test_clamp_to_zero(self):
        tree = _make_tree({"phil": [
            _make_leaf("a1", confidence=0.10),
            _make_leaf("c1", confidence=1.0),
            _make_leaf("c2", confidence=1.0),
        ]})
        synapses = _make_synapses([
            ("c1", "a1", "CONTRADICTS"),
            ("c2", "a1", "CONTRADICTS"),
        ])
        result = assess_belief("a1", tree=tree, synapses=synapses)
        assert result["net_confidence"] >= 0.0
