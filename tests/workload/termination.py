"""Termination evidence classification for the workload diagnostic harness.

This module classifies **evidence**, not faults. The distinction is the whole
point of it and is enforced mechanically by ``is_crash``, which always returns
False.

Measured on Windows, a genuine access violation and a deliberate
``sys.exit(3221225477)`` produce byte-identical return codes with no stderr
either way. On POSIX, ``os.WIFSIGNALED(7)`` is True after an ordinary
``sys.exit(7)`` and ``os.WTERMSIG(-9)`` is 119 rather than 9, so neither helper
may be used. The only safe POSIX signal test is ``returncode < 0`` with the
signal taken as ``-returncode``.

The chain below is known to be invalid, and exists only as something to avoid::

    native_termination_suspected
        -> crash
        -> RenderDoc defect

Phase 1 measurement severed the first arrow. Nothing here may reintroduce it.
"""

import os

NORMAL_EXIT = "normal_exit"
PYTHON_FAILURE = "python_failure"
NONZERO_EXIT = "nonzero_exit"
SIGNAL_TERMINATION = "signal_termination"
NATIVE_TERMINATION_SUSPECTED = "native_termination_suspected"
TIMEOUT = "timeout"
INDETERMINATE = "indeterminate"

CLASSES = (NORMAL_EXIT, PYTHON_FAILURE, NONZERO_EXIT, SIGNAL_TERMINATION,
           NATIVE_TERMINATION_SUSPECTED, TIMEOUT, INDETERMINATE)

#: Measured marker. The previous check required an "error" substring anywhere
#: in lower-cased stderr, which is both case-mangled and far too weak.
TRACEBACK_MARKER = "Traceback (most recent call last)"

#: NTSTATUS with severity Error and customer bit 0. 0xC0000005 access violation,
#: 0xC0000409 abort, 0xC0000374 heap corruption, 0xC000001D illegal
#: instruction. Warning severities (0x8xxxxxxx) are deliberately excluded.
NTSTATUS_SEVERITY_MASK = 0xFFFF0000
NTSTATUS_ERROR_SEVERITY = 0xC0000000


def _is_native_status(status):
    return (status & NTSTATUS_SEVERITY_MASK) == NTSTATUS_ERROR_SEVERITY


def observe(returncode, stdout="", stderr="", sentinel=None, platform=None):
    """Describe how a child process ended, without claiming why.

    The raw return code is preserved verbatim; ``ntstatus`` and
    ``signal_number`` are derived views of it, never replacements.
    """
    platform = os.name if platform is None else platform
    present = returncode is not None
    traceback = TRACEBACK_MARKER in (stderr or "")
    sentinel_seen = bool(sentinel) and sentinel in (stdout or "")

    ntstatus = None
    signal_number = None

    if not present:
        # subprocess.TimeoutExpired has no .returncode attribute at all.
        klass = TIMEOUT
    elif platform == "nt":
        ntstatus = returncode & 0xFFFFFFFF
        if returncode == 0:
            klass = NORMAL_EXIT
        elif _is_native_status(ntstatus):
            klass = NATIVE_TERMINATION_SUSPECTED
        elif traceback:
            klass = PYTHON_FAILURE
        else:
            klass = NONZERO_EXIT
    elif platform == "posix":
        if returncode == 0:
            klass = NORMAL_EXIT
        elif returncode < 0:
            klass = SIGNAL_TERMINATION
            signal_number = -returncode
        elif traceback:
            klass = PYTHON_FAILURE
        else:
            klass = NONZERO_EXIT
    else:
        # An unrecognised platform is not a normal exit.
        klass = INDETERMINATE

    return {
        "execution_result": {
            "process_returncode": returncode,
            "returncode_present": present,
        },
        "termination_observation": {"class": klass},
        "evidence": {
            "platform": platform,
            "completion_sentinel_present": sentinel_seen,
            "traceback_present": traceback,
            "signal_number": signal_number,
            "ntstatus": ntstatus,
        },
        "note": "termination observation is evidence classification, not "
                "fault attribution",
    }


def observe_from_timeout(exc):
    """Build an observation from a ``subprocess.TimeoutExpired``.

    Recorded rather than re-raised. A hang used to kill the child and leave
    ``REPORT["reliability"]`` with no entry, so the one failure mode that
    certainly happened was the one the report could not see.
    """
    stderr = getattr(exc, "stderr", None) or ""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return observe(None, stderr=stderr)


def is_crash(observation):
    """Always False, on purpose.

    Provided so that a caller reaching for a crash predicate gets a refusal and
    an explanation instead of writing its own. No available signal establishes
    that a process crashed: on Windows the return code is shared with a
    deliberate exit, and on POSIX a signal death is equally consistent with an
    external kill. ``native_termination_suspected`` is as far as the evidence
    goes, and it is deliberately not this function.
    """
    return False


def summarise(observation):
    """One line a report can print without overstating."""
    result = observation["execution_result"]
    evidence = observation["evidence"]
    bits = [observation["termination_observation"]["class"]]
    if result["returncode_present"]:
        bits.append(f"returncode={result['process_returncode']}")
    else:
        bits.append("returncode=<absent>")
    if evidence["signal_number"] is not None:
        bits.append(f"signal={evidence['signal_number']}")
    if evidence["ntstatus"] is not None:
        bits.append(f"ntstatus=0x{evidence['ntstatus']:08X}")
    if evidence["traceback_present"]:
        bits.append("traceback")
    if evidence["completion_sentinel_present"]:
        bits.append("sentinel")
    return " ".join(bits)
