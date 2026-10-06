"""Controls for the design claims.

A redesign that is only asserted by reading the source is an opinion. These
check the specific properties that were claimed: one primary action, a visible
elevation difference between the focal panel and the others, a loading state
that is distinguishable from an empty result, real interaction feedback, and
component boundaries that are actually component boundaries rather than one file
that happens to render everything.

They are structural rather than photographic. A pixel-diff against a stored
screenshot would fail on a font hinting change and pass on a layout that is
visually wrong, which is the opposite of useful.
"""
import pathlib
import re
import unittest

UI = pathlib.Path(__file__).resolve().parent.parent.parent / (
    "src/rdebug_ide/static/ui")
SRC = UI / "src"


def read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


class TestComponentBoundaries(unittest.TestCase):
    """The page is split, and the split is real."""

    def test_the_entry_point_only_mounts(self):
        main = read("main.jsx")
        self.assertIn("createRoot", main)
        self.assertNotIn("useState", main, "state belongs in App")
        self.assertNotIn("fetch(", main, "networking belongs in api.js")
        self.assertLess(len(main.splitlines()), 20,
                        "the entry point grew; logic is leaking into it")

    def test_the_page_is_split_into_components(self):
        for rel in ("App.jsx",
                    "components/primitives.jsx",
                    "panels/QueryPanel.jsx",
                    "panels/EvidencePanel.jsx",
                    "views/ResultPanel.jsx",
                    "api.js",
                    "useEventStream.js",
                    "i18n.js"):
            with self.subTest(module=rel):
                self.assertTrue((SRC / rel).is_file(), rel)

    def test_app_composes_rather_than_implementing(self):
        app = read("App.jsx")
        for component in ("QueryPanel", "ResultPanel", "EvidencePanel",
                          "TopBar", "StatusBar"):
            with self.subTest(component=component):
                self.assertIn(component, app)
        # Markup belongs in the panels. A JSX element in App means a panel was
        # inlined, which is how a 500-line file comes back.
        self.assertNotIn("<section", app)
        self.assertNotIn("<textarea", app)

    def test_no_module_is_a_second_page(self):
        # Guards against the split becoming duplication: only App holds state
        # that spans panels.
        for rel in ("panels/QueryPanel.jsx", "panels/EvidencePanel.jsx",
                    "panels/HistoryPanel.jsx", "views/ResultPanel.jsx",
                    "components/primitives.jsx", "components/display.jsx"):
            with self.subTest(module=rel):
                self.assertNotIn("useState(", read(rel),
                                 rel + " holds state; it should be a view")

    def test_the_primitives_are_the_only_place_a_button_is_styled(self):
        css = read("styles.css")
        button_rules = re.findall(r"^\.btn[\s,{:]", css, re.M)
        self.assertTrue(button_rules)
        for rel in ("panels/QueryPanel.jsx", "panels/EvidencePanel.jsx"):
            with self.subTest(module=rel):
                self.assertNotIn("className=\"btn ", read(rel),
                                 "use the Button primitive, not a bare class")


class TestVisualHierarchy(unittest.TestCase):
    """One primary action, and one focal panel."""

    def test_exactly_one_primary_action(self):
        # Read every panel, including the history panel: a control added to the
        # newest panel is exactly where a second "primary" would appear.
        panels = "".join(read(rel) for rel in (
            "panels/QueryPanel.jsx", "panels/EvidencePanel.jsx",
            "panels/HistoryPanel.jsx", "views/ResultPanel.jsx",
            "components/primitives.jsx"))
        # Counted as a prop, not as a word: the prose in the panels explains what
        # primary means, and a substring count would trip over its own comment.
        used = re.findall(r"<Button[^>]*\bprimary\b", panels)
        self.assertEqual(len(used), 1,
                         "one filled control per view; more is not a hierarchy")

    def test_the_diff_control_is_the_primary_one(self):
        panel = read("panels/QueryPanel.jsx")
        self.assertRegex(
            panel, r'primary[^>]*>\s*\{t\("b", "diff"\)\}',
            "the filled button should be the action the page exists for")

    def test_the_result_panel_is_elevated_above_the_others(self):
        css = read("styles.css")
        self.assertIn(".panel--result", css)
        # Split on the declaration, not the substring: the grid-area rule mentions
        # .panel--result first and carries none of the styling.
        result_block = css.split("\n.panel--result {", 1)[1].split("}", 1)[0]
        self.assertIn("box-shadow", result_block,
                      "the focal panel is distinguished by elevation")
        self.assertIn("--shadow-2", result_block)
        # And the others are not elevated the same way.
        plain = css.split(".panel {", 1)[1].split("}", 1)[0]
        self.assertIn("--shadow-1", plain)

    def test_the_layout_names_a_focal_area(self):
        css = read("styles.css")
        self.assertIn("grid-template-areas", css)
        areas = css.split("grid-template-areas")[1][:200]
        for name in ("query", "result", "evidence"):
            with self.subTest(area=name):
                self.assertIn(name, areas)


