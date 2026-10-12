"""Real-replay browser controls, run where their prerequisites are declared.

These classes drive a real browser against a server owning a real capture. Both
prerequisites -- an external capture and an importable renderdoc module -- are
declared by the integration gate in release-gates.json and are not prerequisites
of the unit gate.

They lived under tests/unit, so on a runner lacking those prerequisites they
could only skip, and release_gate maps any skip to UNKNOWN: the unit gate
reported "no content conclusion for the skipped part" everywhere and could never
reach PASS. Nothing is lost by the move. The integration gate already requires
exactly these prerequisites and reports INFRASTRUCTURE_FAILURE for them, which is
the classification the contract gives that condition.

Moved verbatim; the classes and their shared base are byte-identical to what was
under tests/unit. The browser helpers are imported from that module rather than
duplicated, so there is still one definition of how a browser is chosen and one
control over that decision.
"""

import json
import os
import unittest

from tests.unit.test_ide_ui_browser import (
    BROWSER,
    Live,
    _launch_browser,
    _real_replay_ready,
    _release_browser_class,
    app,
)


class RealCaptureBrowser:
    """A browser against a server that owns a real capture.

    Shared by the classes that need one, because configuring a capture is
    process-wide and expensive: a worker process, an eager ping, and a single
    owner that must be released again or every later class in this file answers
    as a ready server.

    Configured the way the CLI configures it, not over HTTP. There is no
    `/api/configure` route, because a second controller for a capture is exactly
    what the one-owner rule forbids.
    """

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        try:
            cls._pw = sync_playwright().start()
            cls.browser = _launch_browser(cls._pw, BROWSER)
            cls.live = Live(store=False)
            cls.capture = os.environ["RDEBUG_INTEGRATION_CAPTURE"]
        except BaseException:
            # Only a configure() failure is a skip. A launch or a missing
            # capture variable stays an error, so the distinction the original
            # code drew is unchanged -- it just no longer leaks the driver.
            _release_browser_class(cls)
            raise
        try:
            app.configure(cls.capture)
        except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
            _release_browser_class(cls)
            raise unittest.SkipTest(
                "configure(" + str(cls.capture) + ") failed: " + str(exc)) from exc

    @classmethod
    def tearDownClass(cls):
        app.dispose()
        _release_browser_class(cls)

    def configured_page(self):
        ctx = self.browser.new_context(viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        self.addCleanup(ctx.close)
        page.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                  wait_until="networkidle")
        ready = page.evaluate(
            "async () => (await (await fetch('/api/info')).json()).ready")
        self.assertTrue(ready, "the server should report a configured capture")
        return page


@unittest.skipUnless(
    _real_replay_ready(),
    "set RDEBUG_INTEGRATION_CAPTURE to a .rdc file and make the renderdoc "
    "python module importable (RDEBUG_RENDERDOC_PATH) to walk the chain "
    "against real replay data",
)
class TestTheEvidenceChainAgainstARealCapture(RealCaptureBrowser, unittest.TestCase):
    """The chain, with real layers and real observations behind it.

    The other class proves the panel handles failure. This one proves it shows
    the actual reasoning, which is the whole reason it exists -- and it needs a
    configured server, because an unconfigured one never produces a chain worth
    reading.
    """

    def test_the_ladder_has_one_step_per_layer(self):
        page = self.configured_page()
        page.fill("#a", "320,240")
        page.fill("#b", "10,10")
        page.click("#btnDiff")
        page.wait_for_selector('[data-testid="chain-step"]', timeout=120000)
        steps = page.eval_on_selector_all(
            '[data-testid="chain-step"]',
            "els => els.map(e => e.textContent)")
        self.assertGreaterEqual(len(steps), 2)

    def test_exactly_one_step_is_marked_as_the_first_difference(self):
        page = self.configured_page()
        page.fill("#a", "320,240")
        page.fill("#b", "10,10")
        page.click("#btnDiff")
        page.wait_for_selector('[data-testid="chain-step"]', timeout=120000)
        marked = page.query_selector_all(".chain__step--first")
        self.assertEqual(len(marked), 1)

    def test_the_divergence_shows_both_sides_with_their_observations(self):
        page = self.configured_page()
        page.fill("#a", "320,240")
        page.fill("#b", "10,10")
        page.click("#btnDiff")
        page.wait_for_selector('[data-testid="chain-evidence"]', timeout=120000)
        text = page.inner_text('[data-testid="chain"]')
        self.assertIn("ReplayController", text)

    def test_the_trace_chain_walks_the_edges_with_their_evidence(self):
        page = self.configured_page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="chain-path"]', timeout=120000)
        hops = page.query_selector_all(".chain__hop")
        self.assertGreaterEqual(len(hops), 1)
        self.assertGreaterEqual(
            len(page.query_selector_all('[data-testid="chain-evidence"]')), 1)

    def test_a_resource_in_the_chain_opens_that_resource(self):
        page = self.configured_page()
        page.fill("#a", "320,240")
        page.fill("#b", "10,10")
        page.click("#btnDiff")
        page.wait_for_selector(".chain__ev .chip--link", timeout=120000)
        # `.first` because a diff names the same resource on both sides, so
        # there are legitimately several chips and the selector is not unique.
        target = page.inner_text(".chain__ev .chip--link")
        before = page.text_content('[data-testid="result"]')
        page.locator(".chain__ev .chip--link").first.click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid=\"result\"]')"
            ".textContent !== " + json.dumps(before), timeout=120000)
        after = page.text_content('[data-testid="result"]')
        self.assertNotEqual(before, after)
        self.assertIn(target, after)

    def test_a_real_capture_breaks_into_two(self):
        page = self.configured_page()
        page.fill("#a", "320,240")
        page.fill("#b", "10,10")
        page.click("#btnDiff")
        page.wait_for_selector('[data-testid="chain-step"]', timeout=120000)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth")
        self.assertLessEqual(overflow, 0)


