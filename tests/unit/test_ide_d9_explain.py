import json
import pathlib
import re
import subprocess
import tempfile
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent.parent
        / "src" / "rdebug_ide" / "static" / "index.html")

DIFF_OK = {"comparison": "different",
           "firstDivergence": {"layer": "L1", "good": {"value": 0},
                               "bad": {"value": 1}},
           "layers": [{"layer": "L1", "status": "different"}]}
TRACE_OK = {"edges": [], "summary": {"target": "320,240", "modificationCount": 0,
                                     "finalValue": 0}}
EXPLAIN_OK = {"prompt": "DEFAULT PROMPT", "evidenceIds": []}

# Every endpoint has a valid default so that a mutant which starts calling an
# endpoint the scenario did not plan still runs to completion. The point is to
# observe the violated property, not to let the mutant die on a null payload and
# have that mistaken for a caught regression.
DEFAULTS = {"diff": DIFF_OK, "trace": TRACE_OK, "explain": EXPLAIN_OK,
            "info": {"capture": "cap"}, "resource": {"resourceId": "ResourceId::1"},
            "ci": {"enabled": False}}


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


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


def afn(src: str, name: str) -> str:
    return "async " + fn(src, name)


PRELUDE = r"""
const writes = [];
const store = {};
const $ = id => store[id] || (store[id] = new Proxy({},
  {set(t,k,v){writes.push({id:id, k:k, v:String(v)}); t[k]=v; return true;},
   get(t,k){
     if (k === "querySelectorAll") return () => [];
     if (k === "checked") return t[k] === undefined ? false : t[k];
     return t[k] === undefined ? "" : t[k];
   }}));
const calls = [];
let plan = {};
const DEFAULTS = __DEFAULTS__;

function payloadFor(path) {
  for (const k of Object.keys(DEFAULTS)) if (path.includes("/api/" + k)) return DEFAULTS[k];
  return {};
}

function fetch(url) {
  const path = String(url).split("?")[0];
  calls.push(path);
  const key = Object.keys(plan).find(k => path.includes(k));
  const step = key ? plan[key] : {json: payloadFor(path)};
  const status = step.status || 200;
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status: status,
    json: () => ("json" in step && step.json !== null)
      ? Promise.resolve(step.json)
      : ("raw" in step ? Promise.reject(new Error("not json"))
                      : Promise.resolve(payloadFor(path))),
  });
}

function reset() { writes.length = 0; calls.length = 0; }
function snap() { return writes.map(w => w.id + "." + w.k); }
// A render into #result is not a failure report. Only the banner counts,
// otherwise a successful diff would satisfy the containment check.
function bannerShown() {
  return writes.some(w => w.id === "result" && String(w.v).indexOf("banner-warn") >= 0);
}
"""

DRIVER = r"""
async function main() {
  $("a").value = "320,240";
  $("b").value = "10,10";

  // E2: the button asks only for the prompt.
  reset();
  plan = {"/api/explain": {json: {prompt: "P1"}}};
  await $("btnExplain").onclick();
  const e2_urls = calls.slice();
  const e2_prompt = $("prompt").value;
  const e2_copy_disabled = $("btnCopy").disabled;

  // E3: an explain failure is reported and leaves no prompt behind.
  reset();
  plan = {"/api/explain": {status: 500, json: {error: "boom"}}};
  await $("btnExplain").onclick();
  const e2b_prompt = $("prompt").value;
  const e2b_reported = bannerShown();
  const e2b_copy_disabled = $("btnCopy").disabled;

  // E3 again, but reached through a diff rather than the button.
  reset();
  plan = {"/api/explain": {status: 500, json: {error: "no"}}};
  await doDiff();
  const e3_urls = calls.slice();
  const e3_prompt = $("prompt").value;
  const e3_reported = bannerShown();
  const e3_copy_disabled = $("btnCopy").disabled;

  // E6: a stale explain is discarded without touching the prompt.
  reset();
  plan = {"/api/explain": {json: {prompt: "P2"}}};
  const mine = claim();
  await new Promise(r => setTimeout(r, 5));
  const theirs = claim();
  const p = await api("/api/explain");
  $("prompt").value = "";
  const applied = [];
  const accepted = enterSeq(mine, p, () => applied.push("applied"));
  const acceptedCurrent = enterSeq(theirs, p, () => applied.push("current"));

  console.log(JSON.stringify({
    e2_urls, e2_prompt, e2_copy_disabled,
    e2b_prompt, e2b_reported, e2b_copy_disabled,
    e3_urls, e3_prompt, e3_reported, e3_copy_disabled,
    stale: isStale(mine), applied,
    accepted: accepted, accepted_current: acceptedCurrent,
  }));
}
main();
"""


def build(src: str) -> str:
    parts = [PRELUDE.replace("__DEFAULTS__", json.dumps(DEFAULTS)),
             "let lastDiff = null;", "const MAX_DRAWS = 16;",
             fn(src, "esc"),
             re.search(r"const FAILURE_TEXT = \{.*?\};", src, re.S).group(0),
             fn(src, "showFailure"), fn(src, "showOk"), fn(src, "enter"),
             "let currentSeq = 0;",
             fn(src, "claim"), fn(src, "isStale"), fn(src, "enterSeq"),
             fn(src, "applyExplain"), fn(src, "clearExplain"),
             afn(src, "api"), fn(src, "statusSpan"),
             fn(src, "renderDiff"), fn(src, "renderTrace"),
             fn(src, "parseCoord"), fn(src, "canonicalResourceId"),
             afn(src, "doDiff"), afn(src, "doExplain"),
             re.search(r'^.*\$\("btnExplain"\)\.onclick.*$', src, re.M).group(0),
             DRIVER]
    return "\n".join(parts)


