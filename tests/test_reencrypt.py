"""Tests for dotconfig.reencrypt."""

from pathlib import Path
from unittest.mock import patch

import pytest

from dotconfig.reencrypt import reencrypt_all


@pytest.fixture
def config_dir(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    return cfg


def _fake_encrypt(content, dest, sops_cfg):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"ENC({content})")
    return True


def test_reencrypts_all_encrypted_files(config_dir):
    a = config_dir / "dev" / "secrets.yaml"
    b = config_dir / "prod" / "secrets.yaml"
    plaintext = config_dir / "dev" / "public.yaml"
    for p, content in ((a, "ENC(original-a)"), (b, "ENC(original-b)")):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    plaintext.write_text("foo: bar\n")

    def fake_is_encrypted(path):
        return path.read_text().startswith("ENC(")

    def fake_decrypt(path, sops_cfg):
        return path.read_text()[4:-1]  # strip ENC(...)

    with patch("dotconfig.reencrypt._is_sops_encrypted", side_effect=fake_is_encrypted), \
         patch("dotconfig.reencrypt._decrypt_sops", side_effect=fake_decrypt), \
         patch("dotconfig.reencrypt._encrypt_sops", side_effect=_fake_encrypt) as mock_enc:
        reencrypt_all(config_dir)

    assert mock_enc.call_count == 2
    # plaintext file should not have been touched
    assert plaintext.read_text() == "foo: bar\n"
    # encrypted files round-tripped through ENC()
    assert a.read_text() == "ENC(original-a)"
    assert b.read_text() == "ENC(original-b)"


def test_no_files_is_noop(config_dir, capsys):
    (config_dir / "dev").mkdir()
    (config_dir / "dev" / "public.yaml").write_text("foo: bar\n")

    with patch("dotconfig.reencrypt._is_sops_encrypted", return_value=False), \
         patch("dotconfig.reencrypt._encrypt_sops") as mock_enc:
        reencrypt_all(config_dir)

    mock_enc.assert_not_called()
    assert "no SOPS-encrypted files found" in capsys.readouterr().out


def test_decrypt_failure_aborts(config_dir):
    target = config_dir / "dev" / "secrets.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("ENC(...)")

    with patch("dotconfig.reencrypt._is_sops_encrypted", return_value=True), \
         patch("dotconfig.reencrypt._decrypt_sops", return_value=None), \
         patch("dotconfig.reencrypt._encrypt_sops") as mock_enc, \
         pytest.raises(SystemExit):
        reencrypt_all(config_dir)

    mock_enc.assert_not_called()


def test_encrypt_failure_aborts(config_dir):
    target = config_dir / "dev" / "secrets.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("ENC(stuff)")

    with patch("dotconfig.reencrypt._is_sops_encrypted", return_value=True), \
         patch("dotconfig.reencrypt._decrypt_sops", return_value="stuff"), \
         patch("dotconfig.reencrypt._encrypt_sops", return_value=False), \
         pytest.raises(SystemExit):
        reencrypt_all(config_dir)


def test_missing_config_dir_aborts(tmp_path):
    with pytest.raises(SystemExit):
        reencrypt_all(tmp_path / "does-not-exist")
