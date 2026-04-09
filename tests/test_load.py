"""Tests for dotconfig.load"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dotconfig.load import _decrypt_sops, _deep_merge, _is_sops_encrypted, load_config, load_file


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Return a populated temporary config/ directory."""
    cfg = tmp_path / "config"

    # Dev environment
    (cfg / "dev").mkdir(parents=True)
    (cfg / "dev" / "public.env").write_text(
        "APP_DOMAIN=example.com\nNODE_ENV=development\nPORT=3000\n"
    )
    (cfg / "dev" / "secrets.env").write_text(
        "SESSION_SECRET=abc123\nsops_version=3.0\n"
    )

    # Prod environment
    (cfg / "prod").mkdir(parents=True)
    (cfg / "prod" / "public.env").write_text(
        "APP_DOMAIN=prod.example.com\nNODE_ENV=production\nPORT=8080\n"
    )

    # Local overrides
    (cfg / "local" / "alice").mkdir(parents=True)
    (cfg / "local" / "alice" / "public.env").write_text(
        "DEV_DOCKER_CONTEXT=orbstack\nQR_DOMAIN=http://192.168.1.1:5173/\n"
    )

    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_decrypt(filepath: Path, sops_config=None):
    """Return file contents with sops metadata stripped (simulates sops decrypt)."""
    lines = filepath.read_text().splitlines()
    return "\n".join(l for l in lines if not l.startswith("sops_")) + "\n"


# ---------------------------------------------------------------------------
# load_config — happy paths
# ---------------------------------------------------------------------------

