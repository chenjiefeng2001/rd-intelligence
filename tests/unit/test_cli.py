import contextlib
import io
import json
import unittest

from rdebug import cli


def parse_error(err_text):
    start = err_text.find("{")
    assert start >= 0, err_text
    return json.loads(err_text[start:])


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def test_version_flag(self):
        code, out, _ = run_main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("rdebug", out)

    def test_no_command_prints_help_and_exits(self):
        code, out, _ = run_main([])
        self.assertEqual(code, 2)
        self.assertIn("usage", out.lower())

    def test_missing_module_fails_cleanly(self):
        code, _, err = run_main(["info", "does_not_exist.rdc"])
        self.assertEqual(code, 2)
        payload = parse_error(err)
        self.assertIn("error", payload)

    def test_trace_pixel_requires_session(self):
        code, _, err = run_main(["trace-pixel", "nope.rdc", "--x", "1", "--y", "2"])
        self.assertEqual(code, 2)
        payload = parse_error(err)
        self.assertIn("error", payload)

    def test_indent_global_option_accepted_anywhere(self):
        code, out, err = run_main(["--indent", "4"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
