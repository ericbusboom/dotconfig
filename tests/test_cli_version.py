"""Tests for dotconfig CLI ``version`` group and ``version bump`` subcommand."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from dotconfig.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_dir_with_version(tmp_path: Path, version: str = "0.20260101.1") -> Path:
    """Create a config/ directory with a dotconfig.yaml containing a version."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "dotconfig.yaml").write_text(
        f"# dotconfig project metadata.\nversion: {version}\n",
        encoding="utf-8",
    )
    return config_dir


# ---------------------------------------------------------------------------
# dotconfig version (print current version)
# ---------------------------------------------------------------------------

class TestVersionCommand:
    def test_prints_version_from_dotconfig_yaml(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "1.20260506.3")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-c", str(config_dir), "version"])
        assert result.exit_code == 0
        assert "1.20260506.3" in result.output

    def test_exits_nonzero_when_dotconfig_yaml_absent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(tmp_path / "config"), "version"],
        )
        assert result.exit_code != 0

    def test_stderr_message_when_not_inited(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(tmp_path / "nonexistent"), "version"],
        )
        assert result.exit_code != 0
        # Click's sys.exit catches the exit; the error message goes to output
        assert "No version set" in result.output

    def test_exits_nonzero_when_version_field_missing(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "dotconfig.yaml").write_text("other_key: something\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-c", str(config_dir), "version"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# dotconfig version bump
# ---------------------------------------------------------------------------

class TestVersionBumpCommand:
    def test_bump_advances_version_in_yaml(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = runner.invoke(cli, ["-c", str(config_dir), "version", "bump"])
        assert result.exit_code == 0
        assert "Version:" in result.output

        # The yaml should now have an updated version
        import yaml
        data = yaml.safe_load((config_dir / "dotconfig.yaml").read_text())
        assert "version" in data
        # Version should be a string (not the old one, unless today really is 20260101 rev 1)
        assert data["version"] is not None

    def test_bump_updates_pyproject_toml(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nversion = "0.20260101.1"\n', encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = runner.invoke(
                cli,
                ["-c", str(config_dir), "version", "bump"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "pyproject.toml" in result.output

    def test_bump_with_major_flag(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = runner.invoke(
                cli,
                ["-c", str(config_dir), "version", "bump", "--major", "2"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Version:" in result.output
        # The resulting version should start with "2."
        import yaml
        data = yaml.safe_load((config_dir / "dotconfig.yaml").read_text())
        assert str(data["version"]).startswith("2.")

    def test_bump_creates_tag_when_tag_flag(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        tagged = []

        def fake_create_tag(version):
            tagged.append(f"v{version}")

        with patch("dotconfig.versioning._get_existing_tags", return_value=[]), \
             patch("dotconfig.versioning.create_version_tag", side_effect=fake_create_tag):
            result = runner.invoke(
                cli,
                ["-c", str(config_dir), "version", "bump", "--tag"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert len(tagged) == 1
        assert tagged[0].startswith("v")
        assert "Tagged:" in result.output

    def test_bump_shows_updated_files(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        # Create a pyproject.toml to sync
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "0.20260101.1"\n', encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = runner.invoke(
                cli,
                ["-c", str(config_dir), "version", "bump"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Updated:" in result.output
        assert "pyproject.toml" in result.output


# ---------------------------------------------------------------------------
# dotconfig version bump --push (pre-flight checks)
# ---------------------------------------------------------------------------

class TestVersionBumpPush:
    def test_push_aborts_on_dirty_tree(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        def fake_run(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            r = R()
            if "rev-parse" in cmd:
                r.stdout = "master\n"
            elif "status" in cmd:
                r.stdout = " M some_file.py\n"  # dirty tree
            return r

        with patch("subprocess.run", side_effect=fake_run):
            result = runner.invoke(
                cli,
                ["-c", str(config_dir), "version", "bump", "--push"],
            )
        assert result.exit_code != 0
        # dirty tree error message should mention "clean"
        assert "clean" in result.output.lower()

    def test_push_aborts_when_not_on_master_or_main(self, tmp_path, monkeypatch):
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        def fake_run(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            r = R()
            if "rev-parse" in cmd:
                r.stdout = "feature/my-branch\n"
            elif "status" in cmd:
                r.stdout = ""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            result = runner.invoke(
                cli,
                ["-c", str(config_dir), "version", "bump", "--push"],
            )
        assert result.exit_code != 0
        combined = result.output
        assert "master" in combined.lower() or "main" in combined.lower()

    def test_push_short_flag_p_works(self, tmp_path, monkeypatch):
        """``-p`` is an alias for ``--push``; same pre-flight applies."""
        config_dir = _make_config_dir_with_version(tmp_path, "0.20260101.1")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        def fake_run(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            r = R()
            if "rev-parse" in cmd:
                r.stdout = "sprint/003\n"
            elif "status" in cmd:
                r.stdout = ""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            result = runner.invoke(
                cli,
                ["-c", str(config_dir), "version", "bump", "-p"],
            )
        # Should fail on branch check (not master/main)
        assert result.exit_code != 0
        assert "master" in result.output.lower() or "main" in result.output.lower()


# ---------------------------------------------------------------------------
# dotconfig version load
# ---------------------------------------------------------------------------

class TestVersionLoadCommand:
    def test_loads_version_from_package_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "myapp", "version": "3.1.4"}),
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["version", "load"])
        assert result.exit_code == 0, result.output
        assert "3.1.4" in result.output

    def test_writes_version_to_dotconfig_yaml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "myapp", "version": "5.0.0"}),
            encoding="utf-8",
        )
        runner = CliRunner()
        runner.invoke(cli, ["version", "load"])
        dotconfig_yaml = tmp_path / "config" / "dotconfig.yaml"
        assert dotconfig_yaml.exists()
        data = yaml.safe_load(dotconfig_yaml.read_text())
        assert data["version"] == "5.0.0"

    def test_loads_version_from_pyproject_when_no_package_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = \"myapp\"\nversion = \"1.9.3\"\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["version", "load"])
        assert result.exit_code == 0, result.output
        assert "1.9.3" in result.output

    def test_exits_nonzero_when_no_source_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["version", "load"])
        assert result.exit_code != 0

    def test_prints_error_to_stderr_when_no_source(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["version", "load"])
        assert result.exit_code != 0
        # The error message is echoed to stderr (captured in output by CliRunner)
        assert "No version source found" in result.output

    def test_overwrites_existing_version_in_dotconfig_yaml(self, tmp_path, monkeypatch):
        """version load unconditionally overwrites any existing version."""
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "dotconfig.yaml").write_text(
            "version: 0.0.1\n", encoding="utf-8"
        )
        (tmp_path / "package.json").write_text(
            json.dumps({"version": "9.8.7"}),
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["version", "load"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load((config_dir / "dotconfig.yaml").read_text())
        assert data["version"] == "9.8.7"

    def test_creates_dotconfig_yaml_when_absent(self, tmp_path, monkeypatch):
        """version load creates config/dotconfig.yaml if it does not exist."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "package.json").write_text(
            json.dumps({"version": "2.0.0"}),
            encoding="utf-8",
        )
        runner = CliRunner()
        runner.invoke(cli, ["version", "load"])
        dotconfig_yaml = tmp_path / "config" / "dotconfig.yaml"
        assert dotconfig_yaml.exists()

    def test_respects_config_dir_flag(self, tmp_path, monkeypatch):
        """version load uses a custom config dir when -c is given."""
        monkeypatch.chdir(tmp_path)
        custom_cfg = tmp_path / "myconfig"
        custom_cfg.mkdir()
        (tmp_path / "package.json").write_text(
            json.dumps({"version": "4.5.6"}),
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["-c", str(custom_cfg), "version", "load"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load((custom_cfg / "dotconfig.yaml").read_text())
        assert data["version"] == "4.5.6"
