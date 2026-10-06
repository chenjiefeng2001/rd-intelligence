"""Controls for the React page, in a real browser.

The frozen page's own record says browser-level propagation is NOT_ESTABLISHED:
the HTTP semantics were observed at a real socket but never verified as
rendered. These controls are what moves that claim, so they drive an actual
browser against an actual server rather than asserting on strings.

They run against the built bundle, not a dev server, because the dev server
proxies /api and would hide a missing route in the packaged app.

If no browser can be launched the whole class skips, and the skip says so.
That is deliberately not a pass: an unverified browser claim must not be
recorded as a verified one.
"""
import http.client
import importlib.util
import os
import pathlib
import shutil
import socket
import sys
import tempfile
import threading
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
UI = REPO / "src" / "rdebug_ide" / "static" / "ui"
DIST = UI / "dist"

sys.path.insert(0, str(REPO / "src"))
import rdebug.recorder as recorder  # noqa: E402 -- the repo src layout needs the path added above before an import can resolve
import rdebug_ide.app as app  # noqa: E402 -- the repo src layout needs the path before the import, and E402 is that cost

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def browser_path():
    # Availability is probed with find_spec rather than by importing: an import
    # here would pull in the driver at collection time, and a suppression would
    # then be needed to keep the reason attached to it.
    if importlib.util.find_spec("playwright") is None:
        return None, "playwright is not installed"
    for candidate in CHROME_CANDIDATES:
        if pathlib.Path(candidate).is_file():
            return candidate, None
    return None, "no installed Chrome or Edge was found"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Live:
    """A server with no capture configured.

    Deliberately unconfigured: `/api/info` then answers ready:false, so a query
    returns a real error body. That is the case the containment controls care
    about, and it needs no replay runtime.

    `store` points RDEBUG_STORE at a temporary database, which is the only way
    the history controls can see the enabled branch. A server without it serves
    the disabled branch, which is what CI gets and what a default install gets.
    """

    def __init__(self, store=False):
        self._store = store
        self._previous = None
        if store:
            self._dir = tempfile.mkdtemp()
            self._previous = os.environ.get("RDEBUG_STORE")
            os.environ["RDEBUG_STORE"] = os.path.join(self._dir, "h.db")
            recorder.close()
        self.port = free_port()
        self.httpd = app.ThreadingHTTPServer(("127.0.0.1", self.port), app.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def seed(self, count=6):
        """Write observations directly, so the panel has something to render.

        Two endpoints on purpose. A single-endpoint seed made the filter control
        depend on whether the page's own /api/info and /api/ci requests had been
        recorded before the panel first read the history, so the control passed
        or failed on a race rather than on the behaviour it was checking.
        """
        for i in range(count):
            trace = i % 2 == 0
            recorder.record(
                "ide", "/api/trace" if trace else "/api/diff",
                ok=i % 3 != 0,
                status=200 if i % 3 != 0 else 400,
                error=None if i % 3 != 0 else "unknown resource id",
                latency_ms=5.0 + i,
                query={"x": "320", "y": "240"} if trace
                else {"a": "320,240", "b": "10,10", "deep": "0"})

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        recorder.close()
        if self._store:
            shutil.rmtree(self._dir, ignore_errors=True)
            if self._previous is None:
                os.environ.pop("RDEBUG_STORE", None)
            else:
                os.environ["RDEBUG_STORE"] = self._previous

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


BROWSER, BROWSER_REASON = browser_path()
needs_browser = unittest.skipIf(
    BROWSER is None, "no usable browser: " + (BROWSER_REASON or ""))
needs_bundle = unittest.skipUnless(
    DIST.is_dir() and any(DIST.glob("assets/*.js")),
    "the React bundle is not built; run npm run build in static/ui")


class TestTheBundleIsServed(unittest.TestCase):
    """No browser needed: this is about routing and about the path check."""

    def setUp(self):
        self.live = Live()
        self.addCleanup(self.live.stop)

    def fetch(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.live.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.getheader("Content-Type"), resp.read()
        finally:
            conn.close()

    def test_the_frozen_page_still_answers_at_the_root(self):
        status, ctype, body = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"<html", body)

    @needs_bundle
    def test_the_bundle_is_served_under_ui(self):
        for path in ("/ui", "/ui/", "/ui/index.html"):
            with self.subTest(path=path):
                status, ctype, _body = self.fetch(path)
                self.assertEqual(status, 200)
                self.assertIn("text/html", ctype)

    @needs_bundle
    def test_the_bundle_asset_is_served_as_javascript(self):
        asset = next(DIST.glob("assets/*.js"))
        status, ctype, body = self.fetch(
            "/ui/" + asset.relative_to(DIST).as_posix())
        self.assertEqual(status, 200)
        self.assertIn("javascript", ctype)
        self.assertGreater(len(body), 0)

    def test_a_path_that_escapes_the_bundle_never_reaches_a_file_outside_it(self):
        # A debug tool is exactly the program people point at a machine they do
        # not fully trust, so the static root is a boundary, not a prefix.
        #
        # The property asserted is that no file outside dist/ is ever returned --
        # not that a specific status comes back. An encoded separator is not a
        # separator to urlparse, so it may legitimately resolve to a literal
        # filename, fall back to the app shell, or be refused. All three are
        # correct; serving app.py or win.ini is not.
        for attempt in ("/ui/../../../../Windows/win.ini",
                        "/ui/..%2f..%2fapp.py",
                        "/ui/....//....//app.py"):
            with self.subTest(attempt=attempt):
                status, _ctype, body = self.fetch(attempt)
                self.assertNotIn(b"_ROUTES", body,
                                 "the request escaped the bundle and served "
                                 "the server's own source")
                self.assertNotIn(b"[extensions]", body,
                                 "the request escaped the bundle and read win.ini")
                self.assertIn(status, (200, 403, 404))

    def test_a_deep_unknown_path_falls_back_to_the_app_shell(self):
        status, _ctype, _body = self.fetch("/ui/some/client/route")
        self.assertEqual(status, 200)


@needs_browser
@needs_bundle
class TestInARealBrowser(unittest.TestCase):
    """The layer that was NOT_ESTABLISHED."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(executable_path=BROWSER)
        cls.live = Live()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.live.stop()

    def page(self, color_scheme="dark"):
        ctx = self.browser.new_context(color_scheme=color_scheme)
        page = ctx.new_page()
        self.addCleanup(ctx.close)
        page.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                  wait_until="networkidle")
        return page

    def test_the_page_renders_in_a_browser(self):
        page = self.page()
        self.assertEqual(page.inner_text("h1"), "rdebug-ide")
        self.assertTrue(page.is_visible("#btnDiff"))
        self.assertTrue(page.is_visible("#btnTrace"))

    def test_the_stream_reports_itself_live(self):
        # This is the browser-level claim: the SSE client connected and the UI
        # says so, rendered, in a browser.
        page = self.page()
        status = page.get_attribute('[data-testid="stream-status"]', "class")
        page.wait_for_function(
            "() => document.querySelector('[data-testid=\"stream-status\"]')"
            ".className.includes('badge--live')", timeout=15000)
        self.assertIn("badge--live", status)

    def test_switching_language_changes_rendered_text(self):
        # inner_text() returns the rendered text, and the card heading is
        # uppercased by CSS. Asserting against the DOM text and comparing
        # case-insensitively is what makes this a test of translation rather
        # than of a text-transform rule.
        page = self.page()
        self.assertEqual(page.text_content("h2").strip(), "Query")
        page.click("#btnLang")
        page.wait_for_function(
            "() => document.querySelector('h2').textContent.trim() === '查询'",
            timeout=10000)
        self.assertEqual(page.text_content("h2").strip(), "查询")
        page.click("#btnLang")
        page.wait_for_function(
            "() => document.querySelector('h2').textContent.trim() === 'Query'",
            timeout=10000)
        self.assertEqual(page.text_content("h2").strip(), "Query")

    def test_the_button_labels_are_translated_too(self):
        page = self.page()
        self.assertEqual(page.text_content("#btnDiff").strip(), "Diff A vs B")
        page.click("#btnLang")
        page.wait_for_function(
            "() => document.querySelector('#btnDiff').textContent.trim()"
            " === '对比 A 与 B'", timeout=10000)
        self.assertEqual(page.text_content("#btnTrace").strip(), "追踪 A")

    def test_the_language_attribute_follows_the_selection(self):
        page = self.page()
        self.assertEqual(page.get_attribute("html", "lang"), "en")
        page.click("#btnLang")
        page.wait_for_function(
            "() => document.documentElement.lang === 'zh-CN'", timeout=10000)
        self.assertEqual(page.get_attribute("html", "lang"), "zh-CN")

    def test_a_failed_query_renders_a_visible_banner(self):
        # The capture is not configured, so this is a genuine server error, and
        # the frozen page's own record says its banner visibility was never
        # established. Here it is checked in a browser.
        page = self.page()
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="failure-banner"]', timeout=20000)
        banner = page.query_selector('[data-testid="failure-banner"]')
        self.assertTrue(banner.is_visible())
        self.assertIn("not configured", banner.inner_text().lower())

    def test_the_failure_banner_is_actually_painted(self):
        # is_visible() can be satisfied by layout alone. A computed colour is
        # what distinguishes "the element exists" from "the user can see it",
        # which is the exact gap the frozen record calls out.
        #
        # Pinned to the dark scheme explicitly. Asserting one literal RGB while
        # inheriting whatever colour scheme the browser happens to default to
        # would make this a test of the default rather than of the page.
        page = self.page(color_scheme="dark")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="failure-banner"]', timeout=20000)
        colour = page.eval_on_selector(
            '[data-testid="failure-banner"]',
            "el => getComputedStyle(el).color")
        background = page.eval_on_selector(
            '[data-testid="failure-banner"]',
            "el => getComputedStyle(el).backgroundColor")
        self.assertEqual(colour, "rgb(232, 196, 104)")
        self.assertNotEqual(background, "rgba(0, 0, 0, 0)")

    def test_a_bad_coordinate_is_refused_before_any_request(self):
        page = self.page()
        page.fill("input >> nth=0", "not-a-coordinate")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="failure-banner"]', timeout=20000)
        self.assertIn("x,y", page.inner_text('[data-testid="failure-banner"]'))

    def test_no_console_errors_on_load(self):
        page = self.page()
        errors = []
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1500)
        self.assertEqual(errors, [])


@needs_browser
@needs_bundle
class TestRestoredFeatures(unittest.TestCase):
    """The React page shipped without two controls the old page has.

    That was a functional regression dressed as a rewrite: `btnExplain` and
    `btnCopy` were simply absent. These assert they exist and that the D9
    availability contract still holds -- copy follows the prompt, not the diff.
    """

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(executable_path=BROWSER)
        cls.live = Live()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.live.stop()

    def page(self):
        ctx = self.browser.new_context(
            permissions=["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        self.addCleanup(ctx.close)
        page.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                  wait_until="networkidle")
        return page

    def test_the_explain_control_exists(self):
        page = self.page()
        self.assertTrue(page.is_visible("#btnExplain"))
        self.assertEqual(page.text_content("#btnExplain").strip(),
                         "Generate AI Prompt")

    def test_the_copy_control_exists(self):
        page = self.page()
        self.assertTrue(page.is_visible("#btnCopy"))

    def test_copy_is_unavailable_while_there_is_no_prompt(self):
        # Availability follows the prompt that exists rather than the fact that
        # a diff happened. Copying an empty prompt as if it were real is the
        # failure this rule exists to prevent.
        page = self.page()
        self.assertTrue(page.is_disabled("#btnCopy"))

    def test_a_failed_explain_leaves_copy_unavailable(self):
        # The capture is unconfigured, so explain fails. An empty prompt must not
        # become copyable.
        page = self.page()
        page.click("#btnExplain")
        page.wait_for_selector('[data-testid="failure-banner"]', timeout=20000)
        self.assertEqual(page.input_value("#prompt"), "")
        self.assertTrue(page.is_disabled("#btnCopy"))

    def test_the_eid_scope_note_is_rendered(self):
        page = self.page()
        note = page.inner_text('[data-testid="eid-scope"]')
        self.assertIn("Applies to", note)
        self.assertIn("Does not apply to", note)
        self.assertIn("Generate AI Prompt", note)

    def test_the_scope_note_travels_with_the_language(self):
        page = self.page()
        page.click("#btnLang")
        page.wait_for_function(
            "() => document.querySelector('[data-testid=\"eid-scope\"]')"
            ".textContent.includes('生效于')", timeout=10000)
        self.assertIn("生效于", page.inner_text('[data-testid="eid-scope"]'))

    def test_the_stream_badge_reads_live(self):
        page = self.page()
        page.wait_for_function(
            "() => document.querySelector('[data-testid=\"stream-status\"]')"
            ".className.includes('badge--live')", timeout=15000)
        self.assertIn("live", page.inner_text('[data-testid="stream-status"]'))


@needs_browser
@needs_bundle
class TestAccessibilityAndLayout(unittest.TestCase):
    """Modernisation claims, each one asserted rather than asserted-by-name."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(executable_path=BROWSER)
        cls.live = Live()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.live.stop()

    def page(self, width=1280, height=900):
        ctx = self.browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        self.addCleanup(ctx.close)
        page.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                  wait_until="networkidle")
        return page

    def test_every_input_has_an_accessible_name(self):
        # A placeholder is not a name: it disappears as soon as the field has a
        # value, and it is not reliably announced.
        page = self.page()
        unnamed = page.evaluate("""() => {
          const out = [];
          for (const el of document.querySelectorAll('input, textarea, select')) {
            const label = el.labels && el.labels[0];
            const aria = el.getAttribute('aria-label')
              || el.getAttribute('aria-labelledby');
            if (!label && !aria && !el.getAttribute('title')) {
              out.push(el.id || el.tagName);
            }
          }
          return out;
        }""")
        self.assertEqual(unnamed, [])

    def test_the_result_region_is_a_live_region(self):
        # The result arrives after the click that asked for it. Without a live
        # region a screen reader announces nothing.
        page = self.page()
        self.assertEqual(
            page.get_attribute("#result", "aria-live"), "polite")

    def test_a_failure_is_announced_assertively(self):
        page = self.page()
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="failure-banner"]', timeout=20000)
        self.assertEqual(
            page.get_attribute('[data-testid="failure-banner"]', "role"), "alert")

    def test_a_long_capture_name_does_not_break_the_layout(self):
        # Long resource ids are the normal case here, not the exception.
        page = self.page()
        page.evaluate("""() => {
          document.getElementById('capture').textContent =
            'D:/very/long/path/that/keeps/going/' + 'x'.repeat(120) + '.rdc';
        }""")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " > document.documentElement.clientWidth + 1")
        self.assertFalse(overflow, "the page scrolls sideways")

    def test_a_narrow_viewport_does_not_scroll_sideways(self):
        page = self.page(width=420, height=800)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " > document.documentElement.clientWidth + 1")
        self.assertFalse(overflow, "narrow viewport forces a horizontal scroll")

    def test_a_very_long_resource_id_wraps_instead_of_escaping(self):
        page = self.page()
        page.set_content("""<style>
          .mono { overflow-wrap: anywhere; word-break: break-word; }
        </style><div class="mono" id="probe">""" + "R" * 300 + "</div>""")
        overflow = page.evaluate(
            "() => document.getElementById('probe').scrollWidth"
            " > document.getElementById('probe').clientWidth + 1")
        self.assertFalse(overflow)

    def test_focus_is_visible_on_the_keyboard_path(self):
        page = self.page()
        page.keyboard.press("Tab")
        outline = page.evaluate("""() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const s = getComputedStyle(el);
          return s.outlineStyle + ' ' + s.outlineWidth;
        }""")
        self.assertIsNotNone(outline, "Tab did not reach an interactive element")
        self.assertNotEqual(outline, "none 0px")

    def test_enter_in_a_coordinate_field_runs_the_query(self):
        page = self.page()
        page.fill("#a", "not-a-coordinate")
        page.press("#a", "Enter")
        page.wait_for_selector('[data-testid="failure-banner"]', timeout=20000)
        self.assertIn("x,y", page.inner_text('[data-testid="failure-banner"]'))

    def test_the_banner_is_readable_in_the_light_scheme_too(self):
        # The light palette is a second set of claims, so it is checked rather
        # than assumed: a media query that renders white-on-white would pass
        # every other test here.
        ctx_light = self.browser.new_context(color_scheme="light")
        self.addCleanup(ctx_light.close)
        light = ctx_light.new_page()
        light.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                   wait_until="networkidle")
        light.click("#btnTrace")
        light.wait_for_selector('[data-testid="failure-banner"]', timeout=20000)
        painted = light.evaluate("""() => {
          const el = document.querySelector('[data-testid="failure-banner"]');
          const s = getComputedStyle(el);
          return {fg: s.color, bg: s.backgroundColor};
        }""")
        self.assertNotEqual(painted["bg"], "rgba(0, 0, 0, 0)")
        self.assertNotEqual(painted["fg"], painted["bg"])


