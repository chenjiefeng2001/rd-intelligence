import os
import tempfile
import unittest

from rdebug.capture_policy import (
    ENV_ROOTS,
    MAX_DRAWS,
    MAX_WRITERS,
    CapturePathError,
    allowed_roots,
    clamp_limits,
    default_root,
    redact,
    resolve_capture,
)


class TestCaptureRootPolicy(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.pop(ENV_ROOTS, None)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._prev is None:
            os.environ.pop(ENV_ROOTS, None)
        else:
            os.environ[ENV_ROOTS] = self._prev

    def test_default_root_is_the_declared_corpus(self):
        self.assertEqual(allowed_roots(), [default_root()])

    def test_env_replaces_the_default_rather_than_adding_to_it(self):
        # Adding would leave the corpus open whenever an operator pointed
        # somewhere else, which is not what "widen" is asked to mean here.
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[ENV_ROOTS] = tmp
            self.assertEqual(allowed_roots(), [os.path.abspath(tmp)])
            with self.assertRaises(CapturePathError):
                resolve_capture(os.path.join(default_root(),
                                             "w00001_frame11.rdc"))

    def test_empty_env_falls_back_to_the_default(self):
        os.environ[ENV_ROOTS] = "   "
        self.assertEqual(allowed_roots(), [default_root()])

    def test_several_roots_may_be_listed(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            os.environ[ENV_ROOTS] = os.pathsep.join([a, b])
            self.assertEqual(sorted(allowed_roots()),
                             sorted([os.path.abspath(a), os.path.abspath(b)]))


class TestResolveCapture(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.pop(ENV_ROOTS, None)
        self.addCleanup(self._restore)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ[ENV_ROOTS] = self.tmp.name
        self.good = os.path.join(self.tmp.name, "cap.rdc")
        with open(self.good, "wb"):
            pass

    def _restore(self):
        if self._prev is None:
            os.environ.pop(ENV_ROOTS, None)
        else:
            os.environ[ENV_ROOTS] = self._prev

    def test_allows_a_file_under_an_allowed_root(self):
        self.assertEqual(resolve_capture(self.good), os.path.abspath(self.good))

    def test_rejects_an_arbitrary_system_path(self):
        with self.assertRaises(CapturePathError):
            resolve_capture(os.path.abspath(os.sep))

    def test_rejects_dot_dot_traversal_out_of_the_root(self):
        outside = os.path.join(self.tmp.name, "..", "escape.rdc")
        with self.assertRaises(CapturePathError):
            resolve_capture(outside)

    def test_rejects_a_sibling_whose_name_shares_the_root_prefix(self):
        # `root-evil` must not pass a naive `startswith(root)` test.
        sibling = self.tmp.name + "-evil"
        os.mkdir(sibling)
        evil = os.path.join(sibling, "cap.rdc")
        with open(evil, "wb"):
            pass

        def _drop():
            if os.path.exists(evil):
                os.remove(evil)
            if os.path.isdir(sibling):
                os.rmdir(sibling)

        self.addCleanup(_drop)
        with self.assertRaises(CapturePathError):
            resolve_capture(evil)

    def test_rejects_a_directory(self):
        with self.assertRaises(CapturePathError):
            resolve_capture(self.tmp.name)

    def test_rejects_a_missing_file(self):
        with self.assertRaises(CapturePathError):
            resolve_capture(os.path.join(self.tmp.name, "absent.rdc"))

    def test_rejects_an_empty_path(self):
        for value in (None, "", "   "):
            with self.assertRaises(CapturePathError):
                resolve_capture(value)


class TestClampLimits(unittest.TestCase):
    def test_clamps_an_oversized_request_to_the_ceiling(self):
        self.assertEqual(clamp_limits(max_draws=10 ** 9,
                                       max_writers=10 ** 9),
                         {"max_draws": MAX_DRAWS, "max_writers": MAX_WRITERS})

    def test_leaves_a_smaller_request_alone(self):
        self.assertEqual(clamp_limits(max_draws=4, max_writers=2),
                         {"max_draws": 4, "max_writers": 2})

    def test_floors_at_one_so_a_request_is_never_handed_on_as_zero(self):
        self.assertEqual(clamp_limits(max_draws=0, max_writers=-5),
                         {"max_draws": 1, "max_writers": 1})

    def test_absent_limits_stay_absent(self):
        # Forwarding a clamp of None would override the worker default with a
        # value the caller never asked for.
        self.assertEqual(clamp_limits(), {})

    def test_expand_reads_is_carried_through_as_a_bool(self):
        self.assertEqual(clamp_limits(expand_reads=1),
                         {"expand_reads": True})


class TestRedact(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.pop(ENV_ROOTS, None)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._prev is None:
            os.environ.pop(ENV_ROOTS, None)
        else:
            os.environ[ENV_ROOTS] = self._prev

    def test_removes_the_capture_path_itself(self):
        cap = os.path.join(default_root(), "w00001_frame11.rdc")
        self.assertNotIn(cap, redact("cannot open " + cap, cap))
        self.assertIn("<capture>", redact("cannot open " + cap, cap))

    def test_removes_a_truncated_prefix_of_the_root(self):
        frag = os.path.dirname(default_root())
        out = redact("failed under " + frag, None)
        self.assertNotIn(frag, out)
        self.assertIn("<capture-root>", out)

    def test_removes_a_path_above_the_root(self):
        frag = os.path.dirname(os.path.dirname(default_root()))
        self.assertNotIn(frag, redact("at " + frag, None))

    def test_keeps_the_useful_part_of_the_message(self):
        # The control exists to hide the host, not to silence the diagnosis.
        self.assertIn("capture", redact("capture file does not exist", None))

    def test_leaves_a_message_without_paths_untouched(self):
        msg = "worker exited before answering"
        self.assertEqual(redact(msg, None), msg)


if __name__ == "__main__":
    unittest.main()
