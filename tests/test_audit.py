"""Tests for dotconfig.audit"""

from pathlib import Path

import pytest

from click.testing import CliRunner

from dotconfig.audit import (
    Finding,
    _is_sops_file,
    _key_looks_secret,
    _scan_env_file,
    _value_is_encrypted,
    audit_config_dir,
    run_audit,
)
from dotconfig.cli import cli


# ---------------------------------------------------------------------------
# _key_looks_secret
# ---------------------------------------------------------------------------


class TestKeyLooksSecret:
    @pytest.mark.parametrize("key", [
        "SECRET_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "API_KEY",
        "GITHUB_TOKEN",
        "DB_PASSWORD",
        "SESSION_SECRET",
        "PRIVATE_KEY",
        "ACCESS_KEY_ID",
        "AUTH_KEY",
        "ENCRYPTION_KEY",
        "SIGNING_KEY",
        "HMAC_SECRET",
        "BEARER_TOKEN",
        "CREDENTIAL_FILE",
        "client_secret",
        "my_api_key",
        "password",
    ])
    def test_secret_keys_detected(self, key):
        assert _key_looks_secret(key) is not None

    @pytest.mark.parametrize("key", [
        "APP_DOMAIN",
        "PORT",
        "NODE_ENV",
        "DATABASE_URL",
        "LOG_LEVEL",
        "DEPLOYMENT",
        "CACHE_TTL",
        "EDITOR",
    ])
    def test_normal_keys_not_flagged(self, key):
        assert _key_looks_secret(key) is None


# ---------------------------------------------------------------------------
# _value_is_encrypted
# ---------------------------------------------------------------------------


class TestValueIsEncrypted:
    def test_sops_enc_detected(self):
        assert _value_is_encrypted("ENC[AES256_GCM,data:abc123,iv:xyz]") is True

    def test_plaintext_not_detected(self):
        assert _value_is_encrypted("mysecretvalue") is False

    def test_empty_not_detected(self):
        assert _value_is_encrypted("") is False


# ---------------------------------------------------------------------------
# _scan_env_file
# ---------------------------------------------------------------------------


class TestScanEnvFile:
    def test_finds_plaintext_secrets(self, tmp_path):
        f = tmp_path / "public.env"
        f.write_text("APP_DOMAIN=example.com\nSECRET_KEY=mysecret\nAPI_KEY=ak_12345\n")
        findings = _scan_env_file(f)
        keys = [r.key for r in findings]
        assert "SECRET_KEY" in keys
        assert "API_KEY" in keys

    def test_skips_encrypted_values(self, tmp_path):
        f = tmp_path / "secrets.env"
        f.write_text("SECRET_KEY=ENC[AES256_GCM,data:abc]\n")
        findings = _scan_env_file(f)
        assert findings == []

    def test_skips_comments(self, tmp_path):
        f = tmp_path / "public.env"
        f.write_text("# SECRET_KEY=mysecret\nAPP_DOMAIN=example.com\n")
        findings = _scan_env_file(f)
        assert findings == []

    def test_skips_empty_values(self, tmp_path):
        f = tmp_path / "public.env"
        f.write_text("SECRET_KEY=\n")
        findings = _scan_env_file(f)
        assert findings == []

    def test_normal_keys_clean(self, tmp_path):
        f = tmp_path / "public.env"
        f.write_text("APP_DOMAIN=example.com\nPORT=3000\n")
        findings = _scan_env_file(f)
        assert findings == []


# ---------------------------------------------------------------------------
# _is_sops_file
# ---------------------------------------------------------------------------


class TestIsSopsFile:
    def test_sops_yaml(self, tmp_path):
        f = tmp_path / "secrets.yaml"
        f.write_text("data: ENC[AES256_GCM,...]\nsops:\n    version: 3.7\n")
        assert _is_sops_file(f) is True

    def test_sops_env(self, tmp_path):
        f = tmp_path / "secrets.env"
        f.write_text("KEY=ENC[...]\nsops_version=3.7\nsops_mac=abc\n")
        assert _is_sops_file(f) is True

    def test_plain_yaml(self, tmp_path):
        f = tmp_path / "app.yaml"
        f.write_text("database:\n  host: localhost\n")
        assert _is_sops_file(f) is False

    def test_missing_file(self, tmp_path):
        assert _is_sops_file(tmp_path / "nope") is False


# ---------------------------------------------------------------------------
# audit_config_dir
# ---------------------------------------------------------------------------


class TestAuditConfigDir:
    def test_finds_secrets_in_public_env(self, tmp_path):
        cfg = tmp_path / "config" / "dev"
        cfg.mkdir(parents=True)
        (cfg / "public.env").write_text("SECRET_KEY=mysecret\nAPP_DOMAIN=example.com\n")
        findings = audit_config_dir(tmp_path / "config")
        assert len(findings) == 1
        assert findings[0].key == "SECRET_KEY"

    def test_skips_sops_encrypted_files(self, tmp_path):
        cfg = tmp_path / "config" / "dev"
        cfg.mkdir(parents=True)
        (cfg / "secrets.env").write_text("SECRET_KEY=val\nsops_version=3.7\nsops_mac=abc\n")
        findings = audit_config_dir(tmp_path / "config")
        assert findings == []

    def test_skips_sops_yaml(self, tmp_path):
        cfg = tmp_path / "config"
        cfg.mkdir(parents=True)
        (cfg / "sops.yaml").write_text("creation_rules: []\n")
        findings = audit_config_dir(cfg)
        assert findings == []

    def test_clean_config_no_findings(self, tmp_path):
        cfg = tmp_path / "config" / "dev"
        cfg.mkdir(parents=True)
        (cfg / "public.env").write_text("APP_DOMAIN=example.com\nPORT=3000\n")
        findings = audit_config_dir(tmp_path / "config")
        assert findings == []

    def test_nonexistent_dir(self, tmp_path):
        findings = audit_config_dir(tmp_path / "nope")
        assert findings == []


# ---------------------------------------------------------------------------
# run_audit
# ---------------------------------------------------------------------------


class TestRunAudit:
    def test_clean_returns_true(self, tmp_path):
        cfg = tmp_path / "config" / "dev"
        cfg.mkdir(parents=True)
        (cfg / "public.env").write_text("APP_DOMAIN=example.com\n")
        assert run_audit(tmp_path / "config") is True

    def test_findings_return_false(self, tmp_path):
        cfg = tmp_path / "config" / "dev"
        cfg.mkdir(parents=True)
        (cfg / "public.env").write_text("SECRET_KEY=plaintext\n")
        assert run_audit(tmp_path / "config") is False


# ---------------------------------------------------------------------------
# CLI — dotconfig audit
# ---------------------------------------------------------------------------


class TestAuditCLI:
    def test_clean_exits_zero(self, tmp_path):
        cfg = tmp_path / "config" / "dev"
        cfg.mkdir(parents=True)
        (cfg / "public.env").write_text("APP_DOMAIN=example.com\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "-c", str(tmp_path / "config")])
        assert result.exit_code == 0

    def test_findings_exit_one(self, tmp_path):
        cfg = tmp_path / "config" / "dev"
        cfg.mkdir(parents=True)
        (cfg / "public.env").write_text("SECRET_KEY=plaintext\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "-c", str(tmp_path / "config")])
        assert result.exit_code == 1