class TestLoadConfigDeployOnly:
    def test_output_file_is_created(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert out.exists()

    def test_metadata_header_written(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        assert "# CONFIG_DEPLOY=dev" in text
        assert "CONFIG_LOCAL" not in text

    def test_public_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert "#@dotconfig: public (dev)" in out.read_text()

    def test_secrets_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert "#@dotconfig: secrets (dev)" in out.read_text()

    def test_public_variables_included(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        assert "APP_DOMAIN=example.com" in text
        assert "NODE_ENV=development" in text

    def test_secret_variables_included(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert "SESSION_SECRET=abc123" in out.read_text()

    def test_no_local_sections_when_local_omitted(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        text = out.read_text()
        assert "public-local" not in text
        assert "secrets-local" not in text

    def test_file_ends_with_newline(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert out.read_text().endswith("\n")

    def test_default_output_is_dot_env(self, config_dir, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, None)
        assert (tmp_path / ".env").exists()


class TestLoadConfigWithLocal:
    def test_config_local_metadata_written(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        assert "# CONFIG_LOCAL=alice" in out.read_text()

    def test_public_local_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        assert "#@dotconfig: public-local (alice)" in out.read_text()

    def test_secrets_local_section_marker_present(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        assert "#@dotconfig: secrets-local (alice)" in out.read_text()

    def test_local_variables_included(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        text = out.read_text()
        assert "DEV_DOCKER_CONTEXT=orbstack" in text
        assert "QR_DOMAIN=http://192.168.1.1:5173/" in text

    def test_section_order(self, config_dir, tmp_path):
        """Public sections come before local sections."""
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "alice", config_dir, out)
        text = out.read_text()
        idx_public = text.index("#@dotconfig: public (dev)")
        idx_secrets = text.index("#@dotconfig: secrets (dev)")
        idx_local = text.index("#@dotconfig: public-local (alice)")
        idx_secrets_local = text.index("#@dotconfig: secrets-local (alice)")
        assert idx_public < idx_secrets < idx_local < idx_secrets_local

    def test_prod_environment(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", return_value=None):
            load_config("prod", None, config_dir, out)
        text = out.read_text()
        assert "# CONFIG_DEPLOY=prod" in text
        assert "APP_DOMAIN=prod.example.com" in text


# ---------------------------------------------------------------------------
# load_config — stdout mode
# ---------------------------------------------------------------------------

class TestLoadConfigStdout:
    def test_stdout_prints_content(self, config_dir, capsys):
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, None, to_stdout=True)
        captured = capsys.readouterr()
        assert "# CONFIG_DEPLOY=dev" in captured.out
        assert "APP_DOMAIN=example.com" in captured.out

    def test_stdout_does_not_create_file(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, None, to_stdout=True)
        assert not out.exists()


# ---------------------------------------------------------------------------
# load_config — error / edge cases
# ---------------------------------------------------------------------------

class TestLoadConfigErrors:
    def test_missing_deploy_env_exits(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with pytest.raises(SystemExit):
            load_config("nonexistent", None, config_dir, out)

    def test_missing_secrets_file_does_not_crash(self, config_dir, tmp_path, capsys):
        out = tmp_path / ".env"
        # Remove secrets file
        (config_dir / "dev" / "secrets.env").unlink()
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", None, config_dir, out)
        assert out.exists()

    def test_missing_local_file_warns_and_continues(self, config_dir, tmp_path, capsys):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_fake_decrypt):
            load_config("dev", "unknown_dev", config_dir, out)
        captured = capsys.readouterr()
        assert "not found" in captured.err
        assert out.exists()

    def test_sops_failure_gracefully_skipped(self, config_dir, tmp_path):
        # Make secrets.env look SOPS-encrypted so _is_sops_encrypted returns True,
        # then mock _decrypt_sops to simulate a decryption failure.
        (config_dir / "dev" / "secrets.env").write_text(
            "SESSION_SECRET=ENC[AES256_GCM,data:xx]\nsops_version=3.0\n"
        )
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", return_value=None):
            with pytest.raises(SystemExit):
                load_config("dev", None, config_dir, out)


# ---------------------------------------------------------------------------
# load_file — specific file retrieval
# ---------------------------------------------------------------------------

class TestLoadFile:
    def test_load_deployment_file(self, config_dir, tmp_path):
        (config_dir / "dev" / "app.yaml").write_text("key: value\n")
        out = tmp_path / "app.yaml"
        load_file("dev", None, "app.yaml", config_dir, out, to_stdout=False)
        assert out.read_text() == "key: value\n"

    def test_load_local_file(self, config_dir, tmp_path):
        (config_dir / "local" / "alice" / "settings.json").write_text('{"a":1}')
        out = tmp_path / "settings.json"
        load_file(None, "alice", "settings.json", config_dir, out, to_stdout=False)
        import json
        assert json.loads(out.read_text()) == {"a": 1}

    def test_load_file_default_output_is_config_files(self, config_dir, monkeypatch, tmp_path):
        (config_dir / "dev" / "app.yaml").write_text("key: value\n")
        monkeypatch.chdir(tmp_path)
        load_file("dev", None, "app.yaml", config_dir, None, to_stdout=False)
        assert (tmp_path / "config" / "files" / "app.yaml").exists()

    def test_load_file_explicit_output(self, config_dir, tmp_path):
        (config_dir / "dev" / "app.yaml").write_text("key: value\n")
        out = tmp_path / "custom" / "output.yaml"
        load_file("dev", None, "app.yaml", config_dir, out, to_stdout=False)
        assert out.exists()
        assert out.read_text() == "key: value\n"

    def test_load_file_stdout(self, config_dir, capsys):
        (config_dir / "dev" / "app.yaml").write_text("key: value\n")
        load_file("dev", None, "app.yaml", config_dir, None, to_stdout=True)
        assert "key: value" in capsys.readouterr().out

    def test_load_file_not_found_exits(self, config_dir, tmp_path):
        with pytest.raises(SystemExit):
            load_file("dev", None, "nope.txt", config_dir, tmp_path / "out", to_stdout=False)

    def test_load_file_no_deploy_no_local_exits(self, config_dir, tmp_path):
        with pytest.raises(SystemExit):
            load_file(None, None, "app.yaml", config_dir, tmp_path / "out", to_stdout=False)

    def test_unsupported_suffix_with_merge_exits(self, config_dir, tmp_path):
        """Merging with an unsupported file type exits."""
        (config_dir / "dev" / "data.txt").write_text("hello")
        (config_dir / "local" / "alice" / "data.txt").write_text("world")
        out = tmp_path / "data.txt"
        with pytest.raises(SystemExit):
            load_file("dev", "alice", "data.txt", config_dir, out, to_stdout=False)


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_flat_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"db": {"host": "prod.example.com", "port": 5432, "name": "app"}}
        override = {"db": {"host": "localhost", "port": 5433}}
        result = _deep_merge(base, override)
        assert result == {"db": {"host": "localhost", "port": 5433, "name": "app"}}

    def test_override_adds_new_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}

    def test_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        _deep_merge(base, override)
        assert base == {"a": {"x": 1}}

    def test_override_replaces_non_dict(self):
        base = {"a": [1, 2]}
        override = {"a": [3]}
        assert _deep_merge(base, override) == {"a": [3]}


# ---------------------------------------------------------------------------
# load_file — YAML/JSON merge mode
# ---------------------------------------------------------------------------

class TestLoadFileMerge:
    def test_yaml_merge(self, config_dir, tmp_path):
        (config_dir / "dev" / "app.yaml").write_text(
            "database:\n  host: prod\n  port: 5432\n  name: app\n"
        )
        (config_dir / "local" / "alice" / "app.yaml").write_text(
            "database:\n  host: localhost\n  port: 5433\n"
        )
        out = tmp_path / "app.yaml"
        load_file("dev", "alice", "app.yaml", config_dir, out, to_stdout=False)
        import yaml
        result = yaml.safe_load(out.read_text())
        assert result["database"]["host"] == "localhost"
        assert result["database"]["port"] == 5433
        assert result["database"]["name"] == "app"  # preserved from base

    def test_json_merge(self, config_dir, tmp_path):
        import json
        (config_dir / "dev" / "settings.json").write_text(
            json.dumps({"theme": "dark", "editor": {"tabSize": 2, "wrap": True}})
        )
        (config_dir / "local" / "alice" / "settings.json").write_text(
            json.dumps({"editor": {"tabSize": 4}})
        )
        out = tmp_path / "settings.json"
        load_file("dev", "alice", "settings.json", config_dir, out, to_stdout=False)
        result = json.loads(out.read_text())
        assert result["theme"] == "dark"
        assert result["editor"]["tabSize"] == 4
        assert result["editor"]["wrap"] is True

    def test_local_file_missing_uses_deploy_only(self, config_dir, tmp_path, capsys):
        (config_dir / "dev" / "app.yaml").write_text("key: value\n")
        out = tmp_path / "app.yaml"
        load_file("dev", "alice", "app.yaml", config_dir, out, to_stdout=False)
        import yaml
        result = yaml.safe_load(out.read_text())
        assert result["key"] == "value"
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_deploy_file_missing_exits(self, config_dir, tmp_path):
        (config_dir / "local" / "alice" / "app.yaml").write_text("key: value\n")
        with pytest.raises(SystemExit):
            load_file("dev", "alice", "app.yaml", config_dir, tmp_path / "out", to_stdout=False)

    def test_merge_stdout(self, config_dir, capsys):
        (config_dir / "dev" / "app.yaml").write_text("base: true\n")
        (config_dir / "local" / "alice" / "app.yaml").write_text("local: true\n")
        load_file("dev", "alice", "app.yaml", config_dir, None, to_stdout=True)
        out = capsys.readouterr().out
        assert "base: true" in out
        assert "local: true" in out


# ---------------------------------------------------------------------------
# load_config — sops.yaml --config flag
# ---------------------------------------------------------------------------

class TestLoadConfigSopsConfig:
    def test_sops_config_passed_when_sops_yaml_exists(self, config_dir, tmp_path):
        """When config/sops.yaml exists, _decrypt_sops is called with its path."""
        sops_yaml = config_dir / "sops.yaml"
        sops_yaml.write_text("creation_rules: []\n")
        out = tmp_path / ".env"

        calls = []

        def capture_decrypt(filepath, sops_config=None):
            calls.append(sops_config)
            lines = filepath.read_text().splitlines()
            return "\n".join(l for l in lines if not l.startswith("sops_")) + "\n"

        with patch("dotconfig.load._decrypt_sops", side_effect=capture_decrypt):
            load_config("dev", None, config_dir, out)

        assert calls, "expected _decrypt_sops to be called"
        assert all(sc == sops_yaml for sc in calls)

    def test_sops_config_path_passed_when_sops_yaml_missing(self, config_dir, tmp_path):
        """When config/sops.yaml does not exist, sops_config path is still passed; --config is NOT used."""
        out = tmp_path / ".env"

        calls = []

        def capture_decrypt(filepath, sops_config=None):
            calls.append(sops_config)
            lines = filepath.read_text().splitlines()
            return "\n".join(l for l in lines if not l.startswith("sops_")) + "\n"

        with patch("dotconfig.load._decrypt_sops", side_effect=capture_decrypt):
            load_config("dev", None, config_dir, out)

        assert calls, "expected _decrypt_sops to be called"
        expected = config_dir / "sops.yaml"
        assert not expected.exists(), "sops.yaml should be absent for this test"
        assert all(sc == expected for sc in calls)

    def test_decrypt_sops_includes_config_flag_in_cmd(self, tmp_path):
        """_decrypt_sops passes --config to subprocess when sops_config exists."""
        sops_yaml = tmp_path / "sops.yaml"
        sops_yaml.write_text("creation_rules: []\n")
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text("SECRET=value\n")

        mock_result = MagicMock()
        mock_result.stdout = "SECRET=value\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _decrypt_sops(secrets_file, sops_config=sops_yaml)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "--config" in cmd
        assert str(sops_yaml) in cmd

    def test_decrypt_sops_no_config_flag_when_sops_yaml_missing(self, tmp_path):
        """_decrypt_sops omits --config when sops_config file does not exist."""
        sops_yaml = tmp_path / "sops.yaml"  # does not exist
        assert not sops_yaml.exists()
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text("SECRET=value\n")

        mock_result = MagicMock()
        mock_result.stdout = "SECRET=value\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _decrypt_sops(secrets_file, sops_config=sops_yaml)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "--config" not in cmd


# ---------------------------------------------------------------------------
# _is_sops_encrypted — detection
# ---------------------------------------------------------------------------

class TestIsSopsEncrypted:
    def test_plain_yaml_not_detected(self, tmp_path):
        f = tmp_path / "app.yaml"
        f.write_text("database:\n  host: localhost\n")
        assert _is_sops_encrypted(f) is False

    def test_plain_json_not_detected(self, tmp_path):
        f = tmp_path / "settings.json"
        f.write_text('{"key": "value"}\n')
        assert _is_sops_encrypted(f) is False

    def test_plain_env_not_detected(self, tmp_path):
        f = tmp_path / "public.env"
        f.write_text("KEY=value\n")
        assert _is_sops_encrypted(f) is False

    def test_sops_yaml_detected(self, tmp_path):
        f = tmp_path / "secrets.yaml"
        f.write_text("database: ENC[AES256_GCM,...]\nsops:\n    version: 3.7\n")
        assert _is_sops_encrypted(f) is True

    def test_sops_json_detected(self, tmp_path):
        f = tmp_path / "secrets.json"
        f.write_text('{"key": "ENC[AES256_GCM,...]", "sops": {"version": "3.7"}}\n')
        assert _is_sops_encrypted(f) is True

    def test_sops_env_detected(self, tmp_path):
        f = tmp_path / "secrets.env"
        f.write_text("KEY=ENC[AES256_GCM,...]\nsops_version=3.7\nsops_mac=...\n")
        assert _is_sops_encrypted(f) is True

    def test_missing_file_returns_false(self, tmp_path):
        assert _is_sops_encrypted(tmp_path / "nope") is False


# ---------------------------------------------------------------------------
# load_file — auto-decrypt SOPS files
# ---------------------------------------------------------------------------

class TestLoadFileAutoDecrypt:
    def test_encrypted_file_is_decrypted(self, config_dir, tmp_path):
        """load_file auto-decrypts when SOPS markers are present."""
        encrypted = config_dir / "dev" / "secrets.yaml"
        encrypted.write_text("data: ENC[AES256_GCM,...]\nsops:\n    version: 3.7\n")
        out = tmp_path / "secrets.yaml"

        with patch("dotconfig.load._decrypt_sops", return_value="data: plaintext\n") as mock:
            load_file("dev", None, "secrets.yaml", config_dir, out, to_stdout=False)

        mock.assert_called_once()
        assert out.read_text() == "data: plaintext\n"

    def test_plain_file_not_sent_to_sops(self, config_dir, tmp_path):
        """load_file does not call _decrypt_sops for plain files."""
        plain = config_dir / "dev" / "app.yaml"
        plain.write_text("key: value\n")
        out = tmp_path / "app.yaml"

        with patch("dotconfig.load._decrypt_sops") as mock:
            load_file("dev", None, "app.yaml", config_dir, out, to_stdout=False)

        mock.assert_not_called()
        assert out.read_text() == "key: value\n"

    def test_decrypt_failure_exits(self, config_dir, tmp_path):
        """load_file exits if decryption fails."""
        encrypted = config_dir / "dev" / "secrets.yaml"
        encrypted.write_text("data: ENC[AES256_GCM,...]\nsops:\n    version: 3.7\n")

        with patch("dotconfig.load._decrypt_sops", return_value=None):
            with pytest.raises(SystemExit):
                load_file("dev", None, "secrets.yaml", config_dir, tmp_path / "out", to_stdout=False)
