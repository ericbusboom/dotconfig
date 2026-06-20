"""Versioning utilities for the dotconfig project.

The source of truth for the version is ``config/dotconfig.yaml`` (key:
``version``).  ``pyproject.toml``, ``package.json``, and the active
``.env`` are *sync targets* that ``bump`` writes to whenever they exist.

Default format: X+.YYYYMMDD.R+

Format tokens:
    X      — manual segment, exactly 1 digit
    XX     — manual segment, exactly 2 digits
    X+     — manual segment, one or more digits (variable width)
    0XX    — manual segment, exactly 2 digits, zero-padded
    0XXX   — manual segment, exactly 3 digits, zero-padded
    YYYY   — four-digit year
    MM     — two-digit month
    DD     — two-digit day
    R      — auto-incrementing revision, exactly 1 digit
    RR     — revision, exactly 2 digits
    R+     — revision, one or more digits (variable width)
    0RR    — revision, exactly 2 digits, zero-padded
    0RRR   — revision, exactly 3 digits, zero-padded
    .      — literal dot separator

Fully manual formats (no R or date tokens) produce X.X.X style versions
that are not auto-computed.
"""

import json
import re
import subprocess
from datetime import date
from pathlib import Path

import yaml

DEFAULT_FORMAT = "X+.YYYYMMDD.R+"

# Priority-ordered list of sync target file names and their types.
_VERSION_FILES: list[tuple[str, str]] = [
    ("pyproject.toml", "pyproject"),
    ("package.json", "package_json"),
]

# --- Format parsing ---

# Token pattern: longest match first.
_TOKEN_RE = re.compile(
    r"(0X{2,}|0R{2,}|X{2,}|R{2,}|X\+|R\+|X|R|YYYY|MM|DD|\.)"
)


def _classify_token(tok: str) -> tuple[str, int, bool]:
    """Classify a format token.

    Returns (kind, width, zero_pad).
    kind: 'manual', 'year', 'month', 'day', 'rev', 'dot'
    width: exact digit count, or 0 for variable-width (+ suffix)
    zero_pad: True if the output should be zero-padded to width
    """
    if tok == ".":
        return ("dot", 0, False)
    if tok == "YYYY":
        return ("year", 4, True)
    if tok == "MM":
        return ("month", 2, True)
    if tok == "DD":
        return ("day", 2, True)
    # X+ or R+ — variable width
    if tok == "X+":
        return ("manual", 0, False)
    if tok == "R+":
        return ("rev", 0, False)
    # 0XX, 0XXX — zero-padded manual
    if tok.startswith("0") and all(c == "X" for c in tok[1:]):
        return ("manual", len(tok) - 1, True)
    # XX, XXX — exact width manual
    if all(c == "X" for c in tok):
        return ("manual", len(tok), False)
    # 0RR, 0RRR — zero-padded rev
    if tok.startswith("0") and all(c == "R" for c in tok[1:]):
        return ("rev", len(tok) - 1, True)
    # RR, RRR — exact width rev
    if all(c == "R" for c in tok):
        return ("rev", len(tok), False)
    raise ValueError(f"Unknown version format token: {tok}")


def parse_format(fmt: str) -> list[tuple[str, int, bool]]:
    """Parse a version format string into classified tokens."""
    tokens = _TOKEN_RE.findall(fmt)
    # Verify we consumed the entire format string
    reconstructed = "".join(tokens)
    if reconstructed != fmt:
        raise ValueError(
            f"Invalid version format: {fmt!r} — unrecognized characters "
            f"(parsed as {reconstructed!r})"
        )
    return [_classify_token(t) for t in tokens]


def format_has_auto(parsed: list[tuple[str, int, bool]]) -> bool:
    """Check if the format has any auto-computed segments (date or rev)."""
    return any(k in ("year", "month", "day", "rev") for k, _, _ in parsed)


def _format_segment(value: int, width: int, zero_pad: bool) -> str:
    """Format a numeric segment with optional zero-padding.

    width=0 means variable width (no padding, no truncation).
    width>0 means exactly that many digits — zero-pad if zero_pad is True,
    otherwise just str(value) (may exceed width if the value is large).
    """
    if width == 0:
        return str(value)
    if zero_pad:
        return str(value).zfill(width)
    return str(value)


