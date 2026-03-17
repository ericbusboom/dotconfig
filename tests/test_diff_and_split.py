"""End-to-end tests for diff-save and secret splitting.

Uses the diff-test.source fixture (copied to a persistent working directory
in tests/fixtures/diff-test/) and standalone input files from tests/fixtures/.

Secrets are generated at test time to avoid checking them into git.
"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from dotconfig.load import load_file
from dotconfig.save import save_file


FIXTURES = Path(__file__).parent / "fixtures"
WORKING_DIR = FIXTURES / "diff-test"


def _fake_encrypt(content: str, filepath: Path, sops_config=None) -> bool:
    """Simulate SOPS encrypt by writing plaintext."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    return True


def _fake_decrypt(filepath: Path, sops_config=None):
    """Simulate SOPS decrypt by returning file contents as-is."""
    return filepath.read_text()


def _generate_secret_yaml() -> str:
    """Generate a YAML string with plausible secret values at runtime.

    Values are generated here (not checked in) so git pre-commit hooks
    won't flag them.
    """
    # Build values that look like real secrets
    fake_db_password = "pg_" + "a1b2c3d4e5f6g7h8i9j0"
    fake_api_token = "tok_" + "Xk9mN2pQ4rS6tU8vW0y"
    fake_session_secret = "sess_" + "ABCDEFghijklMNOPqrst"
    return yaml.dump({
        "database": {
            "host": "db.dev.internal",
            "port": 5432,
            "name": "app_dev",
            "password": fake_db_password,
        },
        "api": {
            "endpoint": "https://api.dev.internal",
            "token": fake_api_token,
        },
        "session_secret": fake_session_secret,
        "logging": {
            "level": "debug",
        },
    }, default_flow_style=False, sort_keys=False)


def _generate_secret_json() -> str:
    """Generate a JSON string with plausible secret values at runtime."""
    fake_api_key = "sk_test_" + "4eC39HqLyjWDarjtT1zdp7dc"
    fake_webhook_secret = "whsec_" + "abc123def456ghi789"
    return json.dumps({
        "stripe": {
            "api_key": fake_api_key,
            "webhook_secret": fake_webhook_secret,
            "currency": "usd",
        },
        "app": {
            "name": "My App",
            "port": 3000,
        },
    }, indent=2) + "\n"


@pytest.fixture(scope="module")
def diff_test():
    """Copy the diff-test fixture to a persistent working directory.

    The directory is NOT cleaned up after tests — it stays at
    tests/fixtures/diff-test/ for manual inspection.
    """
    if WORKING_DIR.exists():
        shutil.rmtree(WORKING_DIR)
    shutil.copytree(FIXTURES / "diff-test.source", WORKING_DIR)
    return WORKING_DIR


# ---------------------------------------------------------------------------
# Diff-save tests — YAML
# ---------------------------------------------------------------------------


