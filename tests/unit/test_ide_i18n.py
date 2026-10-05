"""Controls for the interface-language layer.

Static matching can only show that strings exist. These controls run the real
applyI18n() in Node against a stub DOM, because the failure that matters is a
language switch that reports success and leaves the page in the old language.
"""
import json
import pathlib
import re
import subprocess
import tempfile
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent.parent
        / "src" / "rdebug_ide" / "static" / "index.html")

ATTRIBUTES = ("data-i18n", "data-i18n-placeholder", "data-i18n-html")

# Values that are deliberately identical in both languages: coordinate notation
# is a convention, not prose, and translating "A" into a Chinese article would
# change what the input means.
IDENTICAL = {"l.a", "l.b"}


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def script() -> str:
    return re.findall(r"<script>(.*?)</script>", page(), re.S)[0]


def keys_in_markup() -> list:
    """Every key the markup actually asks for, paired with its attribute."""
    pairs = []
    for attr in ATTRIBUTES:
        pattern = re.escape(attr) + r'="([^"]+)"'
        for key in re.findall(pattern, page()):
            pairs.append((attr, key))
    return pairs


def extract_body(src: str, name: str) -> str:
    m = re.search(r"function " + re.escape(name) + r"\(", src)
    assert m, "missing function " + name
    start = src.index("{", m.end() - 1)
    depth, i = 0, start
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
        i += 1


def balanced(src: str, header: str) -> str:
    """The body of a `header: { ... }` entry, found by counting braces.

    Regexes cannot do this: the groups nest and none of them share a terminator.
    """
    start = src.index(header)
    start = src.index("{", start + len(header) - 1)
    depth, i = 0, start
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
        i += 1


def table(lang: str) -> str:
    return balanced(script(), "  " + lang + ": {")


def strip_strings(block: str) -> str:
    """Blank out quoted literals so their contents cannot be read as keys."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", '""', block)


def keys_in(block: str) -> set:
    return set(re.findall(r"(?:^|[{,\s])([A-Za-z][A-Za-z0-9]*)\s*:",
                          strip_strings(block)))


def scalar(block: str, name: str):
    name_pattern = (r"(?:^|[{,\s])" + re.escape(name)
                    + r":\s*('[^']*'|\"[^\"]*\")")
    m = re.search(name_pattern, block)
    return None if m is None else m.group(1)[1:-1]


def declaration(src: str, name: str) -> str:
    """The whole `function name(params) { body }`, for re-emitting into a harness.

    Emitting only the body would produce `function T(` followed by the first
    statement, which parses the parameter list as `const` in binding position.
    """
    head = re.search(r"function " + re.escape(name) + r"\(", src)
    assert head, "missing function " + name
    start = head.start()
    paren = src.index("(", head.end() - 1)
    depth, i = 0, paren
    while True:
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return src[start:i + 1] + "{" + extract_body(src, name) + "}"


def i18n_code() -> str:
    """Everything the language layer needs, taken as one contiguous slice.

    Naming the individual functions here would mean that adding a helper breaks
    this harness with a ReferenceError -- which is how a control can quietly stop
    testing the code it was written for. The slice grows by itself instead.
    """
    src = script()
    region = src[src.index("const I18N = {"):src.index("async function api")]
    return "\n".join([
        region,
        re.search(r"const FAILURE_TEXT = \{.*?\};", src, re.S).group(0),
    ])


def harness() -> str:
    """The real i18n code over a stub DOM, so switching is observed not assumed."""
    return """
const KEYS = __KEYS__;
function mkNode(attr, key) {
  return {
    _attr: attr, _key: key, _text: "", _html: "", _ph: "",
    getAttribute(name) { return name === attr ? this._key : null; },
    set textContent(v) { this._text = v; }, get textContent() { return this._text; },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    set placeholder(v) { this._ph = v; }, get placeholder() { return this._ph; },
  };
}
const NODES = {};
KEYS.forEach(k => { (NODES[k.attr] = NODES[k.attr] || []).push(mkNode(k.attr, k.key)); });
globalThis.document = {
  documentElement: {},
  querySelectorAll(sel) { return NODES[sel.replace(/[\\[\\]]/g, "")] || []; },
};
globalThis.localStorage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = v; },
};
const langBtn = { _text: "" };
const $ = id => (id === "btnLang") ? langBtn : null;
__I18N__

function snapshot() {
  return KEYS.map(k => {
    const n = NODES[k.attr].find(x => x._key === k.key);
    return [k.attr, k.key, n.textContent, n.innerHTML, n.placeholder];
  });
}
applyI18n("zh");
const zh = {lang: document.documentElement.lang, LANG: LANG,
            failure: FAILURE_TEXT.api_error, btn: langBtn.textContent,
            stored: localStorage.getItem("rdebug-ide-lang"), nodes: snapshot()};
