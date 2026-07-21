"""A user's first claim must never land in the PCIS source repo's data/ tree.

That directory is demo/working space in a clone — and, on a maintainer's machine, a
real substrate. Running `pcis init`/`add` from the repo root with no explicit base
(no --dir, no PCIS_BASE_DIR) must refuse and point the user at a home of their own,
never write the repo tree. An explicit base always works.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args, cwd, extra_env=None, drop_base=False):
    env = {k: v for k, v in os.environ.items()}
    if drop_base:
        env.pop("PCIS_BASE_DIR", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, "-m", "pcis.cli", *args],
                          capture_output=True, text=True, cwd=cwd, env=env, timeout=30)


def test_init_refuses_in_source_repo_without_explicit_base():
    r = _run(["init"], cwd=REPO, drop_base=True)
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"init must refuse in the source repo:\n{out}"
    assert "PCIS_BASE_DIR" in out, "must tell the user how to point PCIS elsewhere"


def test_add_refuses_in_source_repo_without_explicit_base():
    r = _run(["add", "technical", "some claim"], cwd=REPO, drop_base=True)
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"add must refuse in the source repo:\n{out}"
    assert "PCIS_BASE_DIR" in out


def test_init_creates_tree_in_explicit_dir(tmp_path):
    r = _run(["--dir", str(tmp_path), "init"], cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "data" / "tree.json").exists()


def test_init_honors_explicit_pcis_base_dir(tmp_path):
    r = _run(["init"], cwd=REPO, extra_env={"PCIS_BASE_DIR": str(tmp_path)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "data" / "tree.json").exists()