def build_version(
    parsed: list[tuple[str, int, bool]],
    manual_values: list[int],
    rev: int = 1,
    today: date | None = None,
) -> str:
    """Build a version string from parsed format, manual values, and auto values."""
    if today is None:
        today = date.today()

    parts = []
    manual_idx = 0
    for kind, width, zero_pad in parsed:
        if kind == "dot":
            parts.append(".")
        elif kind == "manual":
            val = manual_values[manual_idx] if manual_idx < len(manual_values) else 0
            manual_idx += 1
            parts.append(_format_segment(val, width, zero_pad))
        elif kind == "year":
            parts.append(str(today.year))
        elif kind == "month":
            parts.append(f"{today.month:02d}")
        elif kind == "day":
            parts.append(f"{today.day:02d}")
        elif kind == "rev":
            parts.append(_format_segment(rev, width, zero_pad))
    return "".join(parts)


def build_tag_regex(parsed: list[tuple[str, int, bool]]) -> re.Pattern:
    """Build a regex that matches version tags for this format.

    Returns a compiled pattern with named groups for manual segments
    (manual_0, manual_1, ...), date segments (year, month, day),
    and revision (rev).
    """
    parts = ["^v?"]
    manual_idx = 0
    for kind, width, zero_pad in parsed:
        if kind == "dot":
            parts.append(r"\.")
        elif kind == "manual":
            if width == 0:
                parts.append(f"(?P<manual_{manual_idx}>\\d+)")
            else:
                parts.append(f"(?P<manual_{manual_idx}>\\d{{{width}}})")
            manual_idx += 1
        elif kind == "year":
            parts.append(r"(?P<year>\d{4})")
        elif kind == "month":
            parts.append(r"(?P<month>\d{2})")
        elif kind == "day":
            parts.append(r"(?P<day>\d{2})")
        elif kind == "rev":
            if width == 0:
                parts.append(r"(?P<rev>\d+)")
            else:
                parts.append(f"(?P<rev>\\d{{{width}}})")
    parts.append("$")
    return re.compile("".join(parts))


# --- dotconfig.yaml source of truth ---

def load_dotconfig_yaml(config_dir: Path) -> dict | None:
    """Read and parse ``config/dotconfig.yaml``.

    Returns a dict on success, or ``None`` if the file is absent or
    cannot be parsed as a YAML mapping.
    """
    path = config_dir / "dotconfig.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def read_dotconfig_version(config_dir: Path) -> str | None:
    """Return the ``version`` field from ``config/dotconfig.yaml``.

    Returns ``None`` if the file is absent, malformed, or has no
    ``version`` key.
    """
    data = load_dotconfig_yaml(config_dir)
    if data is None:
        return None
    v = data.get("version")
    return str(v) if v is not None else None


def write_dotconfig_version(config_dir: Path, version: str) -> None:
    """Write ``version`` to ``config/dotconfig.yaml``.

    Creates the file with a minimal header comment if it does not exist.
    Updates the ``version:`` line in place if the file already exists,
    preserving all other content.  If the file has no ``version:`` line
    it is appended.
    """
    path = config_dir / "dotconfig.yaml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# dotconfig project metadata.\n"
            "# Edit `version` only via `dotconfig version bump`.\n"
            f"version: {version}\n",
            encoding="utf-8",
        )
        return

    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r"^version:.*$", re.MULTILINE)
    replacement = f"version: {version}"
    if pattern.search(content):
        updated = pattern.sub(replacement, content, count=1)
    else:
        # Append the version line if not present
        updated = content.rstrip("\n") + f"\n{replacement}\n"
    if updated != content:
        path.write_text(updated, encoding="utf-8")


def seed_version_from_sources(project_root: Path) -> str | None:
    """Return a version string from the first available external source file.

    Priority:
    1. ``<project_root>/package.json`` — the ``version`` field.
    2. ``<project_root>/pyproject.toml`` — ``version = "..."`` under ``[project]``.

    Returns the version string, or ``None`` if neither source yields a value.
    All errors (missing files, malformed content) are silently swallowed.
    """
    pkg_json = project_root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "version" in data:
                return str(data["version"])
        except Exception:
            pass

    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
            in_project = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("["):
                    in_project = stripped == "[project]"
                    continue
                if in_project:
                    m = re.match(r'^version\s*=\s*"([^"]+)"', stripped)
                    if m:
                        return m.group(1)
        except Exception:
            pass

    return None


