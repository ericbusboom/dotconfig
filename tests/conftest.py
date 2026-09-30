"""Global test isolation: no test may read or touch the real age key."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_age_key(tmp_path_factory, monkeypatch):
    """Point SOPS_AGE_KEY_FILE/HOME at a per-test temp dir and unset SOPS_AGE_KEY.

    A plain key file is created there so the guard sees an "unlocked, not
    wrapped" state regardless of the machine's real key state. Tests needing
    a different state override these env vars (or delete the file).
    """
    d = tmp_path_factory.mktemp("age_home")
    key_dir = d / ".config" / "sops" / "age"
    key_dir.mkdir(parents=True)
    kf = key_dir / "keys.txt"
    kf.write_text("# isolated test key placeholder\n")
    kf.chmod(0o600)
    monkeypatch.setenv("HOME", str(d))
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(kf))
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    return kf
