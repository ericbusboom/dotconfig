"""Tests for dotconfig.key — key management commands."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dotconfig.key import (
    gen_key,
    get_key,
    list_keys,
    pub_key,
    rm_key,
    save_key,
    send_key,
)


@pytest.fixture
def keys_dir(tmp_path):
    """Create a config/keys/ structure."""
    cfg = tmp_path / "config"
    keys = cfg / "keys"
    keys.mkdir(parents=True)
    return keys


@pytest.fixture
def config_dir(tmp_path):
    """Return the config dir path."""
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    return cfg


class TestGenKey:
    def test_generates_ed25519_keypair(self, config_dir, capsys):
        with patch("dotconfig.key.subprocess.run") as mock_run, \
             patch("dotconfig.key._encrypt_sops", return_value=True):
            # Simulate ssh-keygen creating the files
            def fake_keygen(*args, **kwargs):
                cmd = args[0]
                # Find the -f argument
                f_idx = cmd.index("-f")
                priv_path = Path(cmd[f_idx + 1])
                priv_path.write_text("FAKE PRIVATE KEY")
                pub_path = Path(str(priv_path) + ".pub")
                pub_path.write_text("ssh-ed25519 AAAA fake")
                return MagicMock(returncode=0)

            mock_run.side_effect = fake_keygen
            gen_key("deploy", config_dir=config_dir)

        out = capsys.readouterr().out
        assert "deploy_ed25519" in out

    def test_rejects_invalid_type(self, config_dir):
        with pytest.raises(SystemExit):
            gen_key("deploy", key_type="dsa", config_dir=config_dir)

    def test_rejects_existing_key(self, config_dir):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "deploy_ed25519").write_text("exists")
        with pytest.raises(SystemExit):
            gen_key("deploy", config_dir=config_dir)


class TestSaveKey:
    def test_saves_and_encrypts_key(self, config_dir, tmp_path, capsys):
        key_file = tmp_path / "my_key"
        key_file.write_text("PRIVATE KEY CONTENT")
        pub_file = tmp_path / "my_key.pub"
        pub_file.write_text("ssh-ed25519 AAAA test")

        with patch("dotconfig.key._encrypt_sops", return_value=True):
            save_key(key_file, config_dir=config_dir)

        out = capsys.readouterr().out
        assert "my_key" in out
        # Check .pub was copied
        assert (config_dir / "keys" / "my_key.pub").exists()

    def test_custom_name(self, config_dir, tmp_path, capsys):
        key_file = tmp_path / "id_rsa"
        key_file.write_text("PRIVATE KEY")

        with patch("dotconfig.key._encrypt_sops", return_value=True):
            save_key(key_file, name="deploy", config_dir=config_dir)

        out = capsys.readouterr().out
        assert "deploy" in out

    def test_file_not_found(self, config_dir, tmp_path):
        with pytest.raises(SystemExit):
            save_key(tmp_path / "nonexistent", config_dir=config_dir)


class TestGetKey:
    def test_prints_decrypted_key(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        priv = keys / "deploy_ed25519"
        priv.write_text("ENCRYPTED CONTENT")

        with patch("dotconfig.key._is_sops_encrypted", return_value=True), \
             patch("dotconfig.key._decrypt_sops", return_value="DECRYPTED KEY"):
            get_key("deploy", config_dir=config_dir)

        out = capsys.readouterr().out
        assert "DECRYPTED KEY" in out

    def test_prints_plaintext_key(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        priv = keys / "mykey"
        priv.write_text("PLAIN KEY")

        with patch("dotconfig.key._is_sops_encrypted", return_value=False):
            get_key("mykey", config_dir=config_dir)

        out = capsys.readouterr().out
        assert "PLAIN KEY" in out

    def test_key_not_found(self, config_dir):
        (config_dir / "keys").mkdir(exist_ok=True)
        with pytest.raises(SystemExit):
            get_key("nonexistent", config_dir=config_dir)


class TestPubKey:
    def test_prints_pub_file(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "deploy_ed25519").write_text("private")
        (keys / "deploy_ed25519.pub").write_text("ssh-ed25519 AAAA test")

        pub_key("deploy", config_dir=config_dir)

        out = capsys.readouterr().out
        assert "ssh-ed25519 AAAA test" in out

    def test_derives_from_private(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "deploy_ed25519").write_text("private key content")

        with patch("dotconfig.key._is_sops_encrypted", return_value=False), \
             patch("dotconfig.key.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="ssh-ed25519 AAAA derived",
                returncode=0,
            )
            pub_key("deploy", config_dir=config_dir)

        out = capsys.readouterr().out
        assert "ssh-ed25519 AAAA derived" in out


class TestListKeys:
    def test_lists_keys(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "deploy_ed25519").write_text("private")
        (keys / "deploy_ed25519.pub").write_text("public")
        (keys / "github_rsa").write_text("private2")

        with patch("dotconfig.key._is_sops_encrypted", return_value=False):
            list_keys(config_dir=config_dir)

        out = capsys.readouterr().out
        assert "deploy_ed25519" in out
        assert "github_rsa" in out

    def test_empty_list(self, config_dir, capsys):
        (config_dir / "keys").mkdir(exist_ok=True)
        list_keys(config_dir=config_dir)
        out = capsys.readouterr().out
        assert "no keys found" in out


class TestRmKey:
    def test_removes_key_and_pub(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        priv = keys / "deploy_ed25519"
        pub = keys / "deploy_ed25519.pub"
        priv.write_text("private")
        pub.write_text("public")

        rm_key("deploy", config_dir=config_dir)

        assert not priv.exists()
        assert not pub.exists()

    def test_key_not_found(self, config_dir):
        (config_dir / "keys").mkdir(exist_ok=True)
        with pytest.raises(SystemExit):
            rm_key("nonexistent", config_dir=config_dir)


class TestSendKey:
    def test_sends_key_with_host_as_name(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "myhost_ed25519").write_text("private")
        (keys / "myhost_ed25519.pub").write_text("ssh-ed25519 AAAA test")

        with patch("dotconfig.key.shutil.which", return_value="/usr/bin/ssh-copy-id"), \
             patch("dotconfig.key.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            send_key("myhost", config_dir=config_dir)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ssh-copy-id"
        assert "myhost" in cmd

    def test_sends_key_with_override_name(self, config_dir, capsys):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "deploy_ed25519").write_text("private")
        (keys / "deploy_ed25519.pub").write_text("ssh-ed25519 AAAA test")

        with patch("dotconfig.key.shutil.which", return_value="/usr/bin/ssh-copy-id"), \
             patch("dotconfig.key.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            send_key("myhost", key_name="deploy", config_dir=config_dir)

        cmd = mock_run.call_args[0][0]
        assert "myhost" in cmd
        assert "deploy_ed25519.pub" in cmd[2]

    def test_key_not_found(self, config_dir):
        (config_dir / "keys").mkdir(exist_ok=True)
        with pytest.raises(SystemExit):
            send_key("myhost", config_dir=config_dir)

    def test_no_pub_key(self, config_dir):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "myhost").write_text("private")

        with pytest.raises(SystemExit):
            send_key("myhost", config_dir=config_dir)

    def test_ssh_copy_id_not_found(self, config_dir):
        keys = config_dir / "keys"
        keys.mkdir(exist_ok=True)
        (keys / "myhost").write_text("private")
        (keys / "myhost.pub").write_text("public")

        with patch("dotconfig.key.shutil.which", return_value=None):
            with pytest.raises(SystemExit):
                send_key("myhost", config_dir=config_dir)
