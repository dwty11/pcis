"""Entry-point cp1251 coverage for verify.sh and run_demo.sh.

Companion to test_start_demo_cp1251.py. Same principle: drive the REAL reader-facing scripts
under a forced Russian-locale (cp1251) console — not their inline python, not the underlying
functions. The cp1251 class slipped through twice because functions were tested while the script
paths stayed broken; these guard the scripts a first-time reader actually runs.

cp1251 is forced without editing the scripts: a sitecustomize.py on PYTHONPATH makes bare open()
default to cp1251 for every python the script spawns.
"""
import os
import shutil
import subprocess
import textwrap

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="verify.sh / run_demo.sh are bash entry points (POSIX shells only)",
)


def _seed_tree(base_dir):
    """A tree this test owns, with non-ASCII content — the thing cp1251 breaks.

    Previously these tests read the repo's own data/tree.json. That file is
    GITIGNORED and absent from a fresh clone, so the test was red for a stranger
    and green here only because a working tree happens to have it: an undeclared
    precondition on `bash setup.sh`.
    """
    import sys as _sys
    _sys.path.insert(0, os.path.join(REPO, "core"))
    import knowledge_tree as kt

    data = os.path.join(str(base_dir), "data")
    os.makedirs(data, exist_ok=True)
    tree = {"branches": {}, "root_hash": ""}
    # non-ASCII on purpose: an em-dash and Cyrillic are what a bare open()
    # mis-decodes under cp1251. An all-ASCII fixture would pass either way.
    kt.add_knowledge(tree, "technical",
                     "Ретенция записей — семь лет, по регламенту.",
                     source="cp1251-fixture", confidence=0.9)
    kt.add_knowledge(tree, "lessons",
                     "Audit logs are immutable — verified quarterly.",
                     source="cp1251-fixture", confidence=0.85)
    kt.save_tree(tree, os.path.join(data, "tree.json"))
    return str(base_dir)


def _cp1251_env(tmp_path, base_dir=None):
    (tmp_path / "sitecustomize.py").write_text(textwrap.dedent("""
        import builtins
        _open = builtins.open
        def _win_open(file, mode="r", buffering=-1, encoding=None, *a, **k):
            if "b" not in mode and encoding is None:
                encoding = "cp1251"            # Russian-locale Windows default
            return _open(file, mode, buffering, encoding, *a, **k)
        builtins.open = _win_open
    """), encoding="utf-8")
    # PCIS_* is STRIPPED, not inherited. dict(os.environ) let a PCIS_BASE_DIR
    # set by an earlier test flow into this subprocess, so in a full run this
    # asserted against whatever tree that test left behind rather than the one
    # under test — it passed for a reason unrelated to what it verifies.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PCIS_")}
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", "")
    if base_dir is not None:
        env["PCIS_BASE_DIR"] = str(base_dir)
    return env


def _run(script_args, env, timeout=90):
    return subprocess.run(["bash", *script_args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=timeout)


def test_verify_sh_reports_untampered_under_cp1251(tmp_path):
    """verify.sh's CLEAN/TAMPERED verdict rides on `pcis verify` ->
    knowledge_tree.load_tree. A bare read anywhere on that chain mis-decodes
    non-ASCII content under cp1251 and flips CLEAN -> false TAMPERED (the
    original bug report). This asserts the entry point stays CLEAN.

    Runs against a tree THIS TEST seeds, under an isolated PCIS_BASE_DIR. The
    earlier version read the repo's data/tree.json and called it "committed";
    it is neither committed nor present in a fresh clone."""
    base = _seed_tree(tmp_path / "repo_base")
    r = _run(["verify.sh"], _cp1251_env(tmp_path, base_dir=base))
    assert r.returncode == 0, f"verify.sh exited {r.returncode} under cp1251:\n{r.stdout}\n{r.stderr}"
    assert "✗ TAMPERED" not in r.stdout, (
        f"verify.sh reported TAMPERED on a clean tree under a cp1251 console:\n{r.stdout}"
    )
    assert "✓ Untampered" in r.stdout, f"verify.sh did not confirm Untampered:\n{r.stdout}"


def test_run_demo_replay_has_no_mojibake_under_cp1251(tmp_path):
    """The replay is functionally robust to a mis-decode (it matches the plant by ASCII leaf-id
    and shows the root from stored hashes), so the verdict survives. But a bare read of any
    fixture renders its non-ASCII content as cp1251 mojibake — the load-bearing verification note
    would show garbage to an RU reader. "вЂ" is the cp1251 rendering of a UTF-8 em-dash
    (bytes 0xE2 0x80 …), i.e. the mis-decode signature; it must not appear."""
    r = _run(["demo/advocate-demo/run_demo.sh"], _cp1251_env(tmp_path))  # replay: no tree needed
    assert r.returncode == 0, f"run_demo.sh exited {r.returncode} under cp1251:\n{r.stdout}\n{r.stderr}"
    assert "The claim MOVED under challenge" in r.stdout, f"replay did not render its verdict:\n{r.stdout}"
    assert "вЂ" not in r.stdout, (
        "run_demo.sh replay shows cp1251 mojibake — a fixture is read with a bare open() and its "
        f"non-ASCII content (em-dashes in the verification note) mis-decodes:\n{r.stdout[:1500]}"
    )