@unittest.skipUnless(
    _real_replay_ready(),
    "set RDEBUG_INTEGRATION_CAPTURE to a .rdc file and make the renderdoc "
    "python module importable (RDEBUG_RENDERDOC_PATH) to observe a streamed "
    "query event against a configured capture",
)
class TestAQueryIsStreamedAgainstARealCapture(RealCaptureBrowser, unittest.TestCase):
    """A real `query` event, carried to a real browser, about a real query.

    This is the gap the browser evidence table still records as PARTIAL. The
    other real-capture class renders real results and shows the stream badge
    reading live; neither of those is the same claim. A badge proves a
    connection is open. It says nothing about whether a query event reached
    this browser carrying the values the server actually measured.

    So the listener here is a **second** EventSource, opened by the test rather
    than by the application. It observes the wire instead of trusting the app's
    own bookkeeping -- if the app parsed a frame wrong, or invented one, this
    listener is unaffected by that error.

    Three things make the evidence specific rather than merely present:

    * the connection is opened with no `lastEventId`, so the server sends
      `hello` and replays no backlog -- any `query` event seen afterwards was
      pushed live;
    * the event's revision must exceed the highest revision seen before the
      click, which is what rules out a replayed frame arriving late;
    * the event's `status` is compared against the HTTP status Playwright
      observed for that very request, so the number in the event has to be the
      number the server returned rather than a plausible-looking constant.
    """

    def _listen(self, page):
        """Open an independent EventSource and collect every frame it gets."""
        page.evaluate("""() => {
          window.__frames = [];
          const es = new EventSource('/api/events');
          const kinds = ['query', 'configured', 'disposed', 'hello', 'resync'];
          for (const kind of kinds) {
            es.addEventListener(kind, (e) => {
              let parsed = null;
              let parseError = null;
              try { parsed = JSON.parse(e.data); }
              catch (err) { parseError = String(err); }
              window.__frames.push({kind, parseError, event: parsed});
            });
          }
          window.__listener = es;
        }""")
        # The server answers a listener with no lastEventId by sending `hello`,
        # so waiting for one is waiting until the stream is genuinely open
        # rather than assuming the constructor was enough.
        page.wait_for_function(
            "() => window.__frames.some(f => f.kind === 'hello')",
            timeout=30000)
        return page.evaluate("() => window.__frames")

    def _queries(self, page):
        return page.evaluate(
            "() => window.__frames.filter(f => f.kind === 'query')"
            ".map(f => f.event)")

    def test_a_real_query_is_pushed_to_the_browser_with_real_values(self):
        page = self.configured_page()
        before = self._listen(page)
        highest_before = max((f["event"]["revision"] for f in before
                              if f["event"]), default=-1)

        # The HTTP status the server actually returns for this request, taken
        # from the network rather than from the event under test.
        statuses = []
        page.on("response", lambda r: statuses.append(
            (r.url, r.status)) if "/api/trace" in r.url else None)

        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_function(
            "() => window.__frames.some(f => f.kind === 'query'"
            " && f.event && f.event.detail"
            " && f.event.detail.endpoint === '/api/trace')",
            timeout=120000)

        events = self._queries(page)
        self.assertTrue(events, "no query event reached the browser")
        trace = [e for e in events if e["detail"]["endpoint"] == "/api/trace"]
        self.assertEqual(len(trace), 1,
                         "a trace issues one request, so one event is expected;"
                         " got " + str([e["detail"]["endpoint"] for e in events]))
        event = trace[0]

        # Streamed, not replayed: a frame that predates the click cannot
        # describe the click.
        self.assertGreater(event["revision"], highest_before,
                           "the event must be newer than anything seen before"
                           " the query, or it was replayed rather than pushed")

        # A real measurement: the status is the one the server returned, and the
        # latency is the one it measured.
        self.assertEqual(event["detail"]["status"], 200)
        self.assertTrue(statuses, "no /api/trace response was observed")
        self.assertEqual(event["detail"]["status"], statuses[-1][1],
                         "the streamed status must be the status actually"
                         " returned for that request")
        self.assertIs(event["detail"]["ok"], True)

        self.assertIsInstance(event["detail"]["latencyMs"], (int, float))
        self.assertGreater(event["detail"]["latencyMs"], 0,
                           "a real replay query takes measurable time")
        # Sanity bound, not a performance claim: it must be a duration, not a
        # timestamp and not a placeholder.
        self.assertLess(event["detail"]["latencyMs"], 60000)

    def test_the_frame_arrives_as_parseable_json(self):
        # Ties this control to the single-line frame rule. A pretty-printed
        # payload under one `data:` header arrives as `{`, and the listener
        # would record a parse error instead of an event.
        page = self.configured_page()
        self._listen(page)
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_function(
            "() => window.__frames.some(f => f.kind === 'query')",
            timeout=120000)
        errors = page.evaluate(
            "() => window.__frames.filter(f => f.parseError)"
            ".map(f => ({kind: f.kind, error: f.parseError}))")
        self.assertEqual(errors, [])

    def test_a_failed_query_is_streamed_too(self):
        # A stream that only carries successes is backwards for a tool whose
        # job is finding out what went wrong.
        #
        # The failure has to be one the **server** produced. A malformed
        # coordinate is rejected by the client before any request is spent, so
        # nothing is ever streamed for it -- which is the D7 contract working,
        # not a gap in the stream, and using it here would assert nothing. An
        # unusable `eid` passes the client untouched and is refused by the
        # semantic layer, so it is the right probe.
        page = self.configured_page()
        self._listen(page)
        page.fill("#a", "320,240")
        page.fill("#eid", "abc")
        page.click("#btnTrace")
        page.wait_for_function(
            "() => window.__frames.some(f => f.kind === 'query'"
            " && f.event && f.event.detail && f.event.detail.ok === false)",
            timeout=60000)
        failed = [e for e in self._queries(page)
                  if e["detail"]["ok"] is False]
        self.assertTrue(failed)
        self.assertEqual(failed[0]["detail"]["status"], 400)
        self.assertEqual(failed[0]["detail"]["endpoint"], "/api/trace")
        # A refusal is still a measurement, so it carries a latency too.
        self.assertGreater(failed[0]["detail"]["latencyMs"], 0)

    def test_a_client_side_rejection_costs_no_request_and_no_event(self):
        # The counterpart to the probe above, recorded because it is easy to
        # mistake for a gap: a coordinate the client refuses never reaches the
        # server, so it appears in the stream as nothing at all.
        page = self.configured_page()
        self._listen(page)
        before = len(self._queries(page))
        page.fill("#a", "not-a-coordinate")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="failure-banner"]', timeout=30000)
        page.wait_for_timeout(1500)
        self.assertEqual(len(self._queries(page)), before,
                         "a client-side rejection must not reach the server")
        self.assertTrue(page.is_visible('[data-testid="failure-banner"]'))

    def test_the_recorded_flag_reflects_this_row_not_the_process(self):
        # Regression control for a real defect: `recorded` was read from the
        # recorder's cumulative drop counter, so any earlier failure marked
        # every later event unrecorded. Here the store is not configured at
        # all, so False is the honest answer -- and it must be False for *this*
        # row without that being an accident of history.
        page = self.configured_page()
        self._listen(page)
        for xy in ("320,240", "100,100", "10,10"):
            page.fill("#a", xy)
            page.click("#btnTrace")
            page.wait_for_timeout(1200)
        events = self._queries(page)
        self.assertGreaterEqual(len(events), 3)
        self.assertTrue(all("recorded" in e["detail"] for e in events))
        # No store is configured for this class, so every one of these rows
        # genuinely failed to store.
        self.assertTrue(all(e["detail"]["recorded"] is False
                            for e in events))


if __name__ == "__main__":
    unittest.main()