def load_version_format(config_dir: Path | None = None) -> str:
    """Load the version format from ``config/dotconfig.yaml``.

    Falls back to ``DEFAULT_FORMAT`` if the file or key doesn't exist.
    """
    if config_dir is None:
        return DEFAULT_FORMAT
    data = load_dotconfig_yaml(config_dir)
    if data is None:
        return DEFAULT_FORMAT
    return data.get("version_format", DEFAULT_FORMAT)


def load_version_sync(config_dir: Path | None = None) -> list[str]:
    """Load the ``version_sync`` setting from ``config/dotconfig.yaml``.

    Returns a list of file paths (relative to project root) to sync the
    version into after a bump.
    """
    if config_dir is None:
        return []
    data = load_dotconfig_yaml(config_dir)
    if data is None:
        return []
    val = data.get("version_sync")
    if isinstance(val, list):
        return [str(v) for v in val]
    return []


# --- Legacy compat ---

VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d{8})\.(\d+)$")


# --- Core API ---

def _get_existing_tags() -> list[str]:
    """Return all git tags in the current repository."""
    result = subprocess.run(
        ["git", "tag", "-l"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def compute_next_version(major: int | None = None, config_dir: Path | None = None) -> str:
    """Compute the next version string based on existing git tags.

    Reads the version format from ``config/dotconfig.yaml``.  For formats
    with auto-computed segments (date, revision), scans git tags to find
    the next revision number.  For fully manual formats, returns the major
    values joined by dots.

    Also reads the current version from ``config/dotconfig.yaml`` so that
    successive bumps advance even when ``--tag`` is not used.
    """
    fmt = load_version_format(config_dir)
    parsed = parse_format(fmt)

    current = read_dotconfig_version(config_dir) if config_dir is not None else None
    tag_pattern = build_tag_regex(parsed)

    # If major is omitted, preserve the existing major from dotconfig.yaml
    # when it matches the active version format. Fall back to 0 otherwise.
    effective_major = major
    if effective_major is None and current:
        m = tag_pattern.match(current.lstrip("v"))
        if m and m.groupdict().get("manual_0") is not None:
            effective_major = int(m.group("manual_0"))
    if effective_major is None:
        effective_major = 0

    if not format_has_auto(parsed):
        # Fully manual format — return manual values as-is
        manual_count = sum(1 for k, _, _ in parsed if k == "manual")
        values = [effective_major] + [0] * (manual_count - 1)
        return build_version(parsed, values)

    today = date.today()
    today_str = today.strftime("%Y%m%d")
    def _extract_rev(candidate: str) -> int | None:
        m = tag_pattern.match(candidate.lstrip("v"))
        if not m:
            return None

        # Check manual segments match
        manual_idx = 0
        for kind, _, _ in parsed:
            if kind == "manual":
                tag_val = int(m.group(f"manual_{manual_idx}"))
                expected = effective_major if manual_idx == 0 else 0
                if tag_val != expected:
                    return None
                manual_idx += 1

        # Check date segments match today
        tag_date = ""
        if "year" in m.groupdict():
            tag_date += m.group("year")
        if "month" in m.groupdict():
            tag_date += m.group("month")
        if "day" in m.groupdict():
            tag_date += m.group("day")

        if tag_date and tag_date != today_str[: len(tag_date)]:
            return None

        if "rev" in m.groupdict():
            return int(m.group("rev"))
        return None

    max_rev = 0
    for tag in _get_existing_tags():
        rev = _extract_rev(tag)
        if rev is not None:
            max_rev = max(max_rev, rev)

    # Also consider the version currently in dotconfig.yaml so consecutive
    # bumps advance even when --tag is not used.
    if current:
        rev = _extract_rev(current)
        if rev is not None:
            max_rev = max(max_rev, rev)

    manual_count = sum(1 for k, _, _ in parsed if k == "manual")
    values = [effective_major] + [0] * (manual_count - 1)
    return build_version(parsed, values, rev=max_rev + 1, today=today)


def _file_type_for(path: Path) -> str:
    """Determine the version file type from a file path."""
    name = path.name
    if name == "pyproject.toml":
        return "pyproject"
    if name == "package.json":
        return "package_json"
    raise ValueError(f"Unknown version file type for {name}")


def update_pyproject_version(version: str, pyproject_path: Path) -> None:
    """Update the version field in pyproject.toml.

    Silently skips if the file does not exist.
    """
    if not pyproject_path.exists():
        return
    content = pyproject_path.read_text(encoding="utf-8")
    pattern = re.compile(r'^version\s*=\s*"[^"]*"', re.MULTILINE)
    if not pattern.search(content):
        raise ValueError(f"Could not find version field in {pyproject_path}")
    updated = pattern.sub(f'version = "{version}"', content, count=1)
    if updated != content:
        pyproject_path.write_text(updated, encoding="utf-8")


def update_package_json_version(version: str, package_path: Path) -> None:
    """Update the version field in package.json.

    Silently skips if the file does not exist.
    """
    if not package_path.exists():
        return
    content = package_path.read_text(encoding="utf-8")
    data = json.loads(content)
    if "version" not in data:
        raise ValueError(f"No 'version' field in {package_path}")
    data["version"] = version
    package_path.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def update_version_file(path: Path, file_type: str, version: str) -> None:
    """Update the version in the detected file, dispatching by type."""
    if file_type == "pyproject":
        update_pyproject_version(version, path)
    elif file_type == "package_json":
        update_package_json_version(version, path)
    else:
        raise ValueError(f"Unknown version file type: {file_type}")


def update_dotenv_version(version: str, env_path: Path) -> None:
    """Rewrite or insert ``_VERSION=<version>`` at the top of ``.env``.

    Preserves all other lines.  No-ops if ``env_path`` does not exist.
    """
    if not env_path.exists():
        return

    content = env_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    # Strip any existing _VERSION= lines
    filtered = [ln for ln in lines if not ln.startswith("_VERSION=")]
    # Prepend the new line
    new_content = f"_VERSION={version}\n" + "".join(filtered)
    env_path.write_text(new_content, encoding="utf-8")


def create_version_tag(version: str) -> None:
    """Create a git tag for the given version."""
    tag_name = f"v{version}"
    result = subprocess.run(
        ["git", "tag", tag_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create tag {tag_name}: {result.stderr.strip()}"
        )


def bump_version(
    major: int | None = None,
    tag: bool = False,
    project_root: Path | None = None,
    config_dir: Path | None = None,
    run_hooks: bool = True,
) -> dict:
    """Compute the next version, update all version files, and optionally tag.

    Source of truth is ``config/dotconfig.yaml``.  ``pyproject.toml``,
    ``package.json``, and ``.env`` are sync targets written best-effort
    (missing files are silently skipped).

    Returns a dict with keys: ``version``, ``source``, ``synced``, ``tag``.
    """
    if project_root is None:
        project_root = Path.cwd()
    if config_dir is None:
        config_dir = project_root / "config"

    # Ensure config_dir is absolute so relative_to() works correctly.
    if not config_dir.is_absolute():
        config_dir = project_root / config_dir

    old_version = read_dotconfig_version(config_dir) or ""
    version = compute_next_version(major=major, config_dir=config_dir)

    # Write source of truth
    write_dotconfig_version(config_dir, version)
    source_path = str((config_dir / "dotconfig.yaml").relative_to(project_root))

    # Sync to pyproject.toml and package.json
    synced: list[str] = []
    for filename, file_type in _VERSION_FILES:
        path = project_root / filename
        if path.exists():
            update_version_file(path, file_type, version)
            synced.append(filename)

    # Sync extra files from version_sync setting
    for rel_path in load_version_sync(config_dir):
        path = project_root / rel_path
        if not path.exists():
            continue
        try:
            file_type = _file_type_for(path)
            update_version_file(path, file_type, version)
            synced.append(rel_path)
        except ValueError:
            pass  # Unknown file type — skip

    # Sync .env if it exists
    env_path = project_root / ".env"
    if env_path.exists():
        update_dotenv_version(version, env_path)
        synced.append(".env")

    # Tag
    tag_name = None
    if tag:
        create_version_tag(version)
        tag_name = f"v{version}"

    # Event hook
    if run_hooks:
        from .event_hooks import run_hook
        run_hook(config_dir, "version_bump", [old_version, version])

    return {
        "version": version,
        "source": source_path,
        "synced": synced,
        "tag": tag_name,
    }
