import pathlib
import re
import subprocess
import tempfile
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent.parent
        / "src" / "rdebug_ide" / "static" / "index.html")

# Every page-level helper the script is allowed to call. Keeping the list
# explicit is deliberate: the point is to catch a call to something that is no
# longer defined, which whole-script parsing cannot see.
HELPERS = ("api", "enter", "showFailure", "showOk", "parseCoord",
           "canonicalResourceId", "renderDiff", "renderTrace", "renderCi",
           "T", "resolve", "applyI18n")


def script() -> str:
    return PAGE.read_text(encoding="utf-8")


def blocks(src: str) -> list:
    return re.findall(r"<script>(.*?)</script>", src, re.S)


def check(js: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js)
        path = fh.name
    return subprocess.run(["node", "--check", path], capture_output=True,
                          text=True)


class TestWholeScriptParses(unittest.TestCase):
    """Layer two. Extracted functions can be correct while the page that calls
    them does not parse, which is exactly how the P2-D freeze was invalidated.
    """

    def test_every_script_block_parses(self):
        found = blocks(script())
        self.assertTrue(found, "no <script> block found")
        for i, js in enumerate(found):
            r = check(js)
            self.assertEqual(r.returncode, 0,
                             f"script block {i} does not parse: "
                             f"{r.stderr.strip()}")

    def test_an_injected_syntax_error_is_caught(self):
        """Orthogonal to the D8 behaviour mutation: this one edits the script
        rather than a validator, so the two controls cannot mask each other."""
        js = blocks(script())[0]
        self.assertEqual(check(js).returncode, 0)
        broken = js.replace("function api(", "function api( {", 1)
        self.assertNotEqual(broken, js, "mutation did not apply")
        self.assertNotEqual(check(broken).returncode, 0,
                            "an unparsable script was accepted")


class TestCalledHelpersAreDefined(unittest.TestCase):
    """Layer three. Parsing does not resolve references, so a removed helper
    still parses and only fails once the path runs."""

    def test_every_called_helper_is_declared(self):
        src = blocks(script())[0]
        for name in HELPERS:
            with self.subTest(helper=name):
                called = re.search(rf"(?<![\w.$]){re.escape(name)}\s*\(", src)
                if called is None:
                    continue
                declared = (f"function {name}(") in src
                self.assertTrue(declared,
                                f"{name} is called but never declared")

    def test_no_helper_is_declared_twice(self):
        src = blocks(script())[0]
        for name in HELPERS:
            with self.subTest(helper=name):
                self.assertLessEqual(
                    len(re.findall(rf"function {re.escape(name)}\(", src)), 1,
                    f"{name} is declared more than once, so the later copy silently "
                    "replaces the earlier one")


if __name__ == "__main__":
    unittest.main()
