"""POSIX adapters: user lookup and ownership changes that resist a hostile tree.

The supervisor holds ``CAP_CHOWN`` but not ``CAP_DAC_READ_SEARCH`` or ``CAP_FOWNER``, so it
cannot look inside, or change the mode of, a directory someone else owns. It first takes
each node for itself (allowed by ``CAP_CHOWN``), locks directories to ``0700`` so their
previous owner can no longer swap entries, and only then descends and hands everything to
the new owner. Every step works on file descriptors or names relative to a locked
directory and never follows a symbolic link.
"""

import grp
import os
import pwd
import stat
from pathlib import Path

from git_manager.supervisor.models import Account, OwnershipModes

_LOCKED = 0o700
_KEEP = -1


class PasswdAccounts:
    """``Accounts`` from the system user and group databases."""

    def user(self, name: str) -> Account | None:
        """See ``Accounts.user``."""
        try:
            entry = pwd.getpwnam(name)
        except KeyError:
            return None
        return Account(
            name=entry.pw_name,
            uid=entry.pw_uid,
            gid=entry.pw_gid,
            groups=tuple(os.getgrouplist(entry.pw_name, entry.pw_gid)),
            home=Path(entry.pw_dir),
        )

    def group_id(self, name: str) -> int | None:
        """See ``Accounts.group_id``."""
        try:
            return grp.getgrnam(name).gr_gid
        except KeyError:
            return None


def _open_directory(name: str | Path, *, dir_fd: int | None = None) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)


class OsOwnership:
    """``Ownership`` through ``os`` calls; needs ``CAP_CHOWN`` to give files away."""

    def hand_over(
        self, path: Path, *, uid: int, gid: int, modes: OwnershipModes | None = None
    ) -> tuple[Path, ...]:
        """See ``Ownership.hand_over``."""
        modes = modes or OwnershipModes()
        skipped: list[Path] = []
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            self._hand_over_entry(
                path,
                info,
                Path(path.name),
                uid=uid,
                gid=gid,
                modes=modes,
                dir_fd=None,
                skipped=skipped,
            )
            return tuple(skipped)
        # The parent is the daemon's, so taking the top by name cannot be redirected.
        os.chown(path, os.geteuid(), _KEEP, follow_symlinks=False)
        fd = _open_directory(path)
        try:
            self._hand_over_directory(
                fd, info, Path(), uid=uid, gid=gid, modes=modes, skipped=skipped
            )
        finally:
            os.close(fd)
        return tuple(skipped)

    def _hand_over_directory(
        self,
        fd: int,
        original: os.stat_result,
        relative: Path,
        *,
        uid: int,
        gid: int,
        modes: OwnershipModes,
        skipped: list[Path],
    ) -> None:
        # Expects ``fd`` to be ours already; locking it freezes its entries.
        os.fchmod(fd, _LOCKED)
        try:
            for name in os.listdir(fd):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode):
                    self._hand_over_entry(
                        name,
                        info,
                        relative / name,
                        uid=uid,
                        gid=gid,
                        modes=modes,
                        dir_fd=fd,
                        skipped=skipped,
                    )
                    continue
                os.chown(name, os.geteuid(), _KEEP, dir_fd=fd, follow_symlinks=False)
                child = _open_directory(name, dir_fd=fd)
                try:
                    self._hand_over_directory(
                        child, info, relative / name, uid=uid, gid=gid, modes=modes, skipped=skipped
                    )
                finally:
                    os.close(child)
        except BaseException:
            # Never leave a root-owned, locked directory behind: give it back as it was.
            os.fchmod(fd, stat.S_IMODE(original.st_mode))
            os.fchown(fd, original.st_uid, original.st_gid)
            raise
        mode = modes.directory if modes.directory is not None else stat.S_IMODE(original.st_mode)
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)

    def _hand_over_entry(
        self,
        name: str | Path,
        info: os.stat_result,
        relative: Path,
        *,
        uid: int,
        gid: int,
        modes: OwnershipModes,
        dir_fd: int | None,
        skipped: list[Path],
    ) -> None:
        if not stat.S_ISLNK(info.st_mode) and info.st_nlink > 1:
            # Another link may sit outside the tree; leave the file with its owner.
            skipped.append(relative)
            return
        if modes.file is not None and stat.S_ISREG(info.st_mode):
            # Only an owner may change a mode without CAP_FOWNER; the entry is checked to
            # be a regular file in a locked directory, so following it is safe.
            os.chown(name, os.geteuid(), _KEEP, dir_fd=dir_fd, follow_symlinks=False)
            os.chmod(name, modes.file, dir_fd=dir_fd)
        os.chown(name, uid, gid, dir_fd=dir_fd, follow_symlinks=False)

    def set_owner(self, path: Path, *, uid: int, gid: int, mode: int) -> None:
        """See ``Ownership.set_owner``."""
        if path.is_symlink():
            msg = f"{path} is a symbolic link"
            raise OSError(msg)
        os.chown(path, os.geteuid(), _KEEP, follow_symlinks=False)
        path.chmod(mode)
        os.chown(path, uid, gid, follow_symlinks=False)

    def ensure_directory(self, path: Path, *, uid: int, gid: int, mode: int) -> None:
        """See ``Ownership.ensure_directory``."""
        path.mkdir(parents=True, exist_ok=True)
        self.set_owner(path, uid=uid, gid=gid, mode=mode)
