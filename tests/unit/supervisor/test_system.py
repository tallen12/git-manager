import os
import pwd
import stat
from pathlib import Path

import pytest

from git_manager.supervisor.models import OwnershipModes
from git_manager.supervisor.system import OsOwnership, PasswdAccounts

# Without root, a tree can only be "handed" to the current user; these tests check the
# walk (modes, links, error recovery). Real user switches are covered by the image.
ME = os.geteuid()
MY_GROUP = os.getegid()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_accounts_come_from_the_user_database() -> None:
    name = pwd.getpwuid(ME).pw_name

    account = PasswdAccounts().user(name)

    assert account is not None
    assert account.uid == ME
    assert account.gid in account.groups


def test_unknown_users_and_groups_are_none() -> None:
    accounts = PasswdAccounts()

    assert accounts.user("gm-no-such-user") is None
    assert accounts.group_id("gm-no-such-group") is None


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "sub" / "b.txt").write_text("b", encoding="utf-8")
    root.chmod(0o755)
    (root / "sub").chmod(0o777)
    return root


def test_handing_over_keeps_modes_unless_told(tree: Path) -> None:
    skipped = OsOwnership().hand_over(tree, uid=ME, gid=MY_GROUP)

    assert skipped == ()
    assert _mode(tree) == 0o755
    assert _mode(tree / "sub") == 0o777
    assert (tree / "sub" / "b.txt").read_text(encoding="utf-8") == "b"


def test_handing_over_can_lock_down_modes(tree: Path) -> None:
    OsOwnership().hand_over(
        tree, uid=ME, gid=MY_GROUP, modes=OwnershipModes(directory=0o500, file=0o400)
    )

    assert _mode(tree) == 0o500
    assert _mode(tree / "sub") == 0o500
    assert _mode(tree / "a.txt") == 0o400
    tree.chmod(0o700)
    (tree / "sub").chmod(0o700)


def test_links_are_never_followed(tree: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("x", encoding="utf-8")
    outside.chmod(0o644)
    (tree / "link").symlink_to(outside)

    OsOwnership().hand_over(tree, uid=ME, gid=MY_GROUP, modes=OwnershipModes(file=0o400))

    assert _mode(outside) == 0o644
    assert (tree / "link").is_symlink()


def test_hard_linked_files_are_left_alone_and_reported(tree: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("x", encoding="utf-8")
    outside.chmod(0o644)
    (tree / "sub" / "linked").hardlink_to(outside)

    skipped = OsOwnership().hand_over(tree, uid=ME, gid=MY_GROUP, modes=OwnershipModes(file=0o400))

    assert skipped == (Path("sub/linked"),)
    assert _mode(outside) == 0o644
    assert _mode(tree / "a.txt") == 0o400


def test_a_failure_gives_locked_directories_back(tree: Path) -> None:
    if ME == 0:
        pytest.skip("root may chown to any group")

    with pytest.raises(PermissionError):
        # A group the user is not in: the first chown inside the tree fails.
        OsOwnership().hand_over(tree, uid=ME, gid=max(os.getgroups()) + 12345)

    assert _mode(tree) == 0o755
    assert _mode(tree / "sub") == 0o777


def test_a_single_file_is_handed_over(tmp_path: Path) -> None:
    file = tmp_path / "key.pem"
    file.write_text("k", encoding="utf-8")

    OsOwnership().hand_over(file, uid=ME, gid=MY_GROUP, modes=OwnershipModes(file=0o400))

    assert _mode(file) == 0o400


def test_ensure_directory_creates_and_sets_the_mode(tmp_path: Path) -> None:
    directory = tmp_path / "run" / "git-manager"

    OsOwnership().ensure_directory(directory, uid=ME, gid=MY_GROUP, mode=0o750)

    assert directory.is_dir()
    assert _mode(directory) == 0o750


def test_set_owner_refuses_a_link(tmp_path: Path) -> None:
    (tmp_path / "link").symlink_to(tmp_path)

    with pytest.raises(OSError, match="symbolic link"):
        OsOwnership().set_owner(tmp_path / "link", uid=ME, gid=MY_GROUP, mode=0o600)
