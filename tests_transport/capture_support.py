"""A capture path the capture policy will actually accept.

Every tool call resolves its capture before it reaches the transport, and the
policy checks two things: the path must sit under an allowed root, and the file
must exist. These tests fake the session but not that step, and they used a
fictional ``cap.rdc``, so the policy refused the call and returned an error
payload. The assertions underneath then failed with ``KeyError: 'summary'`` and
``KeyError: 'comparison'`` on keys that were never missing -- the payload was an
error, and the error was three layers up. This file is why the suite said the
wrong thing about itself.

The corpus cannot be borrowed to fix it: ``tests/workload/corpus/`` is
gitignored, so a fresh clone and the CI runner have no capture there at all,
which is also why the default allowed root points at a directory that does not
exist for anyone but the author. So the file is created in a temporary directory
and the policy is widened to that directory. Hermetic on a machine with no corpus
and on a runner, which is the whole point of a gate.

``FakeSession`` does not read it. The path only has to survive the policy.

The widening is scoped to the module that asks for it rather than done at import
time. ``pyproject.toml`` puts ``tests`` and ``tests_transport`` in one
``testpaths``, so an import-time mutation would narrow the policy for the unit
tests -- which use real corpus captures -- before they ever ran.
"""
import atexit
import os
import shutil
import tempfile
from contextlib import contextmanager

from rdebug import capture_policy

_TMP = tempfile.mkdtemp(prefix="rdebug-transport-")
atexit.register(shutil.rmtree, _TMP, True)

# A real file: the policy resolves the path and stats it. Its contents are never
# read, because every session in this suite is a fake.
CAPTURE = os.path.join(_TMP, "cap.rdc")
with open(CAPTURE, "wb") as _fh:
    _fh.write(b"")


@contextmanager
def widened():
    """Point the capture policy at this file, then put the old value back.

    The policy reads the environment on every call, so restoring it in a finally
    is enough to leave no trace for the next suite.
    """
    previous = os.environ.get(capture_policy.ENV_ROOTS)
    os.environ[capture_policy.ENV_ROOTS] = _TMP
    try:
        yield CAPTURE
    finally:
        if previous is None:
            os.environ.pop(capture_policy.ENV_ROOTS, None)
        else:
            os.environ[capture_policy.ENV_ROOTS] = previous
