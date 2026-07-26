"""test_boot_manifest.py — the boot tab must be able to detect what it claims.

Found by a cold read (2026-07-26), third instance of one shape: a caption
attached to a value it is not derived from.

The explainer said each tracked file "is rehashed and compared against the
stored manifest". No manifest existed. server.py appended a literal
``"status": "OK"`` whose only alternative was ``MISSING``, so a tampered file
displayed a changed hash beside a green tick. "Cryptographic tamper detection"
that structurally cannot detect tampering, on the tab named for integrity.

These tests hold the boot path to the sentence it prints.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


@pytest.fixture
def boot(tmp_path, monkeypatch):
    """A demo dir the test owns, so the shipped files are never touched."""
    from demo import server

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    # a real, self-consistent tree
    import knowledge_tree as kt

    tree = {"branches": {}, "root_hash": ""}
    kt.add_knowledge(tree, "technical", "a tracked claim", source="t", confidence=0.8)
    tree_path = demo_dir / "demo_tree.json"
    kt.save_tree(tree, str(tree_path))

    for name in ("server.py", "index.html"):
        (demo_dir / name).write_text(f"contents of {name}\n", encoding="utf-8")

    monkeypatch.setattr(server, "DEMO_DIR", str(demo_dir))
    monkeypatch.setattr(server, "DEMO_TREE_FILE", str(tree_path))
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    return server.app.test_client(), demo_dir


def _write_manifest(demo_dir, files=("server.py", "index.html", "demo_tree.json")):
    entries = {}
    for name in files:
        p = demo_dir / name
        entries[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (demo_dir / "demo_manifest.json").write_text(
        json.dumps({"files": entries}, indent=2), encoding="utf-8"
    )
    return entries


class TestManifestComparison:
    def test_untampered_files_read_ok(self, boot):
        client, demo_dir = boot
        _write_manifest(demo_dir)

        data = client.get("/api/boot").get_json()

        assert {f["status"] for f in data["file_checks"]} == {"OK"}
        assert data["status"] == "CLEAN"

    def test_tampered_file_is_flagged(self, boot):
        """The whole point: a changed byte must change the status, not just the
        displayed hash."""
        client, demo_dir = boot
        _write_manifest(demo_dir)
        (demo_dir / "index.html").write_text("tampered!\n", encoding="utf-8")

        data = client.get("/api/boot").get_json()

        flagged = [f for f in data["file_checks"] if f["file"] == "index.html"]
        assert flagged and flagged[0]["status"] == "MODIFIED", data["file_checks"]
        assert data["status"] == "MODIFIED", (
            "a tampered tracked file must move the overall status, not sit "
            "under a green tick"
        )

    def test_missing_file_still_flagged(self, boot):
        client, demo_dir = boot
        _write_manifest(demo_dir)
        (demo_dir / "index.html").unlink()

        data = client.get("/api/boot").get_json()

        statuses = {f["file"]: f["status"] for f in data["file_checks"]}
        assert statuses["index.html"] == "MISSING"
        assert data["status"] == "MODIFIED"

    def test_absent_manifest_never_reads_OK(self, boot):
        """No manifest means nothing was compared. Say so; do not imply a pass."""
        client, demo_dir = boot

        data = client.get("/api/boot").get_json()

        assert {f["status"] for f in data["file_checks"]} == {"NO_MANIFEST"}, (
            "with nothing to compare against, a green OK is the original bug"
        )
        assert data["manifest_present"] is False

    def test_file_absent_from_manifest_is_untracked_not_ok(self, boot):
        client, demo_dir = boot
        _write_manifest(demo_dir, files=("server.py", "demo_tree.json"))

        data = client.get("/api/boot").get_json()

        statuses = {f["file"]: f["status"] for f in data["file_checks"]}
        assert statuses["index.html"] == "UNTRACKED"


class TestUnverifiableIsItsOwnState:
    """Nothing compared is not the same as nothing wrong.

    The first fix set files_ok=False in the MISSING and MODIFIED branches and
    missed NO_MANIFEST and UNTRACKED, so three "? NO MANIFEST" lines sat under
    a glowing green CLEAN — the same defect, in the same function, as the one
    the fix was for. And CLEAN was the wrong word regardless: an unverifiable
    check has not passed, and calling it a failure is equally untrue.
    """

    def test_absent_manifest_is_unverifiable_not_clean(self, boot):
        client, demo_dir = boot

        data = client.get("/api/boot").get_json()

        assert data["status"] == "UNVERIFIABLE", (
            "zero files compared to anything must not render as CLEAN"
        )

    def test_untracked_file_is_unverifiable_not_clean(self, boot):
        client, demo_dir = boot
        _write_manifest(demo_dir, files=("server.py", "demo_tree.json"))

        data = client.get("/api/boot").get_json()

        assert data["status"] == "UNVERIFIABLE"

    def test_a_real_failure_outranks_unverifiable(self, boot):
        """A definite mismatch is worse news than an absent comparison."""
        client, demo_dir = boot
        _write_manifest(demo_dir, files=("server.py", "demo_tree.json"))
        (demo_dir / "server.py").write_text("tampered\n", encoding="utf-8")

        data = client.get("/api/boot").get_json()

        assert data["status"] == "MODIFIED", (
            "index.html is UNTRACKED and server.py is MODIFIED — the failure wins"
        )


class TestBootRootIsLabelledHonestly:
    def test_root_is_reported_as_stored_and_as_recomputed(self, boot):
        """The terminal claimed the root was 'computed from N file hashes'.

        It is neither computed at boot nor a function of the file hashes. Both
        values are now served so the caption can name which is which.
        """
        client, demo_dir = boot
        _write_manifest(demo_dir)

        data = client.get("/api/boot").get_json()

        assert "merkle_root_stored" in data
        assert "merkle_root_recomputed" in data
        assert data["merkle_root_stored"] == data["merkle_root_recomputed"], (
            "fixture tree is self-consistent"
        )


class TestHeadlineDerivationIsSafeByConstruction:
    """The headline claim, made executable.

    A comment said an unrecognised per-file status "falls through to
    UNVERIFIABLE, which is the safe direction". Six lines below it,
    ``else: status = "CLEAN"`` did the opposite — so a status nobody had
    classified landed on glowing green CLEAN, the exact failure of the two
    previous rounds, inside the fix meant to make it impossible.

    Tested against the pure function rather than through the route, so
    invented statuses can be fed in directly.
    """

    def test_unknown_file_status_is_unverifiable(self):
        """The invariant the comment asserts. Named by INVARIANT() in server.py."""
        from demo.server import _boot_headline

        assert _boot_headline({"OK", "UNREADABLE"}, tree_ok=True) == "UNVERIFIABLE"
        assert _boot_headline({"STALE"}, tree_ok=True) == "UNVERIFIABLE"
        assert _boot_headline({"SOMETHING_INVENTED_LATER"}, tree_ok=True) == "UNVERIFIABLE"

    def test_clean_requires_every_status_to_be_known_good(self):
        from demo.server import _boot_headline

        assert _boot_headline({"OK"}, tree_ok=True) == "CLEAN"
        assert _boot_headline(set(), tree_ok=True) == "CLEAN"  # nothing tracked

    def test_definite_failure_outranks_everything(self):
        from demo.server import _boot_headline

        assert _boot_headline({"OK", "MODIFIED"}, tree_ok=True) == "MODIFIED"
        assert _boot_headline({"OK", "MISSING"}, tree_ok=True) == "MODIFIED"
        assert _boot_headline({"OK"}, tree_ok=False) == "MODIFIED"
        assert _boot_headline({"NO_MANIFEST", "MODIFIED"}, tree_ok=True) == "MODIFIED"

    def test_every_declared_file_status_is_classified(self):
        """Per-file vocabulary gets the same exported-constant treatment the
        headline vocabulary already has — it was guarded one level up and not
        at this one."""
        from demo.server import FILE_STATUSES, _boot_headline

        for st in FILE_STATUSES:
            assert _boot_headline({st}, tree_ok=True) in {
                "CLEAN", "MODIFIED", "UNVERIFIABLE"
            }, f"{st} produced an unclassified headline"

    def test_declared_vocabulary_matches_what_the_route_emits(self):
        """The constant must describe the code, not a stale copy of it."""
        import re

        from demo.server import FILE_STATUSES

        src = open(os.path.join(_ROOT, "demo", "server.py"), encoding="utf-8").read()
        block = src[src.index("def api_boot"): src.index("def _boot_headline")]
        emitted = set(re.findall(r'"status":\s*"([A-Z_]+)"', block))
        emitted |= set(re.findall(r'st\s*=\s*"([A-Z_]+)"', block))

        assert emitted <= set(FILE_STATUSES), (
            f"api_boot emits {emitted - set(FILE_STATUSES)} which FILE_STATUSES "
            "does not declare"
        )


class TestStatusVocabularyIsRenderable:
    """#3 — a status the CSS cannot style renders as default text.

    ``MODIFIED`` lowercased to a class that was never defined, so the alarm
    displayed as plain white while ``CLEAN`` got green plus a 40px glow. A
    system whose failure state is quieter than its success state teaches the
    reader to relax. This asserts the contract between the statuses the server
    can emit and the classes the stylesheet defines.
    """

    def test_every_server_status_has_a_css_class(self):
        """The status list is IMPORTED, not restated here.

        A hardcoded copy in this file would be the same defect one level up: a
        list maintained by hand that silently stops matching what the server
        actually emits. Adding a status to server.py must break this test.
        """
        from demo.server import BOOT_STATUSES

        html = open(
            os.path.join(_ROOT, "demo", "index.html"), encoding="utf-8"
        ).read()
        defined = set(re.findall(r"\.boot-status\.([a-z]+)\s*\{", html))

        missing = {s for s in BOOT_STATUSES if s.lower() not in defined}
        assert not missing, (
            f"status(es) {missing} would fall through to unstyled default text; "
            f"CSS defines only {sorted(defined)}"
        )

    def test_the_alarm_is_not_quieter_than_the_all_clear(self):
        """CLEAN has a glow. MODIFIED must have one too, at minimum."""
        html = open(
            os.path.join(_ROOT, "demo", "index.html"), encoding="utf-8"
        ).read()

        def rule(cls):
            m = re.search(r"\.boot-status\." + cls + r"\s*\{([^}]*)\}", html)
            return m.group(1) if m else ""

        clean, modified = rule("clean"), rule("modified")
        assert "text-shadow" in clean, "fixture assumption: clean glows"
        assert "text-shadow" in modified, (
            "the failure state must be at least as prominent as the success state"
        )
