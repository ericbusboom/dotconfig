"""Tests for label-aware sops.yaml parse/render (sprint 008, ticket 003)."""

import os
import shutil
import subprocess

import pytest

from dotconfig.init import (
    _merge_key_entries,
    _parse_sops_keys,
    _render_sops_yaml,
    _update_sops_yaml,
)

K1, K2, K3 = "age1aaa", "age1bbb", "age1ccc"


def test_parse_block_scalar():
    c = f"creation_rules:\n  - path_regex: '.+'\n    age: >-\n      {K1},\n      {K2}\n"
    assert _parse_sops_keys(c) == [(K1, None), (K2, None)]


def test_parse_inline_string():
    c = f"creation_rules:\n  - path_regex: '.+'\n    age: {K1},{K2}\n"
    assert _parse_sops_keys(c) == [(K1, None), (K2, None)]


def test_parse_list_with_labels():
    c = (
        "creation_rules:\n  - path_regex: '.+'\n    age:\n"
        f"      - {K1}  # alice\n      - {K2}\n"
    )
    assert _parse_sops_keys(c) == [(K1, "alice"), (K2, None)]


def test_parse_key_groups_with_labels():
    c = _render_sops_yaml([(K1, "alice"), (K2, "bob laptop")])
    assert _parse_sops_keys(c) == [(K1, "alice"), (K2, "bob laptop")]


def test_round_trip_order_and_unlabeled_no_comment():
    entries = [(K2, "b"), (K1, None), (K3, "c")]
    out = _render_sops_yaml(entries)
    assert _parse_sops_keys(out) == entries
    assert f"- {K1}\n" in out


def test_label_sanitized():
    out = _render_sops_yaml([(K1, "evil\nage: x # y")])
    assert len(out.splitlines()) == 6
    assert _parse_sops_keys(out) == [(K1, "evil age: x # y")]


def test_merge_keeps_existing_label_and_override():
    existing = [(K1, "old"), (K2, "keep")]
    merged = _merge_key_entries(existing, [(K1, "new"), (K2, None), (K3, "c")])
    assert merged == [(K1, "new"), (K2, "keep"), (K3, "c")]


def test_update_preserves_labels(tmp_path):
    (tmp_path / "sops.yaml").write_text(_render_sops_yaml([(K1, "alice")]))
    _update_sops_yaml(tmp_path, K2, quiet=True)
    assert _parse_sops_keys((tmp_path / "sops.yaml").read_text()) == [
        (K1, "alice"),
        (K2, None),
    ]


def test_public_rule_unchanged():
    out = _render_sops_yaml([K1])
    assert "  - path_regex: '(^|/)public\\.env$'\n  - path_regex: '.+'\n" in out


@pytest.mark.skipif(
    not (shutil.which("sops") and shutil.which("age-keygen")),
    reason="sops/age-keygen not installed",
)
def test_real_sops_round_trip(tmp_path):
    def gen(name):
        f = tmp_path / name
        subprocess.run(["age-keygen", "-o", str(f)], check=True, capture_output=True)
        pub = subprocess.run(
            ["age-keygen", "-y", str(f)], check=True, capture_output=True, text=True
        ).stdout.strip()
        return f, pub

    f1, p1 = gen("k1.txt")
    f2, p2 = gen("k2.txt")
    (tmp_path / "sops.yaml").write_text(_render_sops_yaml([(p1, "one"), (p2, "two")]))
    plain = tmp_path / "x.env"
    plain.write_text("A=1\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOPS_AGE")}
    enc = subprocess.run(
        ["sops", "--config", str(tmp_path / "sops.yaml"), "--encrypt",
         "--input-type", "dotenv", "--output-type", "dotenv", str(plain)],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    assert enc.returncode == 0, enc.stderr
    (tmp_path / "x.enc.env").write_text(enc.stdout)
    for keyfile in (f1, f2):
        dec = subprocess.run(
            ["sops", "--decrypt", "--input-type", "dotenv", "--output-type", "dotenv",
             str(tmp_path / "x.enc.env")],
            capture_output=True, text=True, cwd=tmp_path,
            env={**env, "SOPS_AGE_KEY_FILE": str(keyfile)},
        )
        assert dec.returncode == 0, dec.stderr
        assert "A=1" in dec.stdout
