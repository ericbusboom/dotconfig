"""End-to-end tests using fixture config directories.

Each fixture lives under tests/fixtures/<name>.source/ and is copied to
tests/fixtures/<name>/ before each test.  The working copy is disposable
and gitignored; the source is checked in and never modified.
"""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.load import load_config
from dotconfig.save import parse_env_file, save_config


FIXTURES = Path(__file__).parent / "fixtures"


def _fake_decrypt(filepath: Path, sops_config=None):
    """Simulate sops decrypt by returning file contents as-is."""
    return filepath.read_text()


def _fake_encrypt(content: str, filepath: Path, sops_config=None) -> bool:
    """Simulate sops encrypt by writing plaintext."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    return True


@pytest.fixture()
def complete(tmp_path: Path) -> Path:
    """Copy the 'complete' fixture to a temp dir and return its path."""
    dest = tmp_path / "complete"
    shutil.copytree(FIXTURES / "complete.source", dest)
    return dest


@pytest.fixture()
def missing_secrets(tmp_path: Path) -> Path:
    """Copy the 'missing-secrets' fixture to a temp dir."""
    dest = tmp_path / "missing-secrets"
    shutil.copytree(FIXTURES / "missing-secrets.source", dest)
    return dest


@pytest.fixture()
def empty_config(tmp_path: Path) -> Path:
    """Copy the 'empty' fixture to a temp dir."""
    dest = tmp_path / "empty"
    shutil.copytree(FIXTURES / "empty.source", dest)
    return dest


# ---------------------------------------------------------------------------
# Load tests — complete fixture
# ---------------------------------------------------------------------------


class TestLoadComplete:
    def test_load_dev_alice(self, complete, tmp_path):
        """Load dev + alice produces a valid .env with all four sections."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        text = out.read_text()
        assert "# CONFIG_COMMON=dev" in text
        assert "# CONFIG_LOCAL=alice" in text
        assert "APP_DOMAIN=dev.example.com" in text
        assert "SESSION_SECRET=dev_session_secret_abc123" in text
        assert "DEV_DOCKER_CONTEXT=orbstack" in text
        assert "PERSONAL_API_TOKEN=alice_token_secret" in text

    def test_load_prod_no_local(self, complete, tmp_path):
        """Load prod without local produces only common sections."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("prod", None, complete, out)

        text = out.read_text()
        assert "# CONFIG_COMMON=prod" in text
        assert "CONFIG_LOCAL" not in text
        assert "APP_DOMAIN=app.example.com" in text
        assert "STRIPE_API_KEY=sk_live_prodkey789" in text
        assert "public-local" not in text

    def test_load_dev_bob(self, complete, tmp_path):
        """Load dev + bob uses bob's local overrides."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "bob", complete, out)

        text = out.read_text()
        assert "# CONFIG_LOCAL=bob" in text
        assert "DEV_DOCKER_CONTEXT=docker-desktop" in text
        assert "EDITOR=nano" in text

    def test_section_markers_use_new_format(self, complete, tmp_path):
        """Newly generated .env files use #@dotconfig: markers."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        text = out.read_text()
        assert "#@dotconfig: public (dev)" in text
        assert "#@dotconfig: secrets (dev)" in text
        assert "#@dotconfig: public-local (alice)" in text
        assert "#@dotconfig: secrets-local (alice)" in text
        # Old-style markers should NOT appear
        assert "# --- public (dev) ---" not in text


# ---------------------------------------------------------------------------
# Round-trip tests — load then save
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_load_save_preserves_public_content(self, complete, tmp_path):
        """Load and save round-trips public config content."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(out, complete)

        public = complete / "dev" / "public.env"
        content = public.read_text()
        assert "APP_DOMAIN=dev.example.com" in content
        assert "PORT=3000" in content
        assert "DEPLOYMENT=dev" in content

    def test_load_save_preserves_secrets_content(self, complete, tmp_path):
        """Load and save round-trips secrets content."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(out, complete)

        secrets = complete / "dev" / "secrets.env"
        content = secrets.read_text()
        assert "SESSION_SECRET=dev_session_secret_abc123" in content
        assert "STRIPE_API_KEY=sk_test_devkey123" in content

    def test_load_save_preserves_local_content(self, complete, tmp_path):
        """Load and save round-trips local overrides."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(out, complete)

        local = complete / "local" / "alice" / "public.env"
        content = local.read_text()
        assert "DEV_DOCKER_CONTEXT=orbstack" in content
        assert "QR_DOMAIN=http://192.168.1.40:5173/" in content

    def test_load_edit_save_round_trip(self, complete, tmp_path):
        """Load, edit a value in .env, save — the edit lands in the right file."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        # Simulate user editing a public variable
        text = out.read_text()
        text = text.replace("PORT=3000", "PORT=4000")
        out.write_text(text)

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(out, complete)

        public = complete / "dev" / "public.env"
        assert "PORT=4000" in public.read_text()
        assert "PORT=3000" not in public.read_text()

    def test_save_to_different_environment(self, complete, tmp_path):
        """Load dev, save to staging — files land in staging/."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(out, complete, override_common="staging")

        staging_public = complete / "staging" / "public.env"
        assert staging_public.exists()
        assert "APP_DOMAIN=dev.example.com" in staging_public.read_text()
        # DEPLOYMENT should be rewritten to staging
        assert "DEPLOYMENT=staging" in staging_public.read_text()

    def test_save_to_different_user(self, complete, tmp_path):
        """Load dev/alice, save to dev/charlie — local files land in charlie/."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", complete, out)

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(out, complete, override_local="charlie")

        charlie = complete / "local" / "charlie" / "public.env"
        assert charlie.exists()
        assert "DEV_DOCKER_CONTEXT=orbstack" in charlie.read_text()


# ---------------------------------------------------------------------------
# Error / edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_missing_secrets_file_still_loads(self, missing_secrets, tmp_path):
        """Config without secrets.env loads successfully with empty secrets section."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, missing_secrets, out)

        text = out.read_text()
        assert "APP_DOMAIN=dev.example.com" in text
        assert "#@dotconfig: secrets (dev)" in text

    def test_nonexistent_environment_exits(self, complete, tmp_path):
        """Loading a nonexistent environment exits with error."""
        out = tmp_path / ".env"
        with pytest.raises(SystemExit):
            load_config("nonexistent", None, complete, out)

    def test_nonexistent_local_user_warns(self, complete, tmp_path, capsys):
        """Loading with a nonexistent local user warns but continues."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "nonexistent", complete, out)

        assert out.exists()
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_empty_config_dir_exits(self, empty_config, tmp_path):
        """Loading from an empty config directory exits with error."""
        out = tmp_path / ".env"
        with pytest.raises(SystemExit):
            load_config("dev", None, empty_config, out)


# ---------------------------------------------------------------------------
# Legacy marker compatibility
# ---------------------------------------------------------------------------


class TestLegacyMarkers:
    def test_save_parses_legacy_env(self, complete, tmp_path):
        """An .env with old-style # --- markers is still parsed correctly by save."""
        legacy_env = tmp_path / ".env"
        legacy_env.write_text("""\
# CONFIG_COMMON=dev
# CONFIG_LOCAL=alice

# --- public (dev) ---
APP_DOMAIN=dev.example.com
PORT=3000

# --- secrets (dev) ---
SESSION_SECRET=dev_session_secret_abc123

# --- public-local (alice) ---
DEV_DOCKER_CONTEXT=orbstack

# --- secrets-local (alice) ---
""")

        with patch("dotconfig.save._encrypt_sops", side_effect=_fake_encrypt):
            save_config(legacy_env, complete)

        public = complete / "dev" / "public.env"
        assert "APP_DOMAIN=dev.example.com" in public.read_text()

    def test_user_subheadings_not_confused_with_sections(self, tmp_path):
        """Comments like '# --- GitHub OAuth ---' inside a section are NOT treated as section markers."""
        env_with_subheadings = """\
# CONFIG_COMMON=dev

#@dotconfig: public (dev)
APP_DOMAIN=example.com

#@dotconfig: secrets (dev)
# GitHub OAuth
GITHUB_CLIENT_ID=gh_xxx
GITHUB_CLIENT_SECRET=gh_yyy
# Stripe
STRIPE_KEY=sk_test_123
"""
        _, _, sections = parse_env_file(env_with_subheadings)
        secrets = sections["secrets (dev)"]
        assert "GITHUB_CLIENT_ID=gh_xxx" in secrets
        assert "GITHUB_CLIENT_SECRET=gh_yyy" in secrets
        assert "STRIPE_KEY=sk_test_123" in secrets

    def test_old_dashed_subheadings_still_split_legacy_format(self, tmp_path):
        """With old markers, a user comment '# --- GitHub OAuth ---' DOES get confused.

        This test documents the problem that motivated switching to #@dotconfig: markers.
        The old format would incorrectly split on user-authored subheadings.
        """
        env_with_collision = """\
# CONFIG_COMMON=dev

# --- secrets (dev) ---
# --- GitHub OAuth ---
GITHUB_CLIENT_ID=gh_xxx
STRIPE_KEY=sk_test_123
"""
        _, _, sections = parse_env_file(env_with_collision)
        # The old parser splits on "# --- GitHub OAuth ---" creating a spurious section
        assert "GitHub OAuth" in sections
        # And the secrets section loses the variables after the subheading
        assert "STRIPE_KEY" not in sections.get("secrets (dev)", "")