class TestDiffSaveYAML:
    """Test saving a modified YAML file with both -d and -l (diff-save mode)."""

    def test_diff_save_yaml_writes_only_changes(self, diff_test, tmp_path):
        """Modified YAML saved with -d dev -l alice writes only the diff."""
        src = FIXTURES / "input-app-modified.yaml"
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_file("dev", "bob", "app.yaml", diff_test, source=src)

        local_file = diff_test / "local" / "bob" / "app.yaml"
        assert local_file.exists(), "local override file should be created"

        data = yaml.safe_load(local_file.read_text())
        # Changed keys should be present
        assert data["database"]["host"] == "localhost"
        assert data["database"]["port"] == 5433
        assert data["logging"]["level"] == "trace"
        assert data["features"]["experimental_ui"] is True
        # Unchanged keys should NOT be present
        assert "name" not in data.get("database", {}), "unchanged key should be omitted"
        assert "redis" not in data, "entirely unchanged section should be omitted"
        assert "format" not in data.get("logging", {}), "unchanged key should be omitted"

    def test_diff_save_yaml_loads_back_merged(self, diff_test, tmp_path):
        """Loading -d dev -l bob merges the diff back into the full file."""
        out = tmp_path / "merged.yaml"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_file("dev", "bob", "app.yaml", diff_test, out, to_stdout=False)

        data = yaml.safe_load(out.read_text())
        # Overridden values from bob's diff
        assert data["database"]["host"] == "localhost"
        assert data["database"]["port"] == 5433
        assert data["logging"]["level"] == "trace"
        assert data["features"]["experimental_ui"] is True
        # Preserved values from dev base
        assert data["database"]["name"] == "app_dev"
        assert data["database"]["pool_size"] == 10
        assert data["redis"]["host"] == "redis.dev.internal"
        assert data["logging"]["format"] == "json"
        assert data["features"]["dark_mode"] is False

    def test_existing_alice_override_loads_correctly(self, diff_test, tmp_path):
        """The checked-in alice override (from fixture) merges correctly."""
        out = tmp_path / "merged.yaml"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_file("dev", "alice", "app.yaml", diff_test, out, to_stdout=False)

        data = yaml.safe_load(out.read_text())
        # Alice's overrides
        assert data["database"]["host"] == "localhost"
        assert data["database"]["port"] == 5433
        assert data["logging"]["level"] == "trace"
        assert data["features"]["experimental_ui"] is True
        # Dev base preserved
        assert data["database"]["name"] == "app_dev"
        assert data["redis"]["port"] == 6379


# ---------------------------------------------------------------------------
# Diff-save tests — JSON
# ---------------------------------------------------------------------------


class TestDiffSaveJSON:
    """Test saving a modified JSON file with both -d and -l."""

    def test_diff_save_json_writes_only_changes(self, diff_test, tmp_path):
        """Modified JSON saved with -d dev -l bob writes only the diff."""
        src = FIXTURES / "input-services-modified.json"
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_file("dev", "bob", "services.json", diff_test, source=src)

        local_file = diff_test / "local" / "bob" / "services.json"
        assert local_file.exists()

        data = json.loads(local_file.read_text())
        # Changed keys
        assert data["api"]["host"] == "localhost"
        assert data["api"]["port"] == 9090
        assert data["cdn"]["cache_ttl"] == 600
        # New section
        assert data["debug"]["profiling"] is True
        assert data["debug"]["sql_logging"] is True
        # Unchanged should be omitted
        assert "notifications" not in data
        assert "endpoint" not in data.get("cdn", {})
        assert "retries" not in data.get("api", {})

    def test_diff_save_json_loads_back_merged(self, diff_test, tmp_path):
        """Loading -d dev -l bob merges JSON diff back correctly."""
        out = tmp_path / "merged.json"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_file("dev", "bob", "services.json", diff_test, out, to_stdout=False)

        data = json.loads(out.read_text())
        # Overridden
        assert data["api"]["host"] == "localhost"
        assert data["api"]["port"] == 9090
        assert data["cdn"]["cache_ttl"] == 600
        # New section
        assert data["debug"]["profiling"] is True
        # Preserved from base
        assert data["api"]["timeout_ms"] == 5000
        assert data["notifications"]["provider"] == "sendgrid"
        assert data["cdn"]["endpoint"] == "https://cdn.dev.example.com"


# ---------------------------------------------------------------------------
# Secret splitting tests — YAML with generated secrets
# ---------------------------------------------------------------------------


