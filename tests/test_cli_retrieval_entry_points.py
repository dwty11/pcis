"""test_cli_retrieval_entry_points.py — the three retrieval-side `pcis`
subcommands, driven as real subprocesses.

WHY THIS FILE EXISTS
====================
Three shipped subcommands raised on every invocation, none covered:

  * `pcis search` — core/knowledge_search.py:307 yields 3-tuples
    (score, leaf_id, leaf_data); pcis/cli.py:168 unpacked two, and
    :169 read leaf['id'], a key index entries do not carry.
  * `pcis proof`  — pcis/cli.py:205 imported `generate_inclusion_proof`,
    a name knowledge_tree does not define (the real one is
    `generate_proof(tree, branch, leaf_id)`, which also needs the branch
    and raises ValueError rather than returning None).
  * `pcis assess` — pcis/cli.py:226/228 printed `effective_confidence`
    and `challenge_count`; assess_belief returns `net_confidence` and
    `contradiction_count` (core/belief_traversal.py:197-209).

These run the installed entry point via `python -m pcis.cli`, matching
tests/test_cli.py, so the argparse dispatch is covered too — a defect at
import time (the `proof` ImportError) is only reachable this way.

`search` additionally needs the one external dependency stubbed (an
Ollama HTTP embed call). It is stubbed via a `sitecustomize.py` on
PYTHONPATH — the same forced-condition-in-a-real-subprocess technique
tests/test_scripts_cp1251.py uses — so the CLI itself is never modified
for testability, and the real search() code path executes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

CLI = [sys.executable, "-m", "pcis.cli"]

LEAF_CONTENT = "Retrieval provenance is not answer provenance"
LEAF_BRANCH = "lessons"
VECTOR = [0.5, 0.25, 0.125, 0.0625]


def _run(args, base_dir, extra_env=None):
    """Run the CLI as a real subprocess. Returns (stdout, stderr, rc)."""
    env = dict(os.environ)
    env["PCIS_BASE_DIR"] = str(base_dir)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        CLI + ["--dir", str(base_dir)] + args,
        capture_output=True, text=True, cwd=_ROOT, env=env,
    )
    return proc.stdout, proc.stderr, proc.returncode


@pytest.fixture
def seeded(tmp_path):
    """A tree with one known leaf. Returns (base_dir, leaf_id)."""
    import knowledge_tree as kt

    data = tmp_path / "data"
    data.mkdir()
    tree = {"branches": {}, "root_hash": ""}
    leaf_id = kt.add_knowledge(
        tree, LEAF_BRANCH, LEAF_CONTENT, source="test", confidence=0.9
    )
    kt.save_tree(tree, str(data / "tree.json"))
    return tmp_path, leaf_id


@pytest.fixture
def seeded_with_index(seeded):
    """As `seeded`, plus a real search index and a sitecustomize stub that
    replaces ONLY the Ollama embed call. Returns (base_dir, leaf_id, env)."""
    import knowledge_tree as kt

    base, leaf_id = seeded
    saved = kt.load_tree(str(base / "data" / "tree.json"))
    leaf = saved["branches"][LEAF_BRANCH]["leaves"][0]
    index = {
        "model": "nomic-embed-text",
        "dimensions": len(VECTOR),
        "created": leaf["created"],
        "last_reindex": leaf["created"],
        "leaf_count": 1,
        "embeddings": {
            leaf_id: {
                "branch": LEAF_BRANCH,
                "content": leaf["content"],
                "source": leaf["source"],
                "confidence": leaf["confidence"],
                "created": leaf["created"],
                "vector": list(VECTOR),
            }
        },
    }
    (base / "data" / "search-index.json").write_text(
        json.dumps(index), encoding="utf-8"
    )

    stub_dir = base / "_stub"
    stub_dir.mkdir()
    # PCIS_BASE_DIR is already exported by _run, so knowledge_search resolves
    # INDEX_FILE correctly at import time here.
    (stub_dir / "sitecustomize.py").write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {os.path.join(_ROOT, 'core')!r})\n"
        "import knowledge_search\n"
        f"knowledge_search.get_embedding = lambda text, model=None: {VECTOR!r}\n",
        encoding="utf-8",
    )
    env = {"PYTHONPATH": os.pathsep.join([str(stub_dir), _ROOT])}
    return base, leaf_id, env


class TestSearch:
    def test_prints_leaf_id_and_content(self, seeded_with_index):
        base, leaf_id, env = seeded_with_index

        out, err, rc = _run(["search", LEAF_CONTENT], base, env)

        assert rc == 0, f"pcis search exited {rc}\nstdout:{out}\nstderr:{err}"
        assert "Traceback" not in err
        assert "Found 1 result(s)" in out
        assert leaf_id[:12] in out
        assert LEAF_CONTENT in out

    def test_reports_no_results_for_unmatched_query(self, seeded_with_index):
        """min_score gates on cosine similarity; an orthogonal query vector
        must produce the clean 'No results' path, not a crash."""
        base, _leaf_id, env = seeded_with_index
        stub = base / "_stub" / "sitecustomize.py"
        stub.write_text(
            stub.read_text(encoding="utf-8").replace(
                f"lambda text, model=None: {VECTOR!r}",
                "lambda text, model=None: [-0.5, 0.25, -0.125, 0.0625]",
            ),
            encoding="utf-8",
        )

        out, err, rc = _run(["search", "utterly unrelated"], base, env)

        assert rc == 0, f"stderr:{err}"
        assert "Traceback" not in err
        assert "No results found." in out


class TestProof:
    def test_emits_verifiable_inclusion_proof(self, seeded):
        base, leaf_id = seeded

        out, err, rc = _run(["proof", leaf_id], base)

        assert rc == 0, f"pcis proof exited {rc}\nstdout:{out}\nstderr:{err}"
        assert "Traceback" not in err
        proof = json.loads(out)
        assert proof["leaf_id"] == leaf_id
        assert proof["branch"] == LEAF_BRANCH

        # The emitted proof must actually verify with the shipped verifier.
        from knowledge_tree import verify_proof

        assert verify_proof(
            proof["leaf_hash"], proof["proof"], proof["branch_root"]
        ) is True

    def test_missing_leaf_exits_nonzero_without_traceback(self, seeded):
        base, _leaf_id = seeded

        out, err, rc = _run(["proof", "no-such-leaf-id"], base)

        assert rc != 0
        assert "Traceback" not in err, f"should fail cleanly, got:\n{err}"
        assert "not found" in (out + err).lower()


class TestAssess:
    def test_prints_stance_and_net_confidence(self, seeded):
        base, leaf_id = seeded

        out, err, rc = _run(["assess", leaf_id], base)

        assert rc == 0, f"pcis assess exited {rc}\nstdout:{out}\nstderr:{err}"
        assert "Traceback" not in err
        assert "KeyError" not in err
        assert f"Leaf: {leaf_id[:12]}" in out
        assert "Stance: CONFIDENT" in out
        # 0.9 with no challengers -> net == base
        assert "0.900" in out
        assert "Supporters: 0" in out
        assert "Challengers: 0" in out

    def test_unknown_leaf_reports_not_found(self, seeded):
        base, _leaf_id = seeded

        out, err, rc = _run(["assess", "no-such-leaf-id"], base)

        assert "Traceback" not in err, f"should degrade cleanly, got:\n{err}"
        assert "NOT_FOUND" in out