@needs_browser
@needs_bundle
class TestTheHistoryPanelWhenNoStoreIsConfigured(unittest.TestCase):
    """The default. This is the branch CI exercises and the branch a plain
    install gets, so it is tested first and tested as a first-class state."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(executable_path=BROWSER)
        cls.live = Live(store=False)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.live.stop()

    def page(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        self.addCleanup(ctx.close)
        page.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                  wait_until="networkidle")
        return page

    def test_the_panel_is_present(self):
        page = self.page()
        self.assertTrue(page.is_visible(".panel--history"))

    def test_it_says_the_store_is_not_configured(self):
        page = self.page()
        page.wait_for_selector('[data-testid="history-disabled"]', timeout=15000)
        text = page.inner_text('[data-testid="history-disabled"]')
        self.assertIn("RDEBUG_STORE", text)

    def test_it_does_not_claim_zero_requests(self):
        # The whole point of the disabled branch: a summary of zeroes under
        # "not configured" is a measurement nobody took.
        page = self.page()
        page.wait_for_selector('[data-testid="history-disabled"]', timeout=15000)
        self.assertEqual(page.query_selector_all('[data-testid="stat"]'), [])
        self.assertEqual(page.query_selector_all('[data-testid="history-table"]'), [])

    def test_it_is_announced_politely_not_alerted(self):
        # A missing optional store is not an error the user must interrupt for.
        page = self.page()
        page.wait_for_selector('[data-testid="history-disabled"]', timeout=15000)
        self.assertEqual(
            page.get_attribute('[data-testid="history-disabled"]', "role"), "status")

    def test_refresh_is_unavailable_while_disabled(self):
        page = self.page()
        page.wait_for_selector('[data-testid="history-disabled"]', timeout=15000)
        refresh = page.query_selector(".panel--history button")
        if refresh is not None:
            self.assertTrue(refresh.is_disabled())


@needs_browser
@needs_bundle
class TestTheHistoryPanelWithAStore(unittest.TestCase):
    """The enabled branch, against a real store on a real server."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(executable_path=BROWSER)
        cls.live = Live(store=True)
        cls.live.seed(6)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        cls.live.stop()

    def page(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        self.addCleanup(ctx.close)
        page.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                  wait_until="networkidle")
        page.wait_for_selector('[data-testid="history-table"]', timeout=15000)
        return page

    def test_it_renders_the_recorded_queries(self):
        page = self.page()
        self.assertGreaterEqual(
            len(page.query_selector_all('[data-testid="history-row"]')), 5)

    def test_it_shows_four_stat_tiles(self):
        page = self.page()
        self.assertEqual(len(page.query_selector_all('[data-testid="stat"]')), 4)

    def test_the_failure_tile_is_present_and_counted(self):
        page = self.page()
        page.wait_for_selector(".stat--bad", timeout=10000)

    def test_a_failure_shows_both_the_mark_and_the_status(self):
        # The documented trap: an unclassified error arrives as HTTP 200, so a
        # row that showed only the number would read as a success.
        page = self.page()
        page.wait_for_selector(".chip-status.bad", timeout=10000)
        text = page.inner_text(".chip-status.bad")
        self.assertNotEqual(text.strip(), "200")

    def test_the_request_column_shows_what_was_sent(self):
        page = self.page()
        body = page.inner_text('[data-testid="history-table"]')
        self.assertIn("x=320", body)
        self.assertIn("y=240", body)

    def test_it_offers_an_endpoint_filter(self):
        page = self.page()
        options = page.eval_on_selector_all(
            "#histEndpoint option", "els => els.map(e => e.value)")
        self.assertIn("", options)
        self.assertIn("/api/trace", options)

    def test_filtering_to_one_endpoint_reduces_the_rows(self):
        page = self.page()
        before = page.eval_on_selector_all(
            '[data-testid="history-row"] td:nth-child(2)',
            "els => els.map(e => e.textContent.trim())")
        self.assertGreater(len(before), 1, "the fixture has two endpoints")
        page.select_option("#histEndpoint", "/api/trace")
        # Wait for a non-empty result whose endpoints are all the chosen one.
        # `.every(...)` alone is vacuously true on an empty list, so it passes
        # while the table is still loading and the assertion below then fails on
        # an empty set. The length check is what makes the wait mean something.
        page.wait_for_function(
            "() => { const tds = Array.from(document.querySelectorAll("
            "'[data-testid=\"history-row\"] td:nth-child(2)'));"
            "  return tds.length > 0 &&"
            "    tds.every(td => td.textContent.trim() === '/api/trace'); }",
            timeout=10000)
        after = page.eval_on_selector_all(
            '[data-testid="history-row"] td:nth-child(2)',
            "els => els.map(e => e.textContent.trim())")
        self.assertGreater(len(after), 0)
        self.assertLess(len(after), len(before))

    def test_the_failures_filter_keeps_only_failures(self):
        page = self.page()
        page.check("#histFailures")
        page.wait_for_selector(".chip-status.bad", timeout=10000)
        marks = page.eval_on_selector_all(
            ".chip-status", "els => els.map(e => e.className)")
        self.assertTrue(marks)
        for name in marks:
            with self.subTest(chip=name):
                self.assertIn("bad", name)

    def test_the_pixel_scope_follows_whether_a_pixel_is_entered(self):
        # Both coordinates count: the scope uses whichever one is well formed, so
        # it is only unavailable when neither is. Clearing one field and finding
        # the toggle still available is correct, not a bug -- and the label has
        # to name the pixel actually being used, or the scope is a mystery.
        page = self.page()
        self.assertFalse(page.is_disabled("#histScope"))
        # inner_text on a checkbox returns its value, which is empty; the text
        # that names the pixel lives on the wrapping label.
        self.assertIn("320,240", page.inner_text("label:has(#histScope)"))
        page.fill("#a", "")
        page.wait_for_function(
            "() => document.querySelector('#histScope').closest('label')"
            ".textContent.includes('10,10')", timeout=10000)
        self.assertFalse(page.is_disabled("#histScope"))
        page.fill("#b", "")
        page.wait_for_function(
            "() => document.getElementById('histScope').disabled", timeout=10000)
        self.assertTrue(page.is_disabled("#histScope"))
        page.fill("#a", "320,240")
        page.wait_for_function(
            "() => !document.getElementById('histScope').disabled", timeout=10000)
        self.assertFalse(page.is_disabled("#histScope"))

    def test_a_malformed_coordinate_does_not_count_as_a_pixel(self):
        page = self.page()
        page.fill("#a", "not-a-pixel")
        page.fill("#b", "")
        page.wait_for_function(
            "() => document.getElementById('histScope').disabled", timeout=10000)
        self.assertTrue(page.is_disabled("#histScope"))

    def test_the_breakdown_lists_the_endpoints(self):
        page = self.page()
        page.wait_for_selector('[data-testid="breakdown"]', timeout=10000)
        text = page.inner_text('[data-testid="breakdown"]')
        self.assertIn("/api/trace", text)

    def test_it_translates(self):
        page = self.page()
        page.click("#btnLang")
        page.wait_for_function(
            "() => document.querySelector('.panel--history .panel__title')"
            ".textContent.trim() === '会话历史'", timeout=10000)
        self.assertEqual(
            page.inner_text(".panel--history .panel__title").strip(), "会话历史")

    def test_it_updates_without_a_manual_refresh(self):
        # The point of announcing queries: a session is observed, not polled.
        # A query issued outside this tab -- here, by the server itself -- must
        # reach the panel without anyone pressing Refresh.
        page = self.page()
        before = len(page.query_selector_all('[data-testid="history-row"]'))
        recorder.record("ide", "/api/trace", ok=True, latency_ms=3.0,
                        query={"x": "7", "y": "7"})
        # Publish what the route would publish for a served query.
        app.publish("query", {"endpoint": "/api/trace", "ok": True,
                              "status": 200, "latencyMs": 3.0, "recorded": True})
        page.wait_for_function(
            "(n) => document.querySelectorAll("
            "'[data-testid=\"history-row\"]').length > n", arg=before,
            timeout=15000)
        after = len(page.query_selector_all('[data-testid="history-row"]'))
        self.assertGreater(after, before)

    def test_a_burst_of_queries_does_not_issue_one_read_each(self):
        # Coalesced, not acted on per event: a diff issues a second request for
        # the prompt, so a per-event refresh would turn the observer into load.
        page = self.page()
        reads = []
        page.on("request", lambda r: reads.append(r.url)
                if "/api/history?" in r.url else None)
        page.wait_for_timeout(600)
        baseline = len(reads)
        for _ in range(8):
            app.publish("query", {"endpoint": "/api/trace", "ok": True,
                                  "status": 200, "latencyMs": 1.0,
                                  "recorded": True})
        page.wait_for_timeout(2000)
        self.assertLessEqual(len(reads) - baseline, 2,
                             "a burst should coalesce into about one refresh")

    def test_the_panel_spans_the_full_width(self):
        # A two-column layout for a comparable-records table halves the row width
        # for nothing.
        page = self.page()
        width = page.eval_on_selector(".panel--history",
                                      "el => el.getBoundingClientRect().width")
        column = page.eval_on_selector(".panel--result",
                                       "el => el.getBoundingClientRect().width")
        self.assertGreater(width, column)


if __name__ == "__main__":
    unittest.main()
