"""Windows-portability probes for the Advocate Demo replay path.

These reproduce, ON A UNIX HOST, the ways a real Windows clone breaks — by BLOCKING
the Unix-only modules and FORCING Windows default encodings BEFORE any project module
is imported, then importing / running the replay path in a fresh subprocess.

Why a fresh subprocess with forced conditions: prior verification ran replay on a real
macOS interpreter, which has `fcntl` and UTF-8 I/O, so every Windows wall was invisible
by construction (the check assumed the very thing it was meant to test). These probes
remove that assumption — they fail on a Unix host exactly where Windows fails.

Walls reproduced:
  #1 import — `import fcntl` (core/knowledge_tree.py, core/knowledge_synapses.py) is Unix-only.
  #2 files  — unqualified open() defaults to cp1252 on Windows; UTF-8 fixtures mojibake.
  #3 stdout — a cp1252 console cannot encode the demo's box-drawing -> UnicodeEncodeError.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADV = os.path.join(REPO, "demo", "advocate-demo")

# Runs in a FRESH subprocess. argv: <mode> <repo> <tmpdir>. Installs the Windows
# conditions BEFORE importing anything from the project.
_BOOT = r'''
import sys, os, builtins, io, runpy
mode, REPO, TMP = sys.argv[1], sys.argv[2], sys.argv[3]
ADV = os.path.join(REPO, "demo", "advocate-demo")

# Wall #1 -- the Unix-only modules are unimportable on Windows.
for _m in ("fcntl", "termios", "pwd", "grp", "resource"):
    sys.modules[_m] = None

if mode in ("console", "files"):
    # Wall #2 -- Windows default encoding for unqualified text open() is cp1252.
    _orig_open = builtins.open
    def _win_open(file, mode="r", buffering=-1, encoding=None, *a, **k):
        if "b" not in mode and encoding is None:
            encoding = "cp1252"
        return _orig_open(file, mode, buffering, encoding, *a, **k)
    builtins.open = _win_open

if mode == "console":
    # Wall #3 -- a cp1252 console cannot encode box-drawing/emoji (strict -> crash).
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="cp1252",
                                  errors="strict", line_buffering=True)
elif mode == "files":
    # Isolate wall #2: UTF-8 console so a bad read shows as WRONG TEXT, not a crash.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="strict", line_buffering=True)

sys.path.insert(0, os.path.join(REPO, "core"))
sys.path.insert(0, ADV)

if mode == "import":
    import knowledge_tree       # the reported failure site
    import knowledge_synapses   # the second, unnamed fcntl site
    import verdict              # pulls belief_traversal
    print("IMPORT-OK")
elif mode == "write":
    import json
    import knowledge_tree as kt
    out = os.path.join(TMP, "tree.json")
    tree = kt.load_tree(out)                     # no file yet -> fresh empty tree
    kt.add_knowledge(tree, "technical", "x beats y", confidence=0.7)
    kt.save_tree(tree, out)                      # exercises the (now-guarded) flock
    with open(out, encoding="utf-8") as f:
        ok, errs = kt.verify_tree_integrity(json.load(f))
    print("WRITE-OK" if ok else "WRITE-FAIL:" + repr(errs))
else:  # console / files -> run the actual demo
    sys.argv = ["replay.py"]
    runpy.run_path(os.path.join(ADV, "replay.py"), run_name="__main__")
'''


def _run(mode, tmp_path):
    boot = tmp_path / "winboot.py"
    boot.write_text(_BOOT)
    return subprocess.run(
        [sys.executable, str(boot), mode, REPO, str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )


def test_import_survives_without_unix_modules(tmp_path):
    """Wall #1: the replay import chain survives with fcntl (and friends) absent."""
    r = _run("import", tmp_path)
    assert r.returncode == 0, "import path died with Unix-only modules blocked:\n" + r.stderr
    assert "IMPORT-OK" in r.stdout


def test_save_tree_writes_atomically_without_fcntl(tmp_path):
    """Option A degradation: with fcntl absent, save_tree still writes a valid tree
    (atomic os.replace; advisory lock is simply skipped)."""
    r = _run("write", tmp_path)
    assert r.returncode == 0, "save_tree failed without fcntl:\n" + r.stderr
    assert "WRITE-OK" in r.stdout, r.stdout + r.stderr


def test_replay_survives_cp1252_console(tmp_path):
    """Walls #1+#3: replay runs and prints the money shot on a cp1252 console."""
    r = _run("console", tmp_path)
    assert r.returncode == 0, "replay crashed on a cp1252 console:\n" + r.stderr
    assert "net-under-challenge 0.85" in r.stdout
    assert "CONFIDENT" in r.stdout


def test_replay_reads_utf8_fixtures_on_windows_default_encoding(tmp_path):
    """Wall #2: with cp1252 as the default open() encoding, UTF-8 fixture content
    still decodes correctly instead of mojibaking."""
    r = _run("files", tmp_path)
    assert r.returncode == 0, r.stderr
    # This token is printed from the memory-note fixture; it mojibakes under cp1252.
    assert "Case prep — Delgado matter" in r.stdout, (
        "fixture content mojibaked — an unqualified open() read UTF-8 as cp1252")
