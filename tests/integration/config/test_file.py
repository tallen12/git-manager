import difflib
import stat
from pathlib import Path

import pytest

from git_manager.config import CheckoutRepoConfig, ConfigError, YamlConfigFile
from git_manager.config.file import write_atomically

# The style of the spec's example: comments everywhere, flow mappings, indented lists.
COMMENTED = """\
# /etc/git-manager/config.yaml  (one repo per container)
repo:
  url: git@github.com:prxengage/trialport-api.git
  credential: /run/secrets/deploy_key
  signing_key: null        # optional key to re-sign rebased commits

budget:                    # rolling Claude spend
  daily_usd: 10
  weekly_usd: 40

defaults:
  poll_interval: 60s       # how often to ls-remote
  cadence:
    mode: debounce         # immediate | debounce | cron | manual
    debounce: 10m          # wait for base to be quiet this long
  commits:
    committer: {name: Git Manager, email: git-manager@users.noreply.github.com}
  notify:
    on: [awaiting_approval, needs_human, pushed]

branches:
  # the main feature branch
  - name: feature/site-portal-v2
    base: main
    verify:
      test: "just test"    # quoted on purpose
"""


def open_file(path: Path) -> YamlConfigFile:
    return YamlConfigFile(path, environ={}, repo_config=CheckoutRepoConfig())


def changed_lines(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line for line in diff if line[:1] in "+-" and line[:3] not in {"---", "+++"}]


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(COMMENTED, encoding="utf-8")
    return path


def test_set_changes_only_the_edited_line_and_keeps_every_comment(config_path: Path) -> None:
    config = open_file(config_path).set(["defaults", "cadence", "debounce"], "15m")

    after = config_path.read_text(encoding="utf-8")
    assert changed_lines(COMMENTED, after) == [
        "-    debounce: 10m          # wait for base to be quiet this long",
        "+    debounce: 15m          # wait for base to be quiet this long",
    ]
    assert config.branches[0].cadence.debounce.total_seconds() == 900


def test_set_inside_a_branch_keeps_quotes_and_list_indentation(config_path: Path) -> None:
    open_file(config_path).set(["branches", 0, "base"], "develop")

    after = config_path.read_text(encoding="utf-8")
    assert changed_lines(COMMENTED, after) == ["-    base: main", "+    base: develop"]


def test_set_appends_a_new_section_in_the_file_style(config_path: Path) -> None:
    open_file(config_path).set(["branches", 0, "claude", "max_turns"], 12)

    after = config_path.read_text(encoding="utf-8")
    assert changed_lines(COMMENTED, after) == ["+    claude:", "+      max_turns: 12"]


def test_set_keeps_a_four_space_style_with_flush_lists(tmp_path: Path) -> None:
    before = "repo:\n    url: u\nbranches:\n- name: a\n  base: main\n"
    path = tmp_path / "config.yaml"
    path.write_text(before, encoding="utf-8")

    open_file(path).set(["budget", "daily_usd"], 5)

    assert path.read_text(encoding="utf-8") == before + "budget:\n    daily_usd: 5\n"


def test_an_invalid_edit_leaves_the_file_byte_for_byte(config_path: Path) -> None:
    with pytest.raises(ConfigError):
        open_file(config_path).set(["defaults", "cadence", "mode"], "sometimes")

    assert config_path.read_text(encoding="utf-8") == COMMENTED
    assert sorted(path.name for path in config_path.parent.iterdir()) == ["config.yaml"]


def test_set_keeps_permissions_and_leaves_no_temporary_file(config_path: Path) -> None:
    config_path.chmod(0o640)

    open_file(config_path).set(["budget", "daily_usd"], 12)

    assert stat.S_IMODE(config_path.stat().st_mode) == 0o640
    assert sorted(path.name for path in config_path.parent.iterdir()) == ["config.yaml"]


def test_set_through_a_symlink_writes_the_target_and_keeps_the_link(
    config_path: Path, tmp_path: Path
) -> None:
    link = tmp_path / "mounted" / "config.yaml"
    link.parent.mkdir()
    link.symlink_to(config_path)

    open_file(link).set(["budget", "daily_usd"], 12)

    assert link.is_symlink()
    assert "daily_usd: 12" in config_path.read_text(encoding="utf-8")


def test_a_failed_replace_keeps_the_original_and_removes_the_temporary_file(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_self: Path, _target: Path) -> Path:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(Path, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        write_atomically(config_path, "repo: {url: other}\n")

    assert config_path.read_text(encoding="utf-8") == COMMENTED
    assert sorted(path.name for path in config_path.parent.iterdir()) == ["config.yaml"]


def test_load_reads_a_trusted_repo_file_from_the_clone(tmp_path: Path) -> None:
    clone = tmp_path / "data" / "repo"
    clone.mkdir(parents=True)
    (clone / ".git-manager.yaml").write_text("defaults:\n  max_restarts: 6\n", encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        f"repo:\n  url: u\n  trust_repo_config: true\n  data_dir: {tmp_path / 'data'}\n",
        encoding="utf-8",
    )

    assert open_file(path).load().defaults.max_restarts == 6
