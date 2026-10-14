#!/usr/bin/env python3
"""`uvicorn`, with `--reload`'s restart made to work on Windows (#2471).

`scripts/dev_backend.py` runs this instead of `python -m uvicorn`; the
arguments are uvicorn's own.

On Windows, uvicorn 0.52's reloader stops its server child with a console
Ctrl+C (`supervisors/basereload.py::restart`):

    os.kill(self.process.pid, signal.CTRL_C_EVENT)
    ...
    self.process.join()

That event never arrives. `os.kill(pid, CTRL_C_EVENT)` is
`GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)`, which addresses a process
*group*. The server is a `multiprocessing` child, not a group leader, so
nothing receives it. Separately, a tree started from a host that runs its
shells in their own process group (a background task runner) inherits "ignore
Ctrl+C". Measured with a standalone probe: only a whole-console broadcast to a
child that had cleared that flag ever got through. So `join()` blocked forever,
the reloader stopped watching, and the OLD server went on serving stale code.
The log said nothing beyond `Reloading...`.

The fix is the restart uvicorn already uses on POSIX: terminate the child, then
start a new one. On Windows `terminate()` is TerminateProcess, so the old server
skips its lifespan shutdown. That shutdown only flushes the node-index cache,
which is rebuildable by design (`app/main.py`). `dev_backend.py`'s own stop has
always been a hard kill (`taskkill /F /T`).
"""

from __future__ import annotations

import sys

from uvicorn._subprocess import get_subprocess
from uvicorn.supervisors.basereload import BaseReload


def restart_by_terminate(self: BaseReload) -> None:
    """`BaseReload.restart`'s POSIX branch, for every platform."""
    self.process.terminate()
    self.process.join()
    self.process = get_subprocess(config=self.config, target=self.target, sockets=self.sockets)
    self.process.start()


# At import: the reloader is this process. (The server child, a `multiprocessing`
# spawn, re-imports this module as `__mp_main__` and patches too — unused there.)
if sys.platform == "win32":
    BaseReload.restart = restart_by_terminate  # type: ignore[method-assign]


if __name__ == "__main__":
    import uvicorn

    sys.exit(uvicorn.main())
