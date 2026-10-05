import json
import pathlib
import re
import subprocess
import tempfile
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent.parent
        / "src" / "rdebug_ide" / "static" / "index.html")

MUTANT = "function isStale(seq) { return false; }"


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def extract(src: str, name: str) -> str:
    """Pull a function declaration out by balancing braces."""
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


SCENARIOS = r"""
function reset() { writes.length = 0; }
function snap() { return writes.map(w => w.id + "." + w.k); }
function ok(d) { return {ok:true, data:d}; }
function bad(kind) { return {ok:false, kind:kind, message:"boom"}; }

const A = {};

// A1  out-of-order arrival: the older request lands last and must not render.
const a1seq = claim(); claim(); reset();
enterSeq(a1seq, ok({n:"first"}), () => writes.push({id:"RENDER", k:"diff"}));
A.a1_writes = snap().length;

// A2  the CURRENT request failing must still be reported, not swallowed.
const a2seq = claim(); reset();
const a2ret = enterSeq(a2seq, bad("api_error"), () => writes.push({id:"RENDER", k:"x"}));
A.a2_returned = a2ret;
A.a2_wrote_result = snap().some(w => w.indexOf("result.") === 0);

// A3  claiming a newer request invalidates the one still in flight.
const a3old = claim(); claim(); reset();
enterSeq(a3old, ok({n:"inflight"}), () => writes.push({id:"RENDER", k:"inflight"}));
A.a3_writes = snap().length;

// A4  diff and trace share one domain, so a late diff cannot replace a trace.
const a4diff = claim(); const a4trace = claim(); reset();
enterSeq(a4trace, ok({n:"trace"}), () => writes.push({id:"RENDER", k:"trace"}));
const afterTrace = snap().length;
enterSeq(a4diff, ok({n:"diff"}), () => writes.push({id:"RENDER", k:"diff"}));
A.a4_trace_rendered = afterTrace;
A.a4_diff_writes = snap().length - afterTrace;

// A5  the evidence panel is a different target but the same domain.
const a5ev = claim(); const a5diff = claim(); reset();
enterSeq(a5ev, ok({n:"ev"}), () => writes.push({id:"evdetail", k:"textContent"}));
A.a5_ev_writes = snap().filter(w => w.indexOf("evdetail") === 0).length;
enterSeq(a5diff, ok({n:"d"}), () => writes.push({id:"result", k:"innerHTML"}));
A.a5_result_writes = snap().filter(w => w.indexOf("result") === 0).length;

// A6  a stale response writes nothing at all, including on the failure path.
const a6old = claim(); claim(); reset();
enterSeq(a6old, bad("transport_error"), () => writes.push({id:"RENDER", k:"never"}));
A.a6_writes = snap().length;
A.a6_detail = snap();

console.log(JSON.stringify(A));
"""


def build(src: str) -> str:
    return "\n".join([
        "const writes = [];",
        "const store = {};",
        "const $ = id => store[id] || (store[id] = new Proxy({},",
        "  {set(t,k,v){writes.push({id:id, k:k, v:v}); t[k]=v; return true;},",
        "   get(t,k){return t[k];}}));",
        extract(src, "esc"),
        re.search(r"const FAILURE_TEXT = \{.*?\};", src, re.S).group(0),
        extract(src, "showFailure"),
        extract(src, "showOk"),
        extract(src, "enter"),
        "let currentSeq = 0;",
        extract(src, "claim"),
        extract(src, "isStale"),
        extract(src, "enterSeq"),
        SCENARIOS,
    ])


def run(src: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(build(src))
        path = fh.name
    r = subprocess.run(["node", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("harness failed: " + r.stderr)
    return json.loads(r.stdout)


def violations(res: dict) -> list:
    bad = []
    if res["a1_writes"] != 0:
        bad.append("A1 out-of-order rendered")
    if res["a2_returned"] is not False or not res["a2_wrote_result"]:
        bad.append("A2 current failure was swallowed")
    if res["a3_writes"] != 0:
        bad.append("A3 in-flight request was not invalidated")
    if res["a4_trace_rendered"] != 1 or res["a4_diff_writes"] != 0:
        bad.append("A4 diff overwrote trace")
    if res["a5_ev_writes"] != 0 or res["a5_result_writes"] != 1:
        bad.append("A5 cross-region identity split")
    if res["a6_writes"] != 0:
        bad.append("A6 stale path wrote {}".format(res["a6_detail"]))
    return bad


class TestRequestIdentity(unittest.TestCase):
    """A1-A6, executed against the page's own guards in node against a counting
    DOM, because "the user probably would not notice" is not a property, and A6
    is specifically about writes that must never happen."""

    def setUp(self):
        self.res = run(page())

    def test_a1_an_out_of_order_older_response_does_not_render(self):
        self.assertEqual(self.res["a1_writes"], 0)

    def test_a2_the_current_request_failing_is_still_reported(self):
        self.assertIs(self.res["a2_returned"], False)
        self.assertTrue(self.res["a2_wrote_result"],
                        "a current failure must still reach the user")

    def test_a3_claiming_a_newer_request_invalidates_the_in_flight_one(self):
        self.assertEqual(self.res["a3_writes"], 0)

    def test_a4_a_late_diff_cannot_replace_a_newer_trace(self):
        self.assertEqual(self.res["a4_trace_rendered"], 1)
        self.assertEqual(self.res["a4_diff_writes"], 0)

    def test_a5_render_targets_share_one_generation_domain(self):
        self.assertEqual(self.res["a5_ev_writes"], 0)
        self.assertEqual(self.res["a5_result_writes"], 1)

    def test_a6_a_stale_response_writes_no_dom_including_on_failure(self):
        self.assertEqual(self.res["a6_writes"], 0, self.res["a6_detail"])

    def test_nothing_is_broken_today(self):
        self.assertEqual(violations(self.res), [])


class TestStaleMutation(unittest.TestCase):
    """The contract rather than the implementation: disabling the stale check
    has to break the properties above."""

    def test_disabling_is_stale_is_caught(self):
        src = page()
        self.assertEqual(violations(run(src)), [])
        mutant = src.replace(extract(src, "isStale"), MUTANT)
        self.assertNotEqual(mutant, src, "mutation did not apply")
        broken = violations(run(mutant))
        self.assertTrue(broken, "removing the stale guard changed nothing")
        for expected in ("A1", "A3", "A4", "A5", "A6"):
            self.assertTrue(any(b.startswith(expected) for b in broken),
                            f"{expected} survived the mutation: {broken}")
        self.assertFalse(any(b.startswith("A2") for b in broken),
                         "A2 must hold without staleness too, because a current "
                         f"failure is never stale: {broken}")


class TestNoStateMachine(unittest.TestCase):
    """A7. The name of the defect is not a mandate for a state machine."""

    def test_no_state_machine_tokens(self):
        src = page()
        for token in ("idle", "loading_state", "unknown_state", "statemachine",
                      "STALE_RESULT", "state ="):
            with self.subTest(token=token):
                self.assertNotIn(token, src)

    def test_identity_is_claimed_at_the_action_not_the_response(self):
        src = page()
        for fn in ("doDiff", "doTrace", "showEv"):
            with self.subTest(fn=fn):
                body = extract(src, fn)
                self.assertLess(body.index("claim();"), body.index("await"),
                                f"{fn} must claim before it awaits")


if __name__ == "__main__":
    unittest.main()