class TestInteractionFeedback(unittest.TestCase):
    """Every interactive element has to say that it was touched."""

    def test_buttons_report_press_and_hover(self):
        css = read("styles.css")
        self.assertRegex(css, r"\.btn:hover:not\(:disabled\)")
        self.assertRegex(css, r"\.btn:active:not\(:disabled\)")

    def test_focus_is_visible_on_every_interactive_element(self):
        css = read("styles.css")
        # The whole selector list of the shared focus rule. Reading only up to
        # the first ":focus-visible" would see the first selector alone, which is
        # how this control could pass while .btn, .chip and textarea went
        # unchecked -- three elements reachable only by keyboard.
        anchor = css.index(":focus-visible")
        rule = css[css.rindex("}", 0, anchor) + 1: css.index("{", anchor)]
        for selector in (".input", ".btn", ".chip", "textarea"):
            with self.subTest(selector=selector):
                self.assertIn(selector, rule)
        brace = css.index("{", anchor)
        body = css[brace + 1: css.index("}", brace)]
        self.assertIn("outline:", body, "a focus rule that sets no outline is not one")

    def test_the_busy_state_is_animated_and_announced(self):
        self.assertIn(".btn__spinner", read("styles.css"))
        self.assertIn("@keyframes spin", read("styles.css"))
        primitives = read("components/primitives.jsx")
        self.assertIn("aria-busy", primitives,
                      "a spinner that is invisible to assistive technology "
                      "is not feedback")

    def test_the_connection_state_is_visible_without_being_read(self):
        css = read("styles.css")
        self.assertIn(".badge__dot", css)
        self.assertIn("@keyframes pulse", css)

    def test_the_live_badge_is_what_pulses(self):
        # The dot is what pulses, not the whole pill: an animated container reads
        # as the element loading rather than as a connection indicator.
        css = read("styles.css")
        live = css.split(".badge--live .badge__dot")[1].split("}")[0]
        self.assertIn("animation", live)
        self.assertIn("dot", read("components/primitives.jsx"))


class TestLoadingIsNotEmpty(unittest.TestCase):
    """The failure this exists to prevent: a spinner next to nothing reads as
    'no result'."""

    def test_a_skeleton_exists_and_is_animated(self):
        css = read("styles.css")
        self.assertIn(".skeleton", css)
        self.assertIn("@keyframes shimmer", css)

    def test_the_result_panel_renders_it_while_loading(self):
        views = read("views/ResultPanel.jsx")
        self.assertIn("Skeleton", views)
        self.assertIn('result.kind === "loading"', views)

    def test_an_unrun_query_says_so_instead_of_being_blank(self):
        views = read("views/ResultPanel.jsx")
        self.assertIn("EmptyState", views)
        self.assertIn('!result', views)

    def test_empty_and_loading_are_different_states(self):
        # The test id is a default parameter rather than a literal attribute, so
        # the two states are distinguished by what the primitives default to.
        primitives = read("components/primitives.jsx")
        self.assertIn('testId = "loading"', primitives)
        self.assertIn('data-testid="empty-state"', primitives)
        views = read("views/ResultPanel.jsx")
        self.assertIn("<Skeleton", views)
        self.assertIn("<EmptyState", views)

    def test_the_empty_state_carries_a_hint(self):
        primitives = read("components/primitives.jsx")
        self.assertIn("empty__hint", primitives)


class TestTokensRatherThanMagicNumbers(unittest.TestCase):
    def test_the_palette_defines_both_schemes_under_the_same_names(self):
        theme = read("theme.css")
        media = theme.split("@media (prefers-color-scheme: light)", 1)[1]
        explicit = theme.split(':root[data-theme="light"]', 1)[1]

        def names(block):
            return set(re.findall(r"(--[a-z0-9-]+):", block))

        # An explicit theme has to restate every token the media query sets.
        # A palette that defines a token only in one of the two is how a page
        # becomes unreadable when the user switches.
        self.assertTrue(names(media))
        self.assertTrue(names(explicit))
        self.assertEqual(names(explicit) - names(media), set())

    def test_spacing_and_motion_come_from_tokens(self):
        css = read("styles.css")
        # A raw hex colour in a stylesheet is a colour that will not follow the
        # scheme.
        self.assertNotRegex(css, r"#[0-9a-fA-F]{6}", "use a token, not a literal")
        # Interaction latency must come from a token. An animation *period* may
        # be literal, because a spin loop and a shimmer sweep are not feedback
        # latency, and pretending otherwise would only move the number.
        transitions = re.findall(r"transition:[^;}]+;", css)
        self.assertTrue(transitions)
        for rule in transitions:
            with self.subTest(rule=rule.strip()):
                self.assertIn("var(--t-", rule)

    def test_components_do_not_hardcode_colours(self):
        for rel in ("components/primitives.jsx", "panels/QueryPanel.jsx",
                    "panels/EvidencePanel.jsx", "views/ResultPanel.jsx",
                    "App.jsx"):
            with self.subTest(module=rel):
                self.assertNotRegex(read(rel), r"#[0-9a-fA-F]{6}")

    def test_reduced_motion_is_honoured(self):
        css = read("styles.css")
        self.assertIn("prefers-reduced-motion", css)
        block = css.split("prefers-reduced-motion")[1][:400]
        self.assertIn("animation-duration", block)


class TestTheFrozenPageIsStillUntouched(unittest.TestCase):
    def test_index_html_is_not_part_of_this_ui(self):
        # SRC is .../static/ui/src, so the frozen page is two levels up. Getting
        # this wrong compares the Vite shell, which passes for the wrong reason.
        frozen = (SRC.parent.parent / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("data-testid", frozen)
        self.assertIn("const FAILURE_TEXT", frozen)


if __name__ == "__main__":
    unittest.main()
