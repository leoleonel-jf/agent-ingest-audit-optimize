"""One writer at a time per ledger, across processes.

`update ledger`, `update all`, and `chain --seal` each read the ledger,
compute a new document from what they read, and replace the file. The
replace is atomic (`chain._write_atomically`), so no reader sees half a file,
but two writers whose read-and-replace windows overlap would each replace the
file with a document built from the same old read, and the first writer's
change would vanish with both commands reporting success.

`ledger_lock` closes that window for the writers that take it: it holds an
operating-system lock on a sidecar file, `<ledger>.lock`, from before the read
until after the replace. The sidecar, not the ledger itself, carries the
lock because Windows refuses `os.replace` onto a file another handle holds
locked, and because the ledger is replaced while the lock is held. The
operating system drops the lock when the holding process exits, cleanly or
not, so a crashed writer never leaves the ledger locked. The sidecar file is
left in place afterwards: deleting it would let a third writer lock a fresh
inode while a second still waits on the old one.

The guarantee covers only writers that take this lock. A record written by
hand, or by an agent editing the JSON directly, does not take it, and can
still be lost to, or lose, a concurrent `update` or `chain --seal`.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ledgerlib.errors import LedgerError

if os.name == "nt":  # pragma: no cover -- exercised on the Windows CI legs
    import msvcrt

    def _try_lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:  # pragma: no cover -- exercised on the Ubuntu CI legs
    import fcntl

    # `flock`, not `lockf`: POSIX record locks do not exclude a second
    # descriptor in the same process, and `flock` locks do.
    def _try_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


LOCK_TIMEOUT_SECONDS = 30.0
_POLL_SECONDS = 0.05


def lock_path(ledger: Path) -> Path:
    """The sidecar file that carries `ledger`'s lock."""
    return ledger.with_name(ledger.name + ".lock")


@contextmanager
def ledger_lock(ledger: Path, *, timeout: float | None = None) -> Iterator[None]:
    """Hold `ledger`'s writer lock for the duration of the block.

    Waits up to `timeout` seconds (default `LOCK_TIMEOUT_SECONDS`) for another
    writer to finish, then raises `LedgerError` naming the sidecar. Nothing is
    read or written before the lock is held, so a writer that gives up leaves
    the ledger exactly as it found it and can simply be run again.
    """
    limit = LOCK_TIMEOUT_SECONDS if timeout is None else timeout
    path = lock_path(ledger)
    try:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        raise LedgerError(f"cannot open the ledger lock {path}: {exc}") from exc
    try:
        deadline = time.monotonic() + limit
        while True:
            try:
                _try_lock(fd)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LedgerError(
                        f"{ledger}: another writer holds the ledger lock "
                        f"({path}); nothing was written. Run the command again "
                        "once it finishes."
                    ) from None
                time.sleep(_POLL_SECONDS)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
