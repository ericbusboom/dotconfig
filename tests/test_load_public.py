"""Tests for ``dotconfig load --public`` (secrets blanked, never decrypted)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from dotconfig.cli import cli
from dotconfig.load import PUBLIC_MARKER, _blank_secrets, load_config
from dotconfig.save import save_config

SOPS_DOTENV = (
    "SESSION_SECRET=ENC[AES256_GCM,data:abc,iv:x,tag:y,type:str]\n"
    "export API_TOKEN=ENC[AES256_GCM,data:def,iv:x,tag:y,type:str]\n"
    "#ENC[AES256_GCM,data:comment,type:comment]\n"
    "sops_age__list_0__map_recipient=age1xyz\n"
    "sops_mac=ENC[AES256_GCM,data:mac]\n"
    "sops_version=3.9.0\n"
)


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    (cfg / "prod").mkdir(parents=True)
    (cfg / "prod" / "public.env").write_text("APP_DOMAIN=prod.example.com\nPORT=8080\n")
    (cfg / "prod" / "secrets.env").write_text(SOPS_DOTENV)
    (cfg / "local" / "alice").mkdir(parents=True)
    (cfg / "local" / "alice" / "public.env").write_text("DEBUG=1\n")
    (cfg / "local" / "alice" / "secrets.env").write_text("ALICE_KEY=ENC[x]\nsops_version=3\n")
    return cfg


def _no_decrypt(*_a, **_k):
    raise AssertionError("--public must never decrypt")


class TestBlankSecrets:
    def test_keeps_keys_blanks_values_drops_sops_meta_and_comments(self):
        assert _blank_secrets(SOPS_DOTENV) == "SESSION_SECRET=\nexport API_TOKEN="

    def test_plain_values_blanked(self):
        assert _blank_secrets("A=1\nB = two\n\nA=3\n") == "A=\nB="


class TestLoadConfigPublic:
    def test_env_output_blanks_secrets_and_marks_file(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", side_effect=_no_decrypt):
            load_config("prod", "alice", config_dir, out, public_only=True)
        text = out.read_text()
        assert PUBLIC_MARKER in text.splitlines()
        assert "APP_DOMAIN=prod.example.com" in text
        assert "SESSION_SECRET=\n" in text
        assert "export API_TOKEN=\n" in text
        assert "ALICE_KEY=\n" in text
        assert "ENC[" not in text and "sops_" not in text

    def test_works_while_key_locked(self, config_dir, tmp_path, monkeypatch):
        # Simulate a locked key: plain key missing, wrapped copy present.
        key = tmp_path / "age" / "keys.txt"
        key.parent.mkdir()
        (key.parent / "keys.txt.pass.age").write_text("x")
        monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(key))
        monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
        out = tmp_path / ".env"
        load_config("prod", None, config_dir, out, public_only=True)
        assert "SESSION_SECRET=\n" in out.read_text()

    def test_split_mode(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        load_config("prod", None, config_dir, out, split=True, public_only=True)
        assert PUBLIC_MARKER in out.read_text()
        assert (tmp_path / ".env.secret").read_text() == "SESSION_SECRET=\nexport API_TOKEN=\n"

    def test_yaml_output_marked(self, config_dir, tmp_path):
        out = tmp_path / ".env.yaml"
        load_config("prod", None, config_dir, out, fmt="yaml", public_only=True)
        data = yaml.safe_load(out.read_text())
        assert data["_dotconfig"]["public"] is True
        assert data["prod"]["secrets"] == {"SESSION_SECRET": "", "API_TOKEN": ""}

    def test_default_load_unmarked(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        with patch("dotconfig.load._decrypt_sops", return_value="SESSION_SECRET=real\n"):
            load_config("prod", None, config_dir, out)
        assert PUBLIC_MARKER not in out.read_text()


class TestSaveRefusesPublic:
    def test_env(self, config_dir, tmp_path):
        out = tmp_path / ".env"
        load_config("prod", None, config_dir, out, public_only=True)
        before = (config_dir / "prod" / "secrets.env").read_text()
        with pytest.raises(SystemExit) as exc:
            save_config(out, config_dir)
        assert exc.value.code == 1
        assert (config_dir / "prod" / "secrets.env").read_text() == before

    def test_json(self, config_dir, tmp_path):
        out = tmp_path / ".env.json"
        load_config("prod", None, config_dir, out, fmt="json", public_only=True)
        assert json.loads(out.read_text())["_dotconfig"]["public"] is True
        with pytest.raises(SystemExit):
            save_config(out, config_dir)


class TestCliPublic:
    def _run(self, config_dir, args):
        return CliRunner().invoke(cli, ["-c", str(config_dir), "load", *args])

    def test_reloads_current_env_without_names(self, config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "# CONFIG_DEPLOY=prod\n# CONFIG_LOCAL=alice\n\n"
            "#@dotconfig: secrets (prod)\nSESSION_SECRET=real-secret\n"
        )
        with patch("dotconfig.load._decrypt_sops", side_effect=_no_decrypt):
            result = self._run(config_dir, ["--public"])
        assert result.exit_code == 0, result.output
        text = (tmp_path / ".env").read_text()
        assert "# CONFIG_DEPLOY=prod" in text
        assert "# CONFIG_LOCAL=alice" in text
        assert "real-secret" not in text
        assert "SESSION_SECRET=\n" in text
        assert "ALICE_KEY=\n" in text

    def test_explicit_deployment(self, config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self._run(config_dir, ["prod", "--public"])
        assert result.exit_code == 0, result.output
        assert PUBLIC_MARKER in (tmp_path / ".env").read_text()

    def test_no_env_and_no_names_errors(self, config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self._run(config_dir, ["--public"])
        assert result.exit_code == 2
        assert "pass a deployment name" in result.output

    def test_env_without_header_errors(self, config_dir, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("FOO=1\n")
        result = self._run(config_dir, ["--public"])
        assert result.exit_code == 2
        assert "CONFIG_DEPLOY" in result.output

    @pytest.mark.parametrize("extra", [["--file", "x.yaml"], ["-e", "CERT_FILE"], ["--json", "--flat"]])
    def test_incompatible_options(self, config_dir, tmp_path, monkeypatch, extra):
        monkeypatch.chdir(tmp_path)
        result = self._run(config_dir, ["prod", "--public", *extra])
        assert result.exit_code == 2
        assert "--public cannot be used" in result.output