def run(src: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(build(src))
        path = fh.name
    r = subprocess.run(["node", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("harness failed: " + r.stderr[-700:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def violations(res: dict) -> list:
    bad = []
    if "/api/diff" in res["e2_urls"]:
        bad.append("E2 button re-ran the diff: {}".format(res["e2_urls"]))
    if res["e2_prompt"] != "P1":
        bad.append("E2 prompt not applied: {!r}".format(res["e2_prompt"]))
    if not res["e2b_reported"]:
        bad.append("E3 explain failure was not reported")
    if res["e2b_prompt"] != "" or res["e2b_copy_disabled"] is not True:
        bad.append("E3 failed explain left a usable prompt: {!r}".format(res["e2b_prompt"]))
    if not res["e3_reported"]:
        bad.append("E3 diff-time explain failure was not reported")
    if res["e3_prompt"] != "" or res["e3_copy_disabled"] is not True:
        bad.append("E3 diff-time failure left a usable prompt: {!r}".format(res["e3_prompt"]))
    if res["e2_copy_disabled"] is not False:
        bad.append("E4 copy stayed disabled with a prompt present")
    if res["stale"] is not True or res["applied"] != ["current"]:
        bad.append("E6 stale explain was applied: {}".format(res["applied"]))
    if res["accepted_current"] is not True:
        bad.append("E6 the current explain was rejected")
    return bad


MUT_E2 = ('$("btnExplain").onclick = doExplain;', '$("btnExplain").onclick = doDiff;')
MUT_E3 = ("if (!enterSeq(seq, p, applyExplain)) clearExplain();",
          '$("prompt").value = (p.ok && p.data && p.data.prompt) || "";')


class TestExplainContract(unittest.TestCase):
    def setUp(self):
        self.res = run(page())

    def test_e2_the_button_requests_only_the_prompt(self):
        self.assertNotIn("/api/diff", self.res["e2_urls"])
        self.assertEqual(self.res["e2_prompt"], "P1")

    def test_e3_an_explain_failure_is_reported_and_leaves_no_prompt(self):
        self.assertTrue(self.res["e2b_reported"], "the failure reached no DOM")
        self.assertEqual(self.res["e2b_prompt"], "")
        self.assertIs(self.res["e2b_copy_disabled"], True)
        self.assertTrue(self.res["e3_reported"])
        self.assertEqual(self.res["e3_prompt"], "")
        self.assertIs(self.res["e3_copy_disabled"], True)

    def test_e4_copy_follows_the_prompt_that_exists(self):
        self.assertIs(self.res["e2_copy_disabled"], False)

    def test_e6_a_stale_explain_is_discarded_and_the_current_one_kept(self):
        self.assertIs(self.res["stale"], True)
        self.assertEqual(self.res["applied"], ["current"])
        self.assertIs(self.res["accepted_current"], True)

    def test_e1_the_label_describes_the_artefact(self):
        src = page()
        self.assertIn("Generate AI Prompt", src)
        self.assertNotIn("Explain with AI", src)

    def test_e5_no_new_state_enum(self):
        # Comments are stripped first: this file's own rationale mentions the
        # things it refuses to add, and a token scan that cannot tell a comment
        # from code would flag its own explanation.
        code = re.sub(r"//[^\n]*", "", page()).lower()
        for token in ("unavailable", "not_available", "capability",
                      "capabilities", "ai_unavailable"):
            with self.subTest(token=token):
                self.assertNotIn(token, code)

    def test_the_failure_check_is_not_satisfied_by_a_plain_render(self):
        # A successful diff writes #result too, so if this check were just
        # "did #result change" it would pass for the wrong reason.
        self.assertIn("/api/diff", self.res["e3_urls"])
        self.assertIs(self.res["e3_reported"], True)

    def test_nothing_is_broken_today(self):
        self.assertEqual(violations(self.res), [])


class TestExplainMutations(unittest.TestCase):
    """A mutant that crashes the harness has not been caught; it has only
    stopped the test, which is a different and much weaker claim."""

    def _run_mutant(self, pair):
        src = page()
        self.assertIn(pair[0], src, "mutation anchor missing")
        mutant = src.replace(*pair)
        self.assertNotEqual(mutant, src, "mutation did not apply")
        return run(mutant)

    def test_wiring_the_button_back_to_do_diff_is_caught(self):
        broken = violations(self._run_mutant(MUT_E2))
        self.assertTrue(any(b.startswith("E2") for b in broken),
                        f"E2 survived the mutation: {broken}")

    def test_restoring_the_silent_prompt_clear_is_caught(self):
        broken = violations(self._run_mutant(MUT_E3))
        self.assertTrue(any(b.startswith("E3") for b in broken),
                        f"E3 survived the mutation: {broken}")


if __name__ == "__main__":
    unittest.main()
