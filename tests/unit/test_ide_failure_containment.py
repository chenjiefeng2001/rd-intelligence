"""P2-C / F1 -- failure containment at the client/API boundary.

MUTATION CONTROLS (M1-M5)
==========================
Each test below asserts on a *source property* of the shipped page, so that
reverting the fix fails the test rather than passing silently:

  M1  removing the r.ok check                     -> FAIL
  M2  returning r.json() straight to a renderer  -> FAIL
  M3  restoring .catch(() => null)                -> FAIL
  M4  an uncontained fetch rejection             -> FAIL
  M5  an unclassified malformed response         -> FAIL

These are source assertions, not executed browser behaviour. That limitation
is deliberate and recorded: browser-level propagation is P9/P10.
"""
import pathlib
import re
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent.parent /
        "src" / "rdebug_ide" / "static" / "index.html")


def page():
    return PAGE.read_text(encoding="utf-8")


class TestClientResultEnvelope(unittest.TestCase):
    """M1/M5: the four outcomes are kept apart at the boundary."""

    def test_m1_the_ok_status_is_actually_checked(self):
        self.assertIn("if (!r.ok)", page())

    def test_m5_a_non_json_body_is_classified_rather_than_thrown(self):
        src = page()
        self.assertIn('kind:"malformed"', src)

    def test_m4_a_rejected_fetch_is_contained(self):
        src = page()
        self.assertIn('kind:"transport_error"', src)
        # The fetch call itself must sit inside a try, not be awaited bare.
        self.assertIn("try {\n    r = await fetch(path);", src)

    def test_a_valid_payload_is_wrapped_as_ok(self):
        self.assertIn("return {ok:true, data:body};", page())

    def test_an_error_body_on_a_200_is_still_an_error(self):
        # The server can answer 200 with an error payload; treating that as data
        # is the same defect as ignoring r.ok.
        self.assertIn("body.error", page())

    def test_the_envelope_is_client_internal_not_the_semantic_contract(self):
        # The rationale lives in the comment, so the comment body is kept and
        # only the hard wrapping and the leading markers are removed.
        lines = [re.sub(r"^\s*//\s?", "", ln) for ln in page().splitlines()]
        prose = " ".join(" ".join(lines).split())
        self.assertIn("Internal to this page", prose)
        self.assertIn("not the semantic API contract", prose)
        self.assertIn("the server's JSON contract is unchanged", prose)


class TestFailureCannotReachARenderer(unittest.TestCase):
    def test_m2_no_call_site_passes_an_api_result_straight_to_a_renderer(self):
        # A definition legitimately reads "function renderDiff(d) {", so only
        # call positions are inspected: a bare invocation, or an await whose
        # result is handed over without passing a guard.
        for line in page().splitlines():
            code = line.strip()
            if code.startswith("function "):
                continue
            for name in ("renderDiff(", "renderTrace("):
                self.assertNotIn(
                    name, code,
                    f"{name} appears unguarded in: {code}")

    def test_every_consumer_goes_through_a_guard(self):
        # This used to assert the exact literal "if (!enter(d, renderDiff))
        # return;", which pinned one spelling of the guard rather than the
        # property. D11 legitimately routes it through enterSeq instead, so the
        # control is expressed structurally now: the renderer is still reached
        # only through a guard, and the guard set is closed.
        src = page()
        guards = ("enter", "enterSeq", "showOk")
        for renderer in ("renderDiff", "renderTrace"):
            hits = [ln.strip() for ln in src.splitlines()
                    if re.search(r"if \(!{}\(".format("|".join(guards)), ln)
                    and re.search(rf"\b{renderer}\b", ln)]
            self.assertTrue(hits,
                            f"{renderer} is not reached through a guard")
            for line in hits:
                self.assertNotRegex(
                    line, r"=\s*await\s+api\(",
                    f"{renderer} consumes an api() result without guarding: {line}")
        self.assertIn("if (!showOk(ciResult)) return;", src)
        self.assertIn("if (i.ok) $(\"capture\").textContent", src)

    def test_every_guard_still_reaches_the_containment(self):
        # A guard that does not delegate is not containment, and the previous
        # literal assertion could not tell the difference. The guard set is
        # enumerated rather than hardcoded: containment is a P2-C property, so
        # this control must not come to depend on whichever guards a later
        # phase happens to add.
        found = [n for n in ("enter", "enterSeq", "showOk")
                 if f"function {n}(" in page()]
        self.assertIn("enter", found)
        guards = ("enter", "enterSeq", "showOk")
        for name in found:
            with self.subTest(guard=name):
                # Transitive: a guard may reach the reporter by delegating to
                # another guard, so the closure is walked rather than the body
                # of the outermost function being inspected.
                seen, stack, reached = set(), [name], False
                while stack:
                    cur = stack.pop()
                    if cur in seen:
                        continue
                    seen.add(cur)
                    body = self._body(cur)
                    if "showFailure" in body:
                        reached = True
                        break
                    for g in guards:
                        if f"{g}(" in body:
                            stack.append(g)
                self.assertTrue(reached,
                                f"{name} never reaches showFailure: {seen}")

    def _body(self, name):
        src = page()
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

    def test_the_info_then_callback_guards_on_ok(self):
        # A bare .then(i => i.capture) would read .capture off an envelope.
        self.assertNotIn(".then(i => { $(\"capture\").textContent = i.capture; })",
                         page())


class TestD6IsGone(unittest.TestCase):
    def test_m3_the_null_swallowing_catch_is_removed(self):
        self.assertNotIn("catch(()=>null)", page())

    def test_the_resource_call_goes_through_the_client_boundary(self):
        # Flattened before matching, as elsewhere in this file: the property is
        # that the resource request is issued through api() rather than by a
        # bare fetch, and that is not a statement about where the line wraps.
        src = re.sub(r"\s+", " ", page())
        self.assertRegex(src, r"const r = await api\(\s*`/api/resource",
                         "the resource request no longer goes through api()")
        self.assertNotRegex(src, r"fetch\(\s*`/api/resource",
                            "a bare fetch bypassed the client boundary")


class TestGuardsDoNotBecomeAStateMachine(unittest.TestCase):
    """The scope boundary: containment is not D11."""

    def test_no_idle_loading_or_unknown_lifecycle_was_introduced(self):
        src = page().lower()
        for token in ("idle", "loading_state", "unknown_state", "statemachine"):
            self.assertNotIn(token, src,
                             f"{token} would be D11 creeping into F1")

    def test_failure_wording_is_plain_and_does_not_map_outcomes_to_stages(self):
        src = page()
        # `kind` selects wording only. There must be no outcome-to-stage map.
        self.assertNotIn("transport_error: \"UNKNOWN\"", src)
        self.assertNotIn("api_error: \"ERROR\"", src)

    def test_the_semantic_api_and_evidence_contract_are_untouched(self):
        # F1 changes the page only. app.py keeps owning the JSON contract.
        app = (PAGE.parent.parent / "app.py").read_text(encoding="utf-8")
        self.assertIn("status, payload = route(parsed.path, query)", app)
        self.assertIn("body = to_json(payload)", app)


class TestFailureStillGetsShownSomehow(unittest.TestCase):
    """Containment must not become silent failure."""

    def test_a_failure_produces_a_visible_banner(self):
        src = page()
        self.assertIn("function showFailure(", src)
        self.assertIn("banner-warn", src)

    def test_every_failure_class_has_wording(self):
        src = page()
        for kind in ("transport_error", "malformed", "api_error"):
            self.assertIn(kind + ":", src)


if __name__ == "__main__":
    unittest.main()
