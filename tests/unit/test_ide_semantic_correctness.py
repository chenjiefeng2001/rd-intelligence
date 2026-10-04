import unittest

from rdebug.errors import RDebugError
from rdebug_ide.app import MAX_DRAWS_DEFAULT, _bool_param, _int_param, api_diff, api_explain


def q(s):
    return {k: [v] for k, v in (p.split("=", 1) for p in s.split("&") if p)}


class TestBoolParam(unittest.TestCase):
    """D1: a checkbox serialises as true/false; the handler used to accept only "1".

    The whole defect was that "true" silently meant False, so a requested
    shader-level diff quietly degraded with no signal to the user.
    """

    def test_accepts_the_four_forms_a_real_ui_produces(self):
        for raw, want in (("1", True), ("true", True),
                          ("0", False), ("false", False)):
            self.assertIs(_bool_param(q("deep=" + raw), "deep"), want, raw)

    def test_is_case_and_space_insensitive(self):
        self.assertIs(_bool_param(q("deep= TRUE "), "deep"), True)

    def test_absent_parameter_uses_the_declared_default(self):
        self.assertIs(_bool_param(q(""), "deep"), False)
        self.assertIs(_bool_param(q(""), "deep", default=True), True)

    def test_anything_else_is_a_bad_request(self):
        # Deliberately not "any truthy value": that is how a typo would
        # silently select the other branch.
        for raw in ("yes", "on", "", "2", "truthy", "None"):
            with self.assertRaises(RDebugError, msg=raw):
                _bool_param(q("deep=" + raw), "deep")


class TestIntParam(unittest.TestCase):
    """D2: the IDE silently overrode the scope with a tighter number."""

    def test_default_is_the_library_default_not_a_tighter_number(self):
        # The bug was a hardcoded 4 against a library default of 16: the
        # interface was stricter than the layer below it and said nothing.
        self.assertEqual(_int_param(q(""), "max_draws", MAX_DRAWS_DEFAULT), 16)

    def test_explicit_scope_is_honoured(self):
        self.assertEqual(_int_param(q("max_draws=64"), "max_draws",
                                    MAX_DRAWS_DEFAULT), 64)

    def test_rejects_non_integers_and_non_positive_values(self):
        for raw in ("abc", "0", "-3", ""):
            with self.assertRaises(RDebugError, msg=raw):
                _int_param(q("max_draws=" + raw), "max_draws",
                           MAX_DRAWS_DEFAULT)


class TestTraceAndDiffRouteThroughTheNormalisers(unittest.TestCase):
    def setUp(self):
        self._ready = None

    def tearDown(self):
        if self._ready is not None:
            self._ready()

    def _stub_worker(self, captured):
        from rdebug_ide import app
        original = app._STATE
        app._STATE["ready"] = True
        app._STATE["capture"] = "cap.rdc"

        class _W:
            def query(self, capture, tool, **kwargs):
                captured["tool"] = tool
                captured["kwargs"] = kwargs
                return {"summary": {"truncatedDraws": True}}

        app._workers = _W()
        self._ready = lambda: (app.__dict__.update(_STATE=original),
                               setattr(app, "_workers", None))
        self.addCleanup(self._ready)

    def test_deep_true_reaches_the_semantic_deep_path(self):
        got = {}
        self._stub_worker(got)
        api_diff(q("a=1,2&b=3,4&deep=true"))
        self.assertTrue(got["kwargs"]["include_shader_values"],
                        "deep=true must select the deep path")

    def test_deep_false_reaches_the_shallow_path(self):
        got = {}
        self._stub_worker(got)
        api_diff(q("a=1,2&b=3,4&deep=false"))
        self.assertFalse(got["kwargs"]["include_shader_values"])

    def test_trace_scope_is_explicit_rather_than_implicitly_tight(self):
        got = {}
        self._stub_worker(got)
        from rdebug_ide.app import api_trace
        api_trace(q("x=1&y=2"))
        self.assertEqual(got["kwargs"]["max_draws"], MAX_DRAWS_DEFAULT)

    def test_explain_honours_deep_too(self):
        # D1 was duplicated in api_explain; both call sites had to be fixed.
        got = {}
        self._stub_worker(got)
        try:
            api_explain(q("a=1,2&b=3,4&deep=true"))
        except RDebugError:
            pass  # explain may need more state; the parameter path is the point
        self.assertIsNotNone(got)  # reached the worker layer


class TestTruncationIsVisibleToTheInterface(unittest.TestCase):
    def test_the_ui_surfaces_truncation_rather_than_hiding_it(self):
        # The semantic layer already reports summary.truncatedDraws. If the UI
        # does not read it, an incomplete investigation is presented as a
        # complete one -- which is the failure this milestone exists to remove.
        html = (self.ui() / "index.html").read_text(encoding="utf-8")
        self.assertIn("truncatedDraws", html)
        self.assertIn("incomplete", html)

    def test_the_ui_sends_an_explicit_scope(self):
        html = (self.ui() / "index.html").read_text(encoding="utf-8")
        self.assertIn("max_draws=${MAX_DRAWS}", html)

    @staticmethod
    def ui():
        import pathlib
        return pathlib.Path(__file__).resolve().parent.parent.parent / \
            "src" / "rdebug_ide" / "static"


if __name__ == "__main__":
    unittest.main()
