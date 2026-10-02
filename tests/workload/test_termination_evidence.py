"""Real-process controls for the termination evidence layer.

The truth table in `tests/unit/test_termination_classification.py` is pure and
proves nothing about what a real process actually returns. That gap is why
`code < 0` survived: on Windows it never fires, and no control was spawning a
process that actually crashes.

So every case here spawns a real child. A compiled NULL dereference produces a
genuine access violation on this platform; nothing is simulated. That case
skips, with a stated reason, where no C toolchain exists rather than faking a
return code.

Not part of any gate. It is a diagnostic-suite control, and the unit gate
asserts that it continues to exist and to cover these cases.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.workload import termination as T  # noqa: E402 - needs path above

GCC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

NTSTATUS_AV = 0xC0000005
SENTINEL = "SCENARIO_OK"


#: Temp directories made by _script, removed in tearDownModule. Before this
#: existed every one of the seven controls leaked a directory per run, and
#: nothing reported it: an accumulating pile of empty directories is invisible
#: to a test run that only checks assertions.
_TEMP_DIRS = []


def tearDownModule():
    for directory in _TEMP_DIRS:
        shutil.rmtree(directory, ignore_errors=True)
    del _TEMP_DIRS[:]


def _script(body):
    d = tempfile.mkdtemp(prefix="term_evidence_")
    _TEMP_DIRS.append(d)
    p = os.path.join(d, "child.py")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    return p


def _run(cmd, **kwargs):
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          errors="replace", **kwargs)
    return T.observe(returncode=proc.returncode, stdout=proc.stdout or "",
                     stderr=proc.stderr or "", sentinel=SENTINEL)


def _native_av_exe():
    """Compile a real NULL dereference. Returns a path or None."""
    if not GCC:
        return None
    d = tempfile.mkdtemp(prefix="term_native_")
    src = os.path.join(d, "av.c")
    exe = os.path.join(d, "av.exe" if os.name == "nt" else "av")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("int main(void){volatile int*p=(int*)0;return *p;}\n")
    try:
        built = subprocess.run([GCC, "-O0", "-o", exe, src],
                               capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return exe if built.returncode == 0 and os.path.isfile(exe) else None


class RealProcessControls(unittest.TestCase):

    def test_real_clean_exit(self):
        obs = _run([sys.executable, _script("import sys; sys.exit(0)")])
        self.assertEqual(obs["execution_result"]["process_returncode"], 0)
        self.assertEqual(obs["termination_observation"]["class"],
                         T.NORMAL_EXIT)

    def test_real_explicit_nonzero_exit_is_not_a_signal(self):
        for code in (1, 2, 5, 7):
            obs = _run([sys.executable,
                        _script(f"import sys; sys.exit({code})")])
            self.assertEqual(obs["execution_result"]["process_returncode"], code)
            self.assertEqual(obs["termination_observation"]["class"],
                             T.NONZERO_EXIT,
                             f"exit({code}) must not be read as a signal")
            self.assertIsNone(obs["evidence"]["signal_number"])

    def test_real_python_traceback(self):
        body = ("def f():\n    raise ValueError('boom')\n"
                "import sys\nprint('SCENARIO_OK', flush=True)\n"
                "sys.stderr.flush()\nf()\n")
        obs = _run([sys.executable, _script(body)])
        self.assertIs(obs["evidence"]["traceback_present"], True)
        self.assertEqual(obs["termination_observation"]["class"],
                         T.PYTHON_FAILURE)

    @unittest.skipUnless(GCC, "no C toolchain available to build a real crash")
    def test_real_native_access_violation(self):
        exe = _native_av_exe()
        if exe is None:
            self.skipTest("the C toolchain is present but the build failed")
        obs = _run([exe])
        rc = obs["execution_result"]["process_returncode"]
        if os.name == "nt":
            self.assertEqual(rc, NTSTATUS_AV,
                             "a real AV must measure as 0xC0000005")
            self.assertEqual(obs["termination_observation"]["class"],
                             T.NATIVE_TERMINATION_SUSPECTED)
            self.assertEqual(obs["evidence"]["ntstatus"], NTSTATUS_AV)
            self.assertIs(obs["evidence"]["traceback_present"], False)
            self.assertFalse(
                T.is_crash(obs),
                "even a real access violation must not be reported as a "
                "proven crash; the return code cannot establish it")
        else:
            self.assertLess(rc, 0, "POSIX reports a signal as a negative code")
            self.assertEqual(obs["termination_observation"]["class"],
                             T.SIGNAL_TERMINATION)
            self.assertEqual(obs["evidence"]["signal_number"], -rc)

    def test_deliberate_ntstatus_exit_is_not_called_a_crash(self):
        """Same bytes as a real AV on Windows, and it must not be called one.

        This is the control that keeps the evidence honest. If the classifier
        ever reports "crashed" here it is overstating, because this child
        exited perfectly deliberately.
        """
        obs = _run([sys.executable,
                    _script(f"import sys; sys.exit({NTSTATUS_AV})")])
        self.assertEqual(obs["termination_observation"]["class"],
                         T.NATIVE_TERMINATION_SUSPECTED)
        self.assertNotIn("crashed", repr(obs).lower())
        self.assertFalse(T.is_crash(obs),
                         "a deliberate exit with an AV status is not a crash")

    @unittest.skipUnless(os.name == "nt", "taskkill is Windows-only")
    def test_real_external_kill_is_not_reported_as_a_crash(self):
        # Measured: taskkill /F terminates with plain exit code 1, so an
        # external kill is nearly invisible on Windows. It must still not be
        # promoted into a crash.
        script = _script("import time\nprint('ready', flush=True)\n"
                         "time.sleep(300)\n")
        # `with` closes the pipe. Without it the TextIOWrapper over stdout is
        # left to the garbage collector, which surfaced as a ResourceWarning
        # naming encoding='cp936' -- text=True with no explicit encoding had
        # picked up the machine's locale codepage, making a control that is
        # supposed to be deterministic depend on where it runs.
        with subprocess.Popen([sys.executable, script],
                              stdout=subprocess.PIPE,
                              encoding="utf-8") as proc:
            try:
                proc.stdout.readline()
                subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)],
                               capture_output=True)
                proc.wait(timeout=60)
            finally:
                if proc.poll() is None:
                    proc.kill()
            returncode = proc.returncode
        self.assertNotEqual(returncode, 0)
        self.assertNotEqual(returncode, NTSTATUS_AV)
        # Assert on the classification this process would actually produce,
        # not only on its return code. A return-code comparison alone would let
        # this control pass while the classifier promoted the kill.
        obs = T.observe(returncode=returncode, stdout="", stderr="",
                        sentinel=SENTINEL)
        self.assertNotEqual(obs["termination_observation"]["class"],
                            T.NATIVE_TERMINATION_SUSPECTED)
        self.assertNotEqual(obs["termination_observation"]["class"],
                            T.SIGNAL_TERMINATION)
        self.assertFalse(T.is_crash(obs))

    def test_real_timeout_is_recorded(self):
        """A hang must produce an observation, not an exception.

        Measured: TimeoutExpired has no .returncode, and run_isolated did not
        catch it, so a hung scenario killed the child and recorded nothing.
        """
        script = _script("import time\nprint('ready', flush=True)\n"
                         "time.sleep(300)\n")
        try:
            subprocess.run([sys.executable, script], capture_output=True,
                           text=True, timeout=3)
            self.fail("the child was expected to still be running")
        except subprocess.TimeoutExpired as exc:
            obs = T.observe_from_timeout(exc)
        self.assertEqual(obs["termination_observation"]["class"], T.TIMEOUT)
        self.assertIs(obs["execution_result"]["returncode_present"], False)
        self.assertIsNone(obs["execution_result"]["process_returncode"])
        self.assertFalse(T.is_crash(obs))


if __name__ == "__main__":
    unittest.main()
