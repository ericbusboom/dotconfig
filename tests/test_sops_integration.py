"""Integration tests using real SOPS encryption.

These tests require ``sops`` and ``age-keygen`` to be installed.
They generate a temporary age keypair, configure sops.yaml, and
perform actual encrypt/decrypt operations — no mocking.

The working directory is left at tests/fixtures/sops-integration/
for manual inspection.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from dotconfig.load import load_file, _is_sops_encrypted
from dotconfig.save import save_file


FIXTURES = Path(__file__).parent / "fixtures"
WORKING_DIR = FIXTURES / "sops-integration"


def _tool_available(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(
    not (_tool_available("sops") and _tool_available("age-keygen")),
    reason="sops and age-keygen must be installed",
)


@pytest.fixture(scope="module")
def sops_env():
    """Set up a real SOPS environment with an age keypair.

    Creates:
      - tests/fixtures/sops-integration/ with dev/ and local/alice/ dirs
      - A temporary age keypair
      - sops.yaml configured to encrypt .secrets.* files
      - Sets SOPS_AGE_KEY so sops can decrypt

    The directory is NOT cleaned up after tests.
    """
    if WORKING_DIR.exists():
        shutil.rmtree(WORKING_DIR)

    config_dir = WORKING_DIR
    (config_dir / "dev").mkdir(parents=True)
    (config_dir / "local" / "alice").mkdir(parents=True)

    # Generate a temporary age keypair
    result = subprocess.run(
        ["age-keygen"],
        capture_output=True,
        text=True,
        check=True,
    )
    # age-keygen outputs the secret key to stdout, public key in a comment
    secret_key = None
    public_key = None
    for line in result.stdout.splitlines():
        if line.startswith("AGE-SECRET-KEY-"):
            secret_key = line.strip()
        elif line.startswith("# public key:"):
            public_key = line.split(":", 1)[1].strip()
    # Also check stderr — some versions put the public key comment there
    for line in result.stderr.splitlines():
        if line.startswith("Public key:"):
            public_key = line.split(":", 1)[1].strip()

    assert secret_key, "failed to generate age secret key"
    assert public_key, "failed to extract age public key"

    # Write sops.yaml — match .secrets. files anywhere in the config dir
    sops_yaml = config_dir / "sops.yaml"
    sops_yaml.write_text(
        f"creation_rules:\n"
        f"  - path_regex: '.+\\.secrets\\..+$'\n"
        f"    age: >-\n"
        f"      {public_key}\n"
    )

    # Set the secret key in the environment so sops can decrypt
    old_key = os.environ.get("SOPS_AGE_KEY")
    os.environ["SOPS_AGE_KEY"] = secret_key

    yield config_dir

    # Restore environment
    if old_key is not None:
        os.environ["SOPS_AGE_KEY"] = old_key
    else:
        os.environ.pop("SOPS_AGE_KEY", None)


# ---------------------------------------------------------------------------
# YAML: save with secrets → real SOPS encryption → load back
# ---------------------------------------------------------------------------


class TestRealSopsYAML:
    def test_save_creates_encrypted_companion(self, sops_env, tmp_path, monkeypatch):
        """Saving a YAML with secrets produces a real SOPS-encrypted companion."""
        monkeypatch.chdir(sops_env.parent)

        # Generate secrets at runtime
        src = tmp_path / "app.yaml"
        src.write_text(yaml.dump({
            "database": {
                "host": "db.dev.internal",
                "port": 5432,
                "password": "pg_" + "s3cr3tP4ssw0rd123",
            },
            "api": {
                "endpoint": "https://api.dev.internal",
                "token": "tok_" + "aBcDeFgHiJkLmNoPqRs",
            },
            "logging": {"level": "debug"},
        }, default_flow_style=False, sort_keys=False))

        save_file("dev", None, "app.yaml", sops_env, source=src)

        public_file = sops_env / "dev" / "app.yaml"
        secrets_file = sops_env / "dev" / "app.secrets.yaml"

        assert public_file.exists(), "public file should exist"
        assert secrets_file.exists(), "secrets companion should exist"

        # Public file should have REDACTED, not real secrets
        public_text = public_file.read_text()
        assert "REDACTED" in public_text
        assert "s3cr3tP4ssw0rd123" not in public_text
        assert "aBcDeFgHiJkLmNoPqRs" not in public_text

        # Secrets file should be actually SOPS-encrypted
        secrets_text = secrets_file.read_text()
        assert _is_sops_encrypted(secrets_file), \
            f"secrets file should be SOPS-encrypted, got:\n{secrets_text[:200]}"
        # The raw encrypted file should NOT contain plaintext secrets
        assert "s3cr3tP4ssw0rd123" not in secrets_text
        assert "aBcDeFgHiJkLmNoPqRs" not in secrets_text

    def test_load_decrypts_and_reassembles(self, sops_env, tmp_path, monkeypatch):
        """Loading the file back decrypts the companion and merges it."""
        monkeypatch.chdir(sops_env.parent)

        out = tmp_path / "reassembled.yaml"
        load_file("dev", None, "app.yaml", sops_env, out, to_stdout=False)

        data = yaml.safe_load(out.read_text())

        # Secrets should be back (decrypted from SOPS)
        assert "s3cr3tP4ssw0rd123" in data["database"]["password"]
        assert "aBcDeFgHiJkLmNoPqRs" in data["api"]["token"]
        # Non-secrets preserved
        assert data["database"]["host"] == "db.dev.internal"
        assert data["database"]["port"] == 5432
        assert data["logging"]["level"] == "debug"


# ---------------------------------------------------------------------------
# JSON: save with secrets → real SOPS encryption → load back
# ---------------------------------------------------------------------------


class TestRealSopsJSON:
    def test_save_creates_encrypted_json_companion(self, sops_env, tmp_path, monkeypatch):
        """Saving a JSON with secrets produces a real SOPS-encrypted companion."""
        monkeypatch.chdir(sops_env.parent)

        src = tmp_path / "payment.json"
        src.write_text(json.dumps({
            "stripe": {
                "api_key": "sk_test_" + "Rk4bN7pQ9sT2vX6zY8a",
                "webhook_secret": "whsec_" + "Mn3oP5qR7sT9uV1wX3y",
                "currency": "usd",
            },
            "app": {
                "name": "My App",
                "port": 3000,
            },
        }, indent=2) + "\n")

        save_file("dev", None, "payment.json", sops_env, source=src)

        public_file = sops_env / "dev" / "payment.json"
        secrets_file = sops_env / "dev" / "payment.secrets.json"

        assert public_file.exists()
        assert secrets_file.exists()

        # Public file: REDACTED, no real secrets
        public_text = public_file.read_text()
        assert "REDACTED" in public_text
        assert "Rk4bN7pQ9sT2vX6zY8a" not in public_text

        # Secrets file: SOPS-encrypted
        assert _is_sops_encrypted(secrets_file), "secrets JSON should be SOPS-encrypted"
        secrets_text = secrets_file.read_text()
        assert "Rk4bN7pQ9sT2vX6zY8a" not in secrets_text

    def test_load_decrypts_json_and_reassembles(self, sops_env, tmp_path, monkeypatch):
        """Loading the JSON back decrypts and merges."""
        monkeypatch.chdir(sops_env.parent)

        out = tmp_path / "reassembled.json"
        load_file("dev", None, "payment.json", sops_env, out, to_stdout=False)

        data = json.loads(out.read_text())
        assert "Rk4bN7pQ9sT2vX6zY8a" in data["stripe"]["api_key"]
        assert "Mn3oP5qR7sT9uV1wX3y" in data["stripe"]["webhook_secret"]
        assert data["stripe"]["currency"] == "usd"
        assert data["app"]["name"] == "My App"


# ---------------------------------------------------------------------------
# Diff-save with real SOPS: secrets in the diff get encrypted too
# ---------------------------------------------------------------------------


class TestRealSopsDiffSave:
    def test_diff_save_encrypts_secrets_in_diff(self, sops_env, tmp_path, monkeypatch):
        """Diff-save: secrets in the local override diff are SOPS-encrypted."""
        monkeypatch.chdir(sops_env.parent)

        # First save a base deployment file (no secrets, no encryption needed)
        base_src = tmp_path / "services.yaml"
        base_src.write_text(yaml.dump({
            "api": {"host": "api.dev.internal", "port": 8080},
            "logging": {"level": "debug"},
        }, default_flow_style=False, sort_keys=False))
        save_file("dev", None, "services.yaml", sops_env, source=base_src)

        # Now save a modified version with a secret added, using diff-save
        modified_src = tmp_path / "services-modified.yaml"
        modified_src.write_text(yaml.dump({
            "api": {"host": "localhost", "port": 9090, "secret_key": "key_" + "Abc123Def456Ghi"},
            "logging": {"level": "trace"},
        }, default_flow_style=False, sort_keys=False))
        save_file("dev", "alice", "services.yaml", sops_env, source=modified_src)

        # The local diff should exist
        local_file = sops_env / "local" / "alice" / "services.yaml"
        assert local_file.exists()

        # Check if a secrets companion was created for the diff
        local_secrets = sops_env / "local" / "alice" / "services.secrets.yaml"
        if local_secrets.exists():
            # If secrets were split, the companion should be encrypted
            assert _is_sops_encrypted(local_secrets)
            # And the public local file should have REDACTED
            assert "REDACTED" in local_file.read_text()

    def test_diff_save_round_trip_with_sops(self, sops_env, tmp_path, monkeypatch):
        """Full round-trip: base → diff-save → load merged result."""
        monkeypatch.chdir(sops_env.parent)

        out = tmp_path / "merged.yaml"
        load_file("dev", "alice", "services.yaml", sops_env, out, to_stdout=False)

        data = yaml.safe_load(out.read_text())
        # From local diff (overrides)
        assert data["api"]["host"] == "localhost"
        assert data["api"]["port"] == 9090
        assert data["logging"]["level"] == "trace"
        # The secret should be decrypted and present
        assert "Abc123Def456Ghi" in data["api"]["secret_key"]
        # Preserved from base (not in diff, so comes from deploy)
        # (api.host and api.port were overridden, but base had no other keys to test)
