import pytest

from dotconfig import paths, userconfig

K1 = "age1" + "a" * 58
K2 = "age1" + "b" * 58


def write(text):
    p = paths.user_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_valid_ordered_and_missing_label():
    write(f"public_keys:\n  - key: {K1}\n    name: a@b\n  - key: {K2}\n")
    assert userconfig.load_public_keys() == [(K1, "a@b"), (K2, None)]


def test_missing_and_empty_file():
    assert userconfig.load_public_keys() == []
    write("")
    assert userconfig.load_public_keys() == []


def test_invalid_entries_skipped_with_warning(capsys):
    p = write(f"public_keys:\n  - key: ssh-rsa AAA\n  - name: x\n  - nope\n  - key: {K1}\n")
    assert userconfig.load_public_keys() == [(K1, None)]
    err = capsys.readouterr().err
    assert str(p) in err and err.count("skipped") == 3


@pytest.mark.parametrize("text", ["public_keys: [\n  : bad", "public_keys: nope\n", "- a\n- b\n"])
def test_malformed_warns_returns_empty(text, capsys):
    p = write(text)
    assert userconfig.load_public_keys() == []
    assert str(p) in capsys.readouterr().err


def test_duplicates_first_label_wins():
    write(f"public_keys:\n  - key: {K1}\n    name: first\n  - key: {K1}\n    name: second\n")
    assert userconfig.load_public_keys() == [(K1, "first")]


def test_seed_creates_and_does_not_overwrite(monkeypatch):
    monkeypatch.setattr("getpass.getuser", lambda: "alice")
    monkeypatch.setattr("socket.gethostname", lambda: "box")
    assert userconfig.seed_user_config(K1) is True
    p = paths.user_config_path()
    assert p.is_file()
    assert userconfig.load_public_keys() == [(K1, "alice@box")]
    assert userconfig.seed_user_config(K2) is False
    assert userconfig.load_public_keys() == [(K1, "alice@box")]


def test_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert userconfig.seed_user_config(K1)
    assert (tmp_path / "xdg" / "dotconfig" / "config.yaml").is_file()
