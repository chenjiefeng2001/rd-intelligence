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
import json
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


def _probe_can_launch(_executable):
    """Can Playwright actually start a browser right now?

    Answered by launching one and closing it, because "Playwright is installed"
    and "Playwright has a browser" are different facts. A machine with the
    package but no downloaded Chromium raises on launch, and a launch failure
    inside setUpClass reads as a test error rather than as the skip it is.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=_executable)
        browser.close()
    return None


def browser_path(candidates=CHROME_CANDIDATES, has_playwright=None, probe=None):
    """The executable to drive, and why the controls cannot run if there is none.

    Three outcomes, because "no browser" and "no *system* browser" are different
    problems. Playwright brings and downloads its own Chromium, so a machine
    with no Chrome at any of these Windows paths can still run every control.
    Treating that case as "no browser" is what made the suite skip on a Linux
    runner no matter what CI installed -- and it hid the fact that installing
    Playwright was never the whole job.

    A hardcoded system browser still wins when one is present: it is a
    known-good browser, and quietly switching to a downloaded one would change
    what the controls have already been verified against.

    The parameters exist so the decision can be tested without launching
    anything. This function decides whether 62 controls are skipped, and a skip
    that cannot be exercised is a skip nobody notices is wrong.
    """
    if has_playwright is None:
        # Probed with find_spec rather than by importing: an import here would
        # pull in the driver at collection time, and a suppression would then
        # be needed to keep the reason attached to it.
        has_playwright = importlib.util.find_spec("playwright") is not None
    if not has_playwright:
        return None, "playwright is not installed"

    for candidate in candidates:
        if pathlib.Path(candidate).is_file():
            return candidate, None

    if probe is None:
        probe = _probe_can_launch
    try:
        probe(None)
    except Exception as exc:  # noqa: BLE001 -- the reason is the useful part
        first = str(exc).strip().splitlines()
        return None, ("no usable browser: playwright is installed but could"
                      " not launch one (" + (first[0][:140] if first else "?")
                      + ")")
    # None means "let Playwright choose", which is the documented default.
    return None, None


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


def _browser_unavailable(executable, reason):
    """Whether the controls cannot run at all.

    Named and separate from `browser_path()` because this predicate is what
    actually decides the skip, and it is the one piece of the arrangement with
    no control over it: key it on the executable instead of the reason and every
    control silently disables itself on any machine without a system Chrome --
    which is what happened before, and what made the suite green while testing
    nothing.
    """
    return reason is not None


BROWSER, BROWSER_REASON = browser_path()
needs_browser = unittest.skipIf(
    _browser_unavailable(BROWSER, BROWSER_REASON),
    "no usable browser: " + (BROWSER_REASON or ""))
needs_bundle = unittest.skipUnless(
    DIST.is_dir() and any(DIST.glob("assets/*.js")),
    "the React bundle is not built; run npm run build in static/ui")


class TestHowTheBrowserIsChosen(unittest.TestCase):
    """The decision that decides whether 62 controls are skipped.

    Exercised with injected candidates and probes, so none of it launches a
    browser. This is harness logic, and harness logic that can only be observed
    by running the whole suite against a real browser is exactly the logic that
    rots unnoticed -- the failure mode is a green suite that quietly stopped
    testing anything.
    """

    def test_a_missing_playwright_is_the_only_hard_stop(self):
        path, reason = browser_path(has_playwright=False)
        self.assertIsNone(path)
        self.assertIn("playwright is not installed", reason)

    def test_an_installed_system_browser_is_preferred(self):
        # A known-good browser wins over a downloaded one, because switching
        # silently would change what the controls were verified against.
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as fh:
            fake = fh.name
        self.addCleanup(os.unlink, fake)
        path, reason = browser_path(candidates=(fake,), has_playwright=True,
                                    probe=lambda _p: self.fail(
                                        "must not probe when a browser exists"))
        self.assertEqual(path, fake)
        self.assertIsNone(reason)

    def test_no_system_browser_falls_back_instead_of_skipping(self):
        # The behaviour this change exists for. Before it, a machine with no
        # Chrome at the hardcoded Windows paths reported "no installed Chrome or
        # Edge" and every control skipped -- so installing Playwright in CI was
        # never sufficient to make them run.
        probes = []

        def probe(executable):
            probes.append(executable)

        path, reason = browser_path(candidates=(), has_playwright=True,
                                    probe=probe)
        self.assertIsNone(path, "None means: let Playwright choose")
        self.assertIsNone(reason, "no reason means nothing is wrong")
        self.assertEqual(probes, [None], "the fallback must be probed once")

    def test_a_probe_failure_skips_and_says_why(self):
        # Playwright being installed is not the same as Playwright having a
        # browser. Without this, a runner with the package but no downloaded
        # Chromium raises inside setUpClass and reads as a test error rather
        # than as the skip it is.
        def probe(_executable):
            raise RuntimeError("Executable doesn't exist at C:\\missing\\chrome")

        path, reason = browser_path(candidates=(), has_playwright=True,
                                    probe=probe)
        self.assertIsNone(path)
        self.assertIsNotNone(reason)
        self.assertIn("could not launch", reason)
        self.assertIn("Executable doesn't exist", reason)

    def test_the_skip_keys_on_the_reason_not_on_the_executable(self):
        # The one predicate that decides whether these controls run at all.
        # Three cases, and the middle one is the entire point of the change.
        self.assertFalse(_browser_unavailable("C:/chrome.exe", None),
                         "a system browser must run")
        self.assertFalse(_browser_unavailable(None, None),
                         "no executable with no reason means Playwright's own"
                         " browser will be used, so this must NOT skip")
        self.assertTrue(_browser_unavailable(None, "no usable browser: x"))

    def test_this_machine_takes_the_system_browser_path(self):
        # Not a portability claim: a statement that the change did not alter
        # behaviour where a system browser exists. A silent switch to a
        # downloaded browser would change what the controls were verified
        # against without anything saying so.
        if not any(pathlib.Path(c).is_file() for c in CHROME_CANDIDATES):
            self.skipTest("no system browser here; the fallback is exercised")
        self.assertIsNotNone(BROWSER)
        self.assertIsNone(BROWSER_REASON)
        self.assertFalse(_browser_unavailable(BROWSER, BROWSER_REASON))

    def test_the_windows_paths_are_all_unreachable_on_this_platform(self):
        # Not a portability claim -- a statement of what the fallback exists for.
        # If these ever did resolve on a non-Windows runner, the fallback would
        # stop being exercised and the controls would silently change browser.
        import sys

        if sys.platform.startswith("win"):
            self.skipTest("this assertion describes a non-Windows runner")
        for candidate in CHROME_CANDIDATES:
            self.assertFalse(pathlib.Path(candidate).is_file(), candidate)


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


class TestTheEvidenceChainAndServerLog(unittest.TestCase):
    """The two observing panels, on a server with no capture configured.

    Unconfigured on purpose: a query then returns a real error body, so this
    covers the states that are hardest to reach on a working server -- a failed
    query, and the question of what the chain shows after one. The chain against
    real replay data is a separate class below.
    """

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(executable_path=BROWSER)
        cls.live = Live(store=True)

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

    # ------------------------------------------------------------------ log --

    def test_the_log_panel_is_present_before_anything_happens(self):
        page = self.page()
        self.assertEqual(len(page.query_selector_all('[data-testid="log"]')), 1)

    def test_a_query_is_recorded_in_the_log_when_it_fails(self):
        # Failures included on purpose. A log that only records successes is
        # exactly backwards for a tool whose job is finding out what went wrong.
        page = self.page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="log-row"]', timeout=15000)
        kinds = page.eval_on_selector_all(
            '[data-testid="log-row"] .log__kind', "els => els.map(e => e.textContent)")
        self.assertIn("query", kinds)

    def test_the_log_says_when_a_query_failed(self):
        page = self.page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="log-row"]', timeout=15000)
        text = page.inner_text('[data-testid="log"]')
        self.assertIn("/api/trace", text)
        self.assertIn("400", text)

    def test_newest_entries_come_first(self):
        # Newest-first rather than auto-scrolling: a log that scrolls itself
        # needs scroll state that fights the reader, and newest-first needs none.
        page = self.page()
        for xy in ("320,240", "10,10", "100,100"):
            page.fill("#a", xy)
            page.click("#btnTrace")
            page.wait_for_timeout(700)
        rows = page.eval_on_selector_all(
            '[data-testid="log-row"] .log__rev',
            "els => els.map(e => parseInt(e.textContent.slice(1), 10))")
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows, sorted(rows, reverse=True))

    def test_the_filter_narrows_the_rows(self):
        page = self.page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="log-row"]', timeout=15000)
        page.select_option("#logFilter", "lifecycle")
        page.wait_for_timeout(300)
        kinds = page.eval_on_selector_all(
            '[data-testid="log-row"] .log__kind',
            "els => els.map(e => e.textContent)")
        self.assertNotIn("query", kinds)

    def test_clearing_empties_the_log(self):
        page = self.page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="log-row"]', timeout=15000)
        page.click("#btnLogClear")
        page.wait_for_timeout(300)
        self.assertEqual(
            len(page.query_selector_all('[data-testid="log-row"]')), 0)

    def test_the_log_states_how_many_entries_it_holds(self):
        # A bounded list that does not say it is bounded looks like an idle
        # server once the oldest entries have fallen off.
        page = self.page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_selector('[data-testid="log-row"]', timeout=15000)
        self.assertRegex(page.inner_text('[data-testid="log-foot"]'),
                         r"\d+")

    # ---------------------------------------------------------------- chain --

    def test_the_chain_panel_is_present(self):
        page = self.page()
        self.assertEqual(len(page.query_selector_all('[data-testid="chain"]')), 1)

    def test_a_failed_query_shows_no_chain_rather_than_the_previous_one(self):
        # Showing the last successful chain here would be the worst possible
        # answer: it looks like reasoning about this query and is about another.
        page = self.page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_timeout(1200)
        text = page.inner_text('[data-testid="chain"]').lower()
        self.assertNotIn("first difference", text)
        self.assertNotIn("divergence", text)
        self.assertTrue(text.strip())

    def test_the_chain_is_empty_before_any_query(self):
        page = self.page()
        self.assertEqual(
            len(page.query_selector_all('[data-testid="chain-step"]')), 0)

    # --------------------------------------------------------------- layout --

    def test_no_panel_overflows_its_own_box(self):
        # Each panel contains its own content. A panel wider than its own box
        # means a child escaped it, and the sibling layout inherits the problem.
        page = self.page()
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_timeout(1200)
        bad = page.evaluate("""() => {
          const out = [];
          for (const el of document.querySelectorAll('.panel')) {
            if (el.scrollWidth > el.clientWidth + 1) {
              out.push(el.className + ' scroll=' + el.scrollWidth
                       + ' client=' + el.clientWidth);
            }
          }
          return out;
        }""")
        self.assertEqual(bad, [])

    def test_the_growing_log_scrolls_inside_itself(self):
        # The rule that keeps one panel from pushing the rest of the page: the
        # list has a capped height and its own scrollbar.
        page = self.page()
        box = page.eval_on_selector(
            '[data-testid="log-list"]',
            "el => { const s = getComputedStyle(el);"
            " return { oy: s.overflowY, max: s.maxHeight }; }")
        self.assertEqual(box["oy"], "auto")
        self.assertNotEqual(box["max"], "none")

    def test_the_page_never_scrolls_sideways_at_any_width(self):
        for width in (1440, 1280, 1024, 860, 720, 480):
            with self.subTest(width=width):
                page = self.page(width=width)
                page.fill("#a", "320,240")
                page.click("#btnTrace")
                page.wait_for_timeout(900)
                overflow = page.evaluate(
                    "() => document.documentElement.scrollWidth"
                    " - document.documentElement.clientWidth")
                self.assertLessEqual(overflow, 0)

    def test_exactly_one_panel_is_elevated(self):
        # Visual focus is a property of the rendered page, not of a class name:
        # if two panels are styled apart there is no focal point at all.
        #
        # The signature is background + shadow + border together, because
        # background alone does not carry elevation in both schemes -- in the
        # light palette --panel and --bg-elev are both #ffffff, so the raised
        # panel is distinguished by its shadow and border instead. Asserting on
        # one channel would have passed in one scheme and silently stopped
        # testing anything in the other.
        for scheme in ("light", "dark"):
            with self.subTest(scheme=scheme):
                ctx = self.browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    color_scheme=scheme)
                page = ctx.new_page()
                self.addCleanup(ctx.close)
                page.goto("http://127.0.0.1:" + str(self.live.port) + "/ui/",
                          wait_until="networkidle")
                page.fill("#a", "320,240")
                page.click("#btnTrace")
                page.wait_for_timeout(900)
                counts = page.evaluate("""() => {
                  const sig = (p) => {
                    const s = getComputedStyle(p);
                    return [s.backgroundColor, s.boxShadow,
                            s.borderTopColor].join('|');
                  };
                  const tally = {};
                  for (const p of document.querySelectorAll('.panel')) {
                    const k = sig(p);
                    tally[k] = (tally[k] || 0) + 1;
                  }
                  const n = document.querySelectorAll('.panel').length;
                  const modal = Math.max(...Object.values(tally));
                  // How many panels are NOT part of the largest identical group.
                  return { apart: n - modal, total: n };
                }""")
                self.assertEqual(
                    counts["apart"], 1,
                    "expected one focal panel out of "
                    + str(counts["total"]))

    def test_opening_a_resource_does_not_blank_the_page(self):
        # A regression control for a real crash. `/api/resource` answers with a
        # `summary` but no `edges` and no `layers`, so the two-shape dispatch
        # sent it to the diff view, which read `data.layers.map` and threw.
        # React unmounts the tree on an uncaught render error, so every
        # resource id on the page -- the evidence chips included -- blanked the
        # whole app. Asserted on the symptom: the page is still there.
        page = self.page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # Drive the same code path without needing a configured capture: the
        # fetch is stubbed, so this asserts the renderer's tolerance of the
        # shape rather than the replay runtime's ability to produce it.
        page.route(
            "**/api/resource*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "resource": "ResourceId::47",
                    "contextEventId": 11,
                    "writers": [{"eventId": 2, "usage": "CopyDst", "kind": "write",
                                 "actionName": "", "evidence": []}],
                    "readers": [{"eventId": 11, "usage": "PS_Resource",
                                 "kind": "read", "actionName": "",
                                 "evidence": []}],
                    "other": [],
                    "summary": {"usageCount": 2, "writerCount": 1,
                                "readerCount": 1, "otherCount": 0},
                    "evidence": [],
                })))
        page.fill("#a", "320,240")
        page.click("#btnTrace")
        page.wait_for_timeout(800)
        page.evaluate("""() => {
          const btn = document.querySelector('.chip');
          if (btn) btn.click();
        }""")
        page.wait_for_timeout(600)
        self.assertEqual(errors, [], "the page threw while rendering")
        self.assertEqual(
            len(page.query_selector_all('[data-testid="result"]')), 1,
            "the result region must survive an unfamiliar payload shape")

    def test_the_focal_panel_is_the_result(self):
        page = self.page()
        ctx_bg = {}
        for sel in (".panel--result", ".panel--query", ".panel--chain",
                    ".panel--log", ".panel--history", ".panel--evidence"):
            ctx_bg[sel] = page.eval_on_selector(
                sel, "el => getComputedStyle(el).boxShadow")
        distinct = {v for v in ctx_bg.values()}
        self.assertEqual(len(distinct), 2,
                         "the result panel must not share its elevation")
        self.assertNotEqual(ctx_bg[".panel--result"], ctx_bg[".panel--chain"])
        self.assertEqual(ctx_bg[".panel--chain"], ctx_bg[".panel--log"])

    def test_the_query_rail_is_elastic_rather_than_fixed(self):
        # A rail pinned to one width stops being a rail on a wide screen. It has
        # to grow and shrink with the viewport, within its declared bounds.
        widths = {}
        for width in (1440, 1100):
            page = self.page(width=width)
            widths[width] = page.eval_on_selector(
                ".panel--query", "el => Math.round(el.getBoundingClientRect().width)")
        self.assertLess(widths[1440], widths[1100] + 1)
        self.assertLessEqual(widths[1440], 24 * 16 + 2)
        self.assertGreaterEqual(widths[1100], 260 - 2)


def _real_replay_ready():
    if not os.environ.get("RDEBUG_INTEGRATION_CAPTURE"):
        return False
    try:
        from rdebug.adapter.locator import find_module_dir
    except Exception:
        return False
    return find_module_dir() is not None


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
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(executable_path=BROWSER)
        cls.live = Live(store=False)
        cls.capture = os.environ["RDEBUG_INTEGRATION_CAPTURE"]
        try:
            app.configure(cls.capture)
        except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
            cls.browser.close()
            cls._pw.stop()
            cls.live.stop()
            raise unittest.SkipTest(
                "configure(" + str(cls.capture) + ") failed: " + str(exc)) from exc

    @classmethod
    def tearDownClass(cls):
        app.dispose()
        cls.browser.close()
        cls._pw.stop()
        cls.live.stop()

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
