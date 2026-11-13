from click.testing import CliRunner

from dotconfig.cli import cli


def test_where_outside_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli, ["where"])
    assert r.exit_code == 0, r.output
    assert "No config root found" in r.output
    assert "age key file" in r.output and "user config" in r.output
    assert "[env," in r.output  # SOPS_AGE_KEY_FILE set by fixture


def test_where_in_project(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sops.yaml").write_text("x")
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli, ["where"])
    assert r.exit_code == 0, r.output
    assert "No config root found" not in r.output
    assert "sops.yaml" in r.output and "exists" in r.output
    assert "AGENTS.md" in r.output


def test_where_explicit_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "elsewhere"
    d.mkdir()
    r = CliRunner().invoke(cli, ["-c", str(d), "where"])
    assert r.exit_code == 0 and str(d) in r.output