applyI18n("en");
console.log(JSON.stringify({zh: zh, en: {lang: document.documentElement.lang,
                                        LANG: LANG,
                                        failure: FAILURE_TEXT.api_error,
                                        btn: langBtn.textContent,
                                        nodes: snapshot()}}));
""".replace("__KEYS__", json.dumps([{"attr": a, "key": k}
                                           for a, k in keys_in_markup()])
            ).replace("__I18N__", i18n_code())


def run(js: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js)
        path = fh.name
    # encoding is explicit: text=True alone decodes with the locale codec, which
    # is not UTF-8 on this machine and cannot read the Chinese assertions back.
    r = subprocess.run(["node", path], capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError("harness failed: " + r.stderr)
    return json.loads(r.stdout)


CJK = re.compile(r"[\u4e00-\u9fff]")


def written(node: list) -> str:
    return node[2] or node[3] or node[4]


class TestSwitchingActuallyHappens(unittest.TestCase):
    """Layer one: observed behaviour in Node rather than source matching."""

    @classmethod
    def setUpClass(cls):
        cls.out = run(harness())

    def test_switching_to_chinese_changes_the_language(self):
        self.assertEqual(self.out["zh"]["lang"], "zh-CN")
        self.assertEqual(self.out["zh"]["LANG"], "zh")

    def test_switching_back_restores_english(self):
        self.assertEqual(self.out["en"]["lang"], "en")
        self.assertEqual(self.out["en"]["LANG"], "en")

    def test_the_failure_banner_follows_the_language(self):
        self.assertTrue(CJK.search(self.out["zh"]["failure"]),
                        "the banner stayed English under Chinese")
        self.assertEqual(self.out["en"]["failure"],
                         "The service rejected the request")

    def test_the_toggle_offers_the_other_language(self):
        self.assertEqual(self.out["zh"]["btn"], "English")
        self.assertEqual(self.out["en"]["btn"], "\u4e2d\u6587")

    def test_the_choice_is_remembered(self):
        self.assertEqual(self.out["zh"]["stored"], "zh")

    def test_every_keyed_node_receives_text(self):
        for stage in ("zh", "en"):
            for node in self.out[stage]["nodes"]:
                with self.subTest(stage=stage, key=node[1]):
                    self.assertTrue(written(node), "a keyed node received nothing")

    def test_a_placeholder_is_translated_not_silently_dropped(self):
        hinted = [n for n in self.out["zh"]["nodes"] if n[1] == "res.hint"]
        self.assertEqual(len(hinted), 1, "the prompt hint lost its attribute")
        self.assertTrue(CJK.search(hinted[0][4]),
                        "textContent cannot set a placeholder; it needs its own pass")

    def test_every_key_actually_differs_between_languages(self):
        en = {n[1]: written(n) for n in self.out["en"]["nodes"]}
        for node in self.out["zh"]["nodes"]:
            key = node[1]
            if key in IDENTICAL:
                continue
            with self.subTest(key=key):
                self.assertNotEqual(written(node), en[key],
                                    "switching to Chinese changed nothing here")

    def test_a_missing_translation_falls_back_to_english(self):
        self.assertIn('LANG = I18N[lang] ? lang : "en"', script())


class TestTheTwoTablesAgree(unittest.TestCase):
    def test_the_two_tables_expose_the_same_keys(self):
        en, zh = keys_in(table("en")), keys_in(table("zh"))
        self.assertEqual(en, zh)

    def translation(self, key):
        """A key is either a group member or a top-level scalar; look in both.

        The group lookup is lazy on purpose: a scalar key such as eidScope has
        no `{`, so probing for one has to be able to fail without taking the
        scalar lookup down with it.
        """
        group, dot, name = key.partition(".")
        if not dot:
            group, name = "", key      # partition yields ("eidScope", "", "")
        zh = table("zh")
        if group:
            try:
                found = scalar(balanced(zh, group + ": {"), name)
            except ValueError:
                found = None
            if found is not None:
                return found
        return scalar(zh, name)

    def test_chinese_covers_every_key_the_markup_asks_for(self):
        for _, key in keys_in_markup():
            with self.subTest(key=key):
                self.assertIsNotNone(self.translation(key),
                                     "no Chinese for " + key)

    def test_no_chinese_value_is_left_empty(self):
        for _, key in keys_in_markup():
            with self.subTest(key=key):
                value = self.translation(key)
                self.assertTrue(value and value.strip(),
                                "an empty translation blanks the element")

    def test_english_repeats_the_markup_it_replaces(self):
        en = table("en")
        for literal in ("Query", "Result", "Evidence", "AI Prompt (grounded)",
                        "Diff A vs B", "Trace A", "Generate AI Prompt",
                        "Copy prompt", "run a query\u2026", "CI baseline: not loaded"):
            with self.subTest(literal=literal):
                self.assertIn('"' + literal + '"', en)
                self.assertIn(literal, page())

    def test_both_languages_keep_the_interpolation_placeholders(self):
        for lang in ("en", "zh"):
            body = balanced(table(lang), "trace: {")
            for token in ("{n}", "{id}"):
                with self.subTest(lang=lang, token=token):
                    self.assertIn(token, body)

    def test_the_truncation_wording_stays_honest_in_chinese(self):
        value = scalar(balanced(table("zh"), "trace: {"), "truncated")
        self.assertIn("\u4e0d\u5b8c\u6574", value,
                      "the Chinese truncation notice dropped the incompleteness")
        self.assertIn("{n}", value, "the count interpolation was lost")

    def test_the_chinese_failure_wording_is_actually_chinese(self):
        body = balanced(table("zh"), "failure: {")
        for kind in ("transport_error", "malformed", "api_error"):
            with self.subTest(kind=kind):
                self.assertTrue(CJK.search(scalar(body, kind)))


class TestTheFrozenContainmentSurvives(unittest.TestCase):
    def test_show_failure_gained_no_language_dependency(self):
        # The D11 and D9 harnesses execute showFailure in a bare Node process that
        # contains none of the i18n symbols, so a reference here would be a runtime
        # ReferenceError instead of a test failure.
        body = extract_body(script(), "showFailure")
        for token in ("I18N", "applyI18n", "LANG", "T("):
            with self.subTest(token=token):
                self.assertNotIn(token, body)

    def test_the_banner_is_translated_by_assigning_the_frozen_object(self):
        src = script()
        self.assertIn("Object.assign(FAILURE_TEXT, I18N[LANG].failure)", src)
        self.assertEqual(src.count("const FAILURE_TEXT = {"), 1)

    def test_the_unknown_kind_fallback_is_preserved(self):
        self.assertIn("FAILURE_TEXT[kind] || FAILURE_TEXT.api_error", page())

    def test_no_renderer_is_called_from_the_language_pass(self):
        for line in page().splitlines():
            code = line.strip()
            if code.startswith("function "):
                continue
            for name in ("renderDiff(", "renderTrace("):
                with self.subTest(line=code[:60]):
                    self.assertNotIn(name, code)


class TestTheSwitchIsReachable(unittest.TestCase):
    def test_a_toggle_exists_and_is_wired(self):
        self.assertIn('id="btnLang"', page())
        self.assertIn('$("btnLang").onclick', page())

    def test_the_declaration_says_english(self):
        # The page is authored in English, so lang="zh" was simply untrue.
        self.assertIn('<html lang="en">', page())

    def test_the_language_choice_is_restored(self):
        self.assertIn('localStorage.getItem("rdebug-ide-lang")', page())
        self.assertIn('applyI18n(storedLang || "en")', page())

    def test_generated_markup_carries_its_own_keys(self):
        # The pass re-translates what is already on screen, which is why it needs
        # no renderer call.
        for key in ("diff.comparison", "diff.layers", "trace.target", "trace.reads"):
            with self.subTest(key=key):
                self.assertIn('data-i18n="' + key + '"', page())


class TestTheControlCanFail(unittest.TestCase):
    def test_dropping_one_chinese_string_is_caught(self):
        # Bytes in and bytes out. A text round trip normalises line endings, which
        # would make this test silently rewrite the file it is only inspecting.
        original = PAGE.read_bytes()
        try:
            mutated = original.decode("utf-8").replace('diff:"对比 A 与 B"',
                                                       'diff:"Diff A vs B"')
            PAGE.write_bytes(mutated.encode("utf-8"))
            out = run(harness())
            key = "b.diff"
            en = {n[1]: written(n) for n in out["en"]["nodes"]}
            zh = {n[1]: written(n) for n in out["zh"]["nodes"]}
            self.assertEqual(zh[key], en[key])
        finally:
            PAGE.write_bytes(original)

    def test_the_mutation_leaves_the_file_byte_identical(self):
        before = PAGE.read_bytes()
        self.test_dropping_one_chinese_string_is_caught()
        self.assertEqual(PAGE.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