class TestSecretSplitYAML:
    """Test auto-splitting secrets from a YAML file."""

    def test_yaml_with_secrets_creates_companion(self, diff_test, tmp_path):
        """Saving a YAML file with secret keys creates a .secrets.yaml companion."""
        src = tmp_path / "app-with-secrets.yaml"
        src.write_text(_generate_secret_yaml())

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_file("dev", None, "app-with-secrets.yaml", diff_test, source=src)

        public_file = diff_test / "dev" / "app-with-secrets.yaml"
        secrets_file = diff_test / "dev" / "app-with-secrets.secrets.yaml"

        assert public_file.exists(), "public file should exist"
        assert secrets_file.exists(), "secrets companion should exist"

        public_data = yaml.safe_load(public_file.read_text())
        secrets_data = yaml.safe_load(secrets_file.read_text())

        # Public file has REDACTED for secret values
        assert public_data["database"]["password"] == "REDACTED"
        assert public_data["api"]["token"] == "REDACTED"
        assert public_data["session_secret"] == "REDACTED"
        # Non-secret values are preserved
        assert public_data["database"]["host"] == "db.dev.internal"
        assert public_data["database"]["port"] == 5432
        assert public_data["logging"]["level"] == "debug"

        # Secrets file has the real values
        assert "password" in secrets_data.get("database", {})
        assert "token" in secrets_data.get("api", {})
        assert "session_secret" in secrets_data

    def test_yaml_secrets_round_trip(self, diff_test, tmp_path):
        """Loading a split YAML file reassembles secrets transparently."""
        out = tmp_path / "reassembled.yaml"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_file("dev", None, "app-with-secrets.yaml", diff_test, out, to_stdout=False)

        data = yaml.safe_load(out.read_text())
        # Secrets should be back (not REDACTED)
        assert data["database"]["password"] != "REDACTED"
        assert data["api"]["token"] != "REDACTED"
        assert data["session_secret"] != "REDACTED"
        # Non-secrets preserved
        assert data["database"]["host"] == "db.dev.internal"
        assert data["logging"]["level"] == "debug"


# ---------------------------------------------------------------------------
# Secret splitting tests — JSON with generated secrets
# ---------------------------------------------------------------------------


class TestSecretSplitJSON:
    """Test auto-splitting secrets from a JSON file."""

    def test_json_with_secrets_creates_companion(self, diff_test, tmp_path):
        """Saving a JSON file with secret keys creates a .secrets.json companion."""
        src = tmp_path / "payment.json"
        src.write_text(_generate_secret_json())

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_file("dev", None, "payment.json", diff_test, source=src)

        public_file = diff_test / "dev" / "payment.json"
        secrets_file = diff_test / "dev" / "payment.secrets.json"

        assert public_file.exists()
        assert secrets_file.exists()

        public_data = json.loads(public_file.read_text())
        secrets_data = json.loads(secrets_file.read_text())

        # Public file has REDACTED
        assert public_data["stripe"]["api_key"] == "REDACTED"
        assert public_data["stripe"]["webhook_secret"] == "REDACTED"
        # Non-secrets preserved
        assert public_data["stripe"]["currency"] == "usd"
        assert public_data["app"]["name"] == "My App"
        assert public_data["app"]["port"] == 3000

        # Secrets file has real values
        assert "api_key" in secrets_data.get("stripe", {})
        assert "webhook_secret" in secrets_data.get("stripe", {})

    def test_json_secrets_round_trip(self, diff_test, tmp_path):
        """Loading a split JSON file reassembles secrets transparently."""
        out = tmp_path / "reassembled.json"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_file("dev", None, "payment.json", diff_test, out, to_stdout=False)

        data = json.loads(out.read_text())
        assert data["stripe"]["api_key"] != "REDACTED"
        assert data["stripe"]["webhook_secret"] != "REDACTED"
        assert data["stripe"]["currency"] == "usd"
        assert data["app"]["name"] == "My App"


# ---------------------------------------------------------------------------
# No-change diff
# ---------------------------------------------------------------------------


class TestNoChangeDiff:
    def test_identical_file_writes_nothing(self, diff_test, tmp_path, capsys):
        """Saving an identical file with -d and -l writes nothing."""
        # Use the exact same file as the deployment
        src = diff_test / "dev" / "app.yaml"
        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_file("dev", "charlie", "app.yaml", diff_test, source=src)

        charlie_dir = diff_test / "local" / "charlie"
        assert not charlie_dir.exists(), "no local dir should be created for zero diff"
