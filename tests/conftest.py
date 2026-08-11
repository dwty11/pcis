"""Shared test guards.

The signing key directory defaults to `~/.pcis/keys` — deliberately outside the project
tree, and therefore outside anything pytest sandboxes on its own. Without a guard, any test
that reaches a key path would read or write the operator's real key directory.

`PCIS_BASE_DIR` does not help here: the key dir is intentionally not derived from it (see
`core/signing.py:_default_key_dir`), because the CLI sets that variable to the current
directory, which would put keys back inside the checkout.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_pcis_key_dir(tmp_path_factory, monkeypatch):
    """Point PCIS_KEY_DIR at a per-test temp dir unless the test set it itself.

    Autouse and unconditional: a test that forgets is exactly the case this protects
    against. A test that genuinely wants a specific key dir overrides the env var after
    this fixture runs, and monkeypatch restores it either way.
    """
    key_dir = tmp_path_factory.mktemp("pcis-keys")
    monkeypatch.setenv("PCIS_KEY_DIR", str(key_dir))
    return key_dir
