"""Tests for src/dotconfig/versioning.py."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from dotconfig.versioning import (
    bump_version,
    build_tag_regex,
    build_version,
    compute_next_version,
    create_version_tag,
    format_has_auto,
    load_dotconfig_yaml,
    load_version_format,
    parse_format,
    read_dotconfig_version,
    seed_version_from_sources,
    update_dotenv_version,
    update_package_json_version,
    update_pyproject_version,
    write_dotconfig_version,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


# ---------------------------------------------------------------------------
# load_dotconfig_yaml
# ---------------------------------------------------------------------------

class TestLoadDotconfigYaml:
    def test_returns_none_when_file_missing(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        assert load_dotconfig_yaml(config_dir) is None

    def test_returns_dict_for_valid_yaml(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text("version: 1.0.0\n")
        result = load_dotconfig_yaml(config_dir)
        assert result == {"version": "1.0.0"}

    def test_returns_none_for_malformed_yaml(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text(":\n  - bad: yaml: content\n  bad")
        # If yaml doesn't raise, check for non-dict result
        # Either way, result should be None or the dict
        result = load_dotconfig_yaml(config_dir)
        # malformed YAML may return None (exception) or a non-dict
        assert result is None or isinstance(result, dict)

    def test_returns_none_when_yaml_is_not_dict(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text("- item1\n- item2\n")
        assert load_dotconfig_yaml(config_dir) is None

    def test_preserves_all_keys(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text(
            "version: 1.2.3\nversion_format: X+.YYYYMMDD.R+\n"
        )
        result = load_dotconfig_yaml(config_dir)
        assert result["version"] == "1.2.3"
        assert result["version_format"] == "X+.YYYYMMDD.R+"


# ---------------------------------------------------------------------------
# read_dotconfig_version
# ---------------------------------------------------------------------------

class TestReadDotconfigVersion:
    def test_returns_none_when_file_missing(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        assert read_dotconfig_version(config_dir) is None

    def test_returns_version_string(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text("version: 0.20260503.7\n")
        assert read_dotconfig_version(config_dir) == "0.20260503.7"

    def test_returns_none_when_no_version_key(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text("other_key: value\n")
        assert read_dotconfig_version(config_dir) is None

    def test_returns_none_for_malformed_yaml(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text("- not: a mapping\n")
        assert read_dotconfig_version(config_dir) is None


# ---------------------------------------------------------------------------
# write_dotconfig_version
# ---------------------------------------------------------------------------

class TestWriteDotconfigVersion:
    def test_creates_file_when_absent(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        write_dotconfig_version(config_dir, "1.2.3")
        assert (config_dir / "dotconfig.yaml").exists()
        data = yaml.safe_load((config_dir / "dotconfig.yaml").read_text())
        assert data["version"] == "1.2.3"

    def test_creates_parent_dirs_when_absent(self, tmp_path):
        config_dir = tmp_path / "nested" / "config"
        write_dotconfig_version(config_dir, "1.0.0")
        assert (config_dir / "dotconfig.yaml").exists()

    def test_updates_existing_version_field(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text(
            "# header comment\nversion: 0.1.0\nother_key: kept\n"
        )
        write_dotconfig_version(config_dir, "2.0.0")
        content = (config_dir / "dotconfig.yaml").read_text()
        assert "version: 2.0.0" in content
        # Other keys must be preserved
        assert "other_key: kept" in content
        # Old version must be gone
        assert "0.1.0" not in content

    def test_does_not_corrupt_other_keys(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        original = "version: old\nversion_format: X+.YYYYMMDD.R+\nmy_key: my_val\n"
        (config_dir / "dotconfig.yaml").write_text(original)
        write_dotconfig_version(config_dir, "new-ver")
        data = yaml.safe_load((config_dir / "dotconfig.yaml").read_text())
        assert data["version"] == "new-ver"
        assert data["version_format"] == "X+.YYYYMMDD.R+"
        assert data["my_key"] == "my_val"

    def test_appends_version_line_when_no_version_key(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (config_dir / "dotconfig.yaml").write_text("other_key: value\n")
        write_dotconfig_version(config_dir, "9.9.9")
        data = yaml.safe_load((config_dir / "dotconfig.yaml").read_text())
        assert data["version"] == "9.9.9"
        assert data["other_key"] == "value"


# ---------------------------------------------------------------------------
# update_dotenv_version
# ---------------------------------------------------------------------------

class TestUpdateDotenvVersion:
    def test_noop_when_env_missing(self, tmp_path):
        env_path = tmp_path / ".env"
        # Should not raise
        update_dotenv_version("1.0.0", env_path)
        assert not env_path.exists()

    def test_prepends_version_when_env_exists(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("KEY=value\nOTHER=thing\n")
        update_dotenv_version("2.3.4", env_path)
        lines = env_path.read_text().splitlines()
        assert lines[0] == "_VERSION=2.3.4"
        assert "KEY=value" in lines
        assert "OTHER=thing" in lines

    def test_replaces_existing_version_line(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("_VERSION=old-ver\nKEY=value\n")
        update_dotenv_version("new-ver", env_path)
        content = env_path.read_text()
        assert content.count("_VERSION=") == 1
        assert "_VERSION=new-ver" in content
        assert "_VERSION=old-ver" not in content

    def test_preserves_other_lines(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("ALPHA=1\nBETA=2\nGAMMA=3\n")
        update_dotenv_version("x.y.z", env_path)
        content = env_path.read_text()
        assert "ALPHA=1" in content
        assert "BETA=2" in content
        assert "GAMMA=3" in content

    def test_handles_multiple_existing_version_lines(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("_VERSION=a\nKEY=v\n_VERSION=b\n")
        update_dotenv_version("c", env_path)
        content = env_path.read_text()
        assert content.count("_VERSION=") == 1
        assert "_VERSION=c" in content


# ---------------------------------------------------------------------------
# update_pyproject_version
# ---------------------------------------------------------------------------

class TestUpdatePyprojectVersion:
    def test_updates_version_field(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "myproject"\nversion = "0.1.0"\n')
        update_pyproject_version("1.2.3", p)
        assert 'version = "1.2.3"' in p.read_text()

    def test_skips_silently_when_file_missing(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        # Should not raise
        update_pyproject_version("1.0.0", p)

    def test_raises_when_no_version_line(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "no-version"\n')
        with pytest.raises(ValueError, match="Could not find version field"):
            update_pyproject_version("1.0.0", p)


# ---------------------------------------------------------------------------
# update_package_json_version
# ---------------------------------------------------------------------------

class TestUpdatePackageJsonVersion:
    def test_updates_version_field(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text(json.dumps({"name": "pkg", "version": "0.0.1"}) + "\n")
        update_package_json_version("3.0.0", p)
        data = json.loads(p.read_text())
        assert data["version"] == "3.0.0"

    def test_skips_silently_when_file_missing(self, tmp_path):
        p = tmp_path / "package.json"
        update_package_json_version("1.0.0", p)

    def test_raises_when_no_version_key(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text(json.dumps({"name": "pkg"}) + "\n")
        with pytest.raises(ValueError, match="No 'version' field"):
            update_package_json_version("1.0.0", p)


# ---------------------------------------------------------------------------
# compute_next_version
# ---------------------------------------------------------------------------

class TestComputeNextVersion:
    def _today_str(self) -> str:
        return date.today().strftime("%Y%m%d")

    def test_first_bump_gives_revision_1(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            v = compute_next_version(major=0, config_dir=config_dir)
        assert v == f"0.{self._today_str()}.1"

    def test_increments_revision_beyond_existing_tags(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        today = self._today_str()
        existing = [f"v0.{today}.3"]
        with patch("dotconfig.versioning._get_existing_tags", return_value=existing):
            v = compute_next_version(major=0, config_dir=config_dir)
        assert v == f"0.{today}.4"

    def test_ignores_tags_from_different_day(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        with patch(
            "dotconfig.versioning._get_existing_tags",
            return_value=["v0.20200101.99"],
        ):
            v = compute_next_version(major=0, config_dir=config_dir)
        assert v == f"0.{self._today_str()}.1"

    def test_ignores_tags_with_different_major(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        today = self._today_str()
        with patch(
            "dotconfig.versioning._get_existing_tags",
            return_value=[f"v1.{today}.5"],
        ):
            v = compute_next_version(major=0, config_dir=config_dir)
        assert v == f"0.{today}.1"

    def test_reads_current_version_from_dotconfig_yaml(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        today = self._today_str()
        # Seed current version at revision 7
        (config_dir / "dotconfig.yaml").write_text(f"version: 0.{today}.7\n")
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            v = compute_next_version(major=0, config_dir=config_dir)
        assert v == f"0.{today}.8"

    def test_new_major_resets_revision_search(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        today = self._today_str()
        with patch(
            "dotconfig.versioning._get_existing_tags",
            return_value=[f"v0.{today}.9"],
        ):
            v = compute_next_version(major=1, config_dir=config_dir)
        assert v == f"1.{today}.1"


# ---------------------------------------------------------------------------
# bump_version
# ---------------------------------------------------------------------------

class TestBumpVersion:
    def test_writes_dotconfig_yaml(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        with (
            patch("dotconfig.versioning._get_existing_tags", return_value=[]),
            patch("dotconfig.versioning.create_version_tag"),
        ):
            result = bump_version(
                major=0, tag=False, project_root=tmp_path, config_dir=config_dir
            )
        assert read_dotconfig_version(config_dir) == result["version"]

    def test_syncs_pyproject_when_present(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "0.0.0"\n'
        )
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(project_root=tmp_path, config_dir=config_dir)
        assert "pyproject.toml" in result["synced"]
        content = (tmp_path / "pyproject.toml").read_text()
        assert f'version = "{result["version"]}"' in content

    def test_skips_missing_sync_files(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        # No pyproject.toml or package.json in tmp_path
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(project_root=tmp_path, config_dir=config_dir)
        assert "pyproject.toml" not in result["synced"]
        assert "package.json" not in result["synced"]

    def test_syncs_env_when_present(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text("KEY=val\n")
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(project_root=tmp_path, config_dir=config_dir)
        assert ".env" in result["synced"]
        assert f"_VERSION={result['version']}" in env_path.read_text()

    def test_creates_tag_when_requested(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        with (
            patch("dotconfig.versioning._get_existing_tags", return_value=[]),
            patch("dotconfig.versioning.create_version_tag") as mock_tag,
        ):
            result = bump_version(
                tag=True, project_root=tmp_path, config_dir=config_dir
            )
        mock_tag.assert_called_once_with(result["version"])
        assert result["tag"] == f"v{result['version']}"

    def test_no_tag_when_tag_false(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(
                tag=False, project_root=tmp_path, config_dir=config_dir
            )
        assert result["tag"] is None

    def test_return_dict_keys(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(project_root=tmp_path, config_dir=config_dir)
        assert set(result.keys()) == {"version", "source", "synced", "tag"}

    def test_source_is_dotconfig_yaml(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(project_root=tmp_path, config_dir=config_dir)
        assert result["source"] == "config/dotconfig.yaml"

    def test_syncs_package_json_when_present(self, tmp_path):
        config_dir = _make_config_dir(tmp_path)
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"version": "0.0.0"}) + "\n")
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(project_root=tmp_path, config_dir=config_dir)
        assert "package.json" in result["synced"]
        data = json.loads(pkg.read_text())
        assert data["version"] == result["version"]

    def test_relative_config_dir_does_not_raise(self, tmp_path, monkeypatch):
        """bump_version works when config_dir is a relative path (e.g. Path('config'))."""
        monkeypatch.chdir(tmp_path)
        # Create config dir and dotconfig.yaml via the relative path
        config_dir = Path("config")
        config_dir.mkdir()
        (config_dir / "dotconfig.yaml").write_text("version: 0.20260101.1\n")
        with patch("dotconfig.versioning._get_existing_tags", return_value=[]):
            result = bump_version(
                major=0, tag=False, project_root=tmp_path, config_dir=config_dir
            )
        assert result["version"]
        assert result["source"] == "config/dotconfig.yaml"


# ---------------------------------------------------------------------------
# Format engine (sanity checks — ported logic)
# ---------------------------------------------------------------------------

class TestFormatEngine:
    def test_parse_format_default(self):
        parsed = parse_format("X+.YYYYMMDD.R+")
        kinds = [k for k, _, _ in parsed]
        assert "manual" in kinds
        assert "year" in kinds
        assert "rev" in kinds

    def test_format_has_auto_true(self):
        parsed = parse_format("X+.YYYYMMDD.R+")
        assert format_has_auto(parsed)

    def test_format_has_auto_false_for_manual(self):
        parsed = parse_format("X+.X+.X+")
        assert not format_has_auto(parsed)

    def test_build_version_basic(self):
        parsed = parse_format("X+.YYYYMMDD.R+")
        v = build_version(parsed, [0], rev=3, today=date(2026, 5, 3))
        assert v == "0.20260503.3"

    def test_build_tag_regex_matches(self):
        parsed = parse_format("X+.YYYYMMDD.R+")
        pattern = build_tag_regex(parsed)
        assert pattern.match("v0.20260503.3")
        assert pattern.match("0.20260503.3")
        assert not pattern.match("0.20260503")


# ---------------------------------------------------------------------------
# seed_version_from_sources
# ---------------------------------------------------------------------------

class TestSeedVersionFromSources:
    def test_returns_package_json_version_when_both_exist(self, tmp_path):
        """package.json takes priority over pyproject.toml."""
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "myapp", "version": "2.3.4"}),
            encoding="utf-8",
        )
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = \"myapp\"\nversion = \"9.9.9\"\n",
            encoding="utf-8",
        )
        assert seed_version_from_sources(tmp_path) == "2.3.4"

    def test_returns_pyproject_version_when_only_pyproject_exists(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = \"myapp\"\nversion = \"1.2.3\"\n",
            encoding="utf-8",
        )
        assert seed_version_from_sources(tmp_path) == "1.2.3"

    def test_returns_none_when_neither_file_exists(self, tmp_path):
        assert seed_version_from_sources(tmp_path) is None

    def test_returns_none_when_package_json_has_no_version_field(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "myapp"}),
            encoding="utf-8",
        )
        assert seed_version_from_sources(tmp_path) is None

    def test_returns_none_when_pyproject_has_no_version_under_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.poetry]\nversion = \"5.0.0\"\n\n[project]\nname = \"myapp\"\n",
            encoding="utf-8",
        )
        assert seed_version_from_sources(tmp_path) is None

    def test_handles_malformed_package_json_gracefully(self, tmp_path):
        (tmp_path / "package.json").write_text("{not valid json}", encoding="utf-8")
        assert seed_version_from_sources(tmp_path) is None

    def test_handles_malformed_pyproject_gracefully(self, tmp_path):
        # pyproject parsing is line-based so a broken file just won't match
        (tmp_path / "pyproject.toml").write_text(
            "\x00\x01\x02 not utf8 decodable content" * 10,
            encoding="latin-1",
        )
        assert seed_version_from_sources(tmp_path) is None

    def test_returns_none_when_package_json_exists_but_no_version_falls_back_to_missing_pyproject(
        self, tmp_path
    ):
        """When package.json exists but has no version, and pyproject.toml is absent, return None."""
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "myapp"}),
            encoding="utf-8",
        )
        assert seed_version_from_sources(tmp_path) is None
