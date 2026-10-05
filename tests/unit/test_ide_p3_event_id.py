import json
import pathlib
import re
import subprocess
import tempfile
import unittest

from rdebug.errors import RDebugError

PAGE = (pathlib.Path(__file__).resolve().parent.parent.parent
        / "src" / "rdebug_ide" / "static" / "index.html")
APP = (pathlib.Path(__file__).resolve().parent.parent.parent
       / "src" / "rdebug_ide" / "app.py")


def eid_param():
    """Fetch the IDE's eid handling, failing as a property rather than a crash.

    A module-level import would turn a reverted phase into a collection error,
    and a collection error says only that the module is gone. It is not evidence
    that the malformed-input behaviour stopped holding.
    """
    try:
        from rdebug_ide.app import _eid_param as impl
    except ImportError as exc:
        raise AssertionError(
            "the IDE exposes no event-id parameter handling, so the transport "
            f"and classification properties cannot hold: {exc}")
    return impl


def api_info(query):
    from rdebug_ide.app import api_info as impl
    return impl(query)


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def app() -> str:
    return APP.read_text(encoding="utf-8")


def fn(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    i, depth = src.index("{", start), 0
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1


def _eid_param_js(page_src: str, values: dict, key: str) -> str:
    return ("const VALUES = " + json.dumps(values) + ";\n"
            "const $ = id => ({ value: VALUES[id] });\n"
            + fn(page_src, "eidParam") + "\n"
            "VALUES.__id = " + json.dumps(key) + ";\n"
            "console.log(JSON.stringify(eidParam()));\n")


def _node(js: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js)
        path = fh.name
    r = subprocess.run(["node", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("probe failed: " + r.stderr[-500:])
    return r.stdout.strip().splitlines()[-1]


def probe_eid(values: dict, page_src: str = None) -> dict:
    """Run the page's own eidParam() once per value and record what it produced.

    The page reads $("eid"), so each run supplies a single-value table under
    that exact key rather than trying to index a table by case name.
    """
    src = page() if page_src is None else page_src
    return {k: json.loads(_node(_eid_param_js(src, {"eid": v}, "eid")))
            for k, v in values.items()}


def pyfn(src: str, name: str) -> str:
    """Slice one python def out of a module."""
    start = src.index(f"def {name}(")
    rest = src[start + 1:]
    end = rest.find("\n\ndef ")
    return src[start:start + 1 + (end if end >= 0 else len(rest))]


def urls_for(page_src: str) -> dict:
    """Which endpoint templates interpolate the event id, and which do not."""
    out = {}
    for name, pat in (("trace", r"/api/trace\?[^`]*"),
                      ("resource", r"/api/resource\?[^`]*"),
                      ("diff", r"/api/diff\?[^`]*"),
                      ("explain", r"/api/explain\?[^`]*")):
        hits = re.findall(pat, page_src)
        out[name] = [h for h in hits]
    return out


class TestEventIdFormat(unittest.TestCase):
    """E2/E3: the IDE decides the format only. Legality is the action tree's
    job, so nothing here may encode a range or a membership rule."""

    def test_absent_or_blank_means_no_event_context(self):
        self.assertIsNone(eid_param()({}))
        self.assertIsNone(eid_param()({"eid": [""]}))
        self.assertIsNone(eid_param()({"eid": ["   "]}))

    def test_a_well_formed_integer_is_carried_through_exactly(self):
        self.assertEqual(eid_param()({"eid": ["100"]}), 100)
        self.assertEqual(eid_param()({"eid": [" 100 "]}), 100)
        self.assertEqual(eid_param()({"eid": ["0"]}), 0)

    def test_a_malformed_value_is_a_parameter_error(self):
        for bad in ("abc", "1.5", "1e3", "+5", "0x10", "100 200", "١٠٠"):
            with self.subTest(value=bad):
                with self.assertRaises(RDebugError) as ctx:
                    eid_param()({"eid": [bad]})
                self.assertEqual(getattr(ctx.exception, "kind", None),
                                 "bad_request",
                                 f"{bad!r} must be classified, not guessed")


class TestEventIdScopeIsVisible(unittest.TestCase):
    """E1'. Declaring the scope is not enough; the wiring has to match it."""

    def test_the_scope_is_stated_on_the_page(self):
        src = page()
        self.assertIn('id="eidscope"', src)
        self.assertIn("Applies to", src)
        self.assertIn("Does not apply to", src)
        for label in ("Trace", "Resource", "Diff", "Generate AI Prompt"):
            with self.subTest(label=label):
                self.assertIn(label, src)

    def test_trace_and_resource_send_the_event(self):
        u = urls_for(page())
        for name in ("trace", "resource"):
            with self.subTest(endpoint=name):
                self.assertTrue(u[name], f"{name} template missing")
                self.assertTrue(any("eidParam()" in h for h in u[name]),
                                f"{name} does not send the event id")

    def test_diff_and_explain_never_send_the_event(self):
        # diff_pixel has no context_eid parameter, so sending one would be
        # silently discarded while the result still looked correct.
        u = urls_for(page())
        for name in ("diff", "explain"):
            with self.subTest(endpoint=name):
                self.assertTrue(u[name], f"{name} template missing")
                for hit in u[name]:
                    self.assertNotIn("eid", hit,
                                     f"{name} would send an event id it cannot use")


class TestEventIdTransport(unittest.TestCase):
    """E2, executed: what the page actually puts on the wire."""

    def test_the_value_is_sent_as_typed_and_omitted_when_blank(self):
        out = probe_eid({"v_100": "100", "v_blank": "", "v_spaces": "  ",
                         "v_padded": " 42 ", "v_text": "abc"})
        self.assertEqual(out["v_100"], "&eid=100")
        self.assertEqual(out["v_blank"], "")
        self.assertEqual(out["v_spaces"], "")
        self.assertEqual(out["v_padded"], "&eid=42")
        self.assertEqual(out["v_text"], "&eid=abc")

    def test_nothing_is_renumbered_or_clamped(self):
        out = probe_eid({"v_big": "999999999", "v_neg": "-3", "v_zero": "0"})
        self.assertEqual(out["v_big"], "&eid=999999999")
        self.assertEqual(out["v_neg"], "&eid=-3")
        self.assertEqual(out["v_zero"], "&eid=0")


class TestNoScopeCreep(unittest.TestCase):
    """E3/E5/E6: the three things this phase promised not to touch."""

    def test_e3_the_ide_holds_no_event_membership_rule(self):
        body = pyfn(app(), "_eid_param")
        for token in ("valid_event_ids", "action_rows", "SetFrameEvent",
                      "min(", "max("):
            with self.subTest(token=token):
                self.assertNotIn(token, body)

    def test_e5_info_gained_no_event_enumeration(self):
        info = json.dumps(api_info({}), sort_keys=True)
        for token in ("eid", "event", "events", "contextEventId"):
            with self.subTest(token=token):
                self.assertNotIn(token, info)

    def test_e6_ownership_and_lifecycle_are_unchanged(self):
        src = app()
        self.assertIn("_STATE = {\"capture\": None, \"baseline\": None, \"ready\": False}",
                      src)
        self.assertIn("def configure(capture, baseline=None, workers=None):", src)
        self.assertIn("The IDE owns at most one capture at a time", src)
        self.assertNotIn("switch_capture", src)
        self.assertNotIn("set_capture", src)


class TestEventIdMutations(unittest.TestCase):
    """Reverting the fix must fail the controls; the two mutations below are
    the two ways this feature could quietly reintroduce a wrong answer."""

    def _mutant(self, old, new):
        src = page()
        self.assertIn(old, src, "mutation anchor missing")
        out = src.replace(old, new)
        self.assertNotEqual(out, src, "mutation did not apply")
        return out

    def test_sending_the_event_to_diff_is_caught(self):
        # This is the exact silent wrong-answer the phase refused to ship.
        bad = self._mutant("/api/diff?a=${a}&b=${b}&deep=${deep}",
                           "/api/diff?a=${a}&b=${b}&deep=${deep}${eidParam()}")
        u = urls_for(bad)
        self.assertIn("eid", " ".join(u["diff"]),
                      "diff gained an event id and nothing noticed")

    def test_renumbering_the_event_is_caught(self):
        bad = self._mutant('return raw ? "&eid=" + encodeURIComponent(raw) : "";',
                           'return raw ? "&eid=" + (parseInt(raw, 10) + 1) : "";')
        got = json.loads(_node(_eid_param_js(bad, {"eid": "100"}, "eid")))
        self.assertNotEqual(got, "&eid=100",
                            "the transport renumbered the event and nothing noticed")


if __name__ == "__main__":
    unittest.main()
