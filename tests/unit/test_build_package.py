"""Controls for scripts/build_package.py.

Two layers. The fast layer pins the verification logic and the two declarations
that made this project unbuildable or incomplete, so a regression is caught
without spending a build. The slow layer builds for real, because the defects
this script exists for were invisible to every other test in the repository: a
pyproject that no backend would accept, and a wheel that pip would install
happily while omitting the page the IDE serves.
"""
import importlib.util
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "scripts" / "build_package.py"
PP = REPO / "pyproject.toml"
STATIC = REPO / "src" / "rdebug_ide" / "static" / "index.html"


def load_script():
    spec = importlib.util.spec_from_file_location("build_package", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = load_script()


def have_backend() -> bool:
    return importlib.util.find_spec("build") is not None


def run_script(outdir, clean=True):
    cmd = [sys.executable, str(SCRIPT), "--outdir", str(outdir)]
    if clean:
        cmd.append("--clean")
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(REPO))


def make_wheel(path, members, entry_points=None):
    with zipfile.ZipFile(path, "w") as zf:
        for m in members:
            zf.writestr(m, "x")
        if entry_points is not None:
            zf.writestr("rd_intelligence-0.1.0.dist-info/entry_points.txt",
                        entry_points)
    return str(path)


GOOD_MEMBERS = [
    "rdebug_ide/static/index.html",
    "rdebug_ide/app.py",
    "rdebug/cli.py",
    "rdebug_mcp/server.py",
    "rd_intelligence-0.1.0.dist-info/licenses/LICENSE",
]
GOOD_ENTRY = ("[console_scripts]\n"
              "rdebug = rdebug.cli:main\n"
              "rdebug-mcp = rdebug_mcp.server:main\n"
              "rdebug-ide = rdebug_ide.app:main\n")


class TestTheVerifierHasTeeth(unittest.TestCase):
    """The check must be able to fail, on the exact defect it names."""

    def _wheel(self, members=None, entry=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return make_wheel(os.path.join(tmp, "w.whl"),
                          GOOD_MEMBERS if members is None else members,
                          GOOD_ENTRY if entry is None else entry)

    def test_a_complete_wheel_passes(self):
        self.assertTrue(bp.check_wheel(self._wheel())["ok"])

    def test_a_wheel_without_the_ide_page_is_rejected(self):
        # This is the real defect: pip succeeds, rdebug-ide starts, serves nothing.
        members = [m for m in GOOD_MEMBERS if "static" not in m]
        out = bp.check_wheel(self._wheel(members))
        self.assertFalse(out["ok"])
        self.assertIn("rdebug_ide/static/index.html", out["missing"])

    def test_a_wheel_without_a_licence_is_rejected(self):
        members = [m for m in GOOD_MEMBERS if "LICENSE" not in m]
        out = bp.check_wheel(self._wheel(members))
        self.assertFalse(out["ok"])
        self.assertTrue(any("LICENSE" in m for m in out["missing"]))

    def test_a_wheel_without_console_scripts_is_rejected(self):
        out = bp.check_wheel(self._wheel(entry="[console_scripts]\n"))
        self.assertFalse(out["ok"])
        for name in bp.CONSOLE_SCRIPTS:
            self.assertIn("console script " + name, out["missing"])

    def test_an_unreadable_artifact_is_infrastructure_not_a_pass(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        junk = os.path.join(tmp, "not-a-wheel.whl")
        with open(junk, "wb") as fh:
            fh.write(b"this is not a zip")
        with self.assertRaises(bp.Infra):
            bp.check_wheel(junk)

    def test_an_sdist_missing_a_required_input_is_rejected(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "s.tar.gz")
        with tarfile.open(path, "w:gz") as tf:
            for name in ("rd_intelligence-0.1.0/pyproject.toml",):
                data = b"x"
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        out = bp.check_sdist(path)
        self.assertFalse(out["ok"])
        self.assertIn("src/rdebug_ide/static/index.html", out["missing"])

    def test_the_two_failure_kinds_have_different_exit_codes(self):
        # "the machine could not answer" and "the answer is no" must not be
        # reported the same way.
        self.assertNotEqual(bp.INFRA, bp.REGRESSION)
        self.assertNotEqual(bp.PASS, bp.REGRESSION)


class TestTheDeclarationsThatBrokeTheBuild(unittest.TestCase):
    """Fast guards at the source, so no build is needed to catch a regression."""

    def test_the_static_page_is_declared_as_package_data(self):
        self.assertIn("[tool.setuptools.package-data]", PP.read_text(encoding="utf-8"))
        self.assertIn("static/*.html", PP.read_text(encoding="utf-8"))

    def test_no_license_classifier_survives_the_license_expression(self):
        # PEP 639 supersedes it; setuptools >= 78 refuses to build with both.
        text = PP.read_text(encoding="utf-8")
        self.assertIn('license = "MIT"', text)
        self.assertNotIn("License ::", text)

    def test_the_page_the_declaration_protects_exists(self):
        self.assertTrue(STATIC.is_file())


class TestTheRealBuild(unittest.TestCase):
    """Layer two. A real build, because these defects had no other detector."""

    def setUp(self):
        if not have_backend():
            self.skipTest("the `build` backend is absent; this is not a pass. "
                          "CI installs it, so CI runs this.")

    def test_a_real_build_produces_installable_artifacts(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        proc = run_script(out)
        self.assertEqual(proc.returncode, bp.PASS,
                         proc.stdout + proc.stderr)
        wheels = [f for f in os.listdir(out) if f.endswith(".whl")]
        sdists = [f for f in os.listdir(out) if f.endswith(".tar.gz")]
        self.assertEqual(len(wheels), 1)
        self.assertEqual(len(sdists), 1)
        with zipfile.ZipFile(os.path.join(out, wheels[0])) as zf:
            self.assertIn("rdebug_ide/static/index.html", zf.namelist())

    def test_the_page_is_included_because_it_is_declared_not_by_accident(self):
        # The mutation that mattered: remove the declaration and the wheel loses
        # the page while still building successfully. The staged copy exists so
        # that a leftover SOURCES.txt cannot mask this.
        original = PP.read_bytes()
        text = original.decode("utf-8")
        head, sep, tail = text.partition("[tool.setuptools.package-data]")
        self.assertTrue(sep, "the package-data section is already gone")
        cut = tail.index("rdebug_ide = [\"static/*.html\"]")
        tail = tail[tail.index("\n", cut) + 1:]
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        try:
            PP.write_bytes((head + tail).encode("utf-8"))
            proc = run_script(out)
        finally:
            PP.write_bytes(original)
        self.assertEqual(PP.read_bytes(), original, "the mutation did not revert")
        self.assertEqual(proc.returncode, bp.REGRESSION,
                         "a wheel without the IDE page was accepted:\n"
                         + proc.stdout + proc.stderr)
        self.assertIn("rdebug_ide/static/index.html", proc.stdout + proc.stderr)

    def test_an_unbuildable_package_is_infrastructure_not_pass(self):
        original = PP.read_bytes()
        text = original.decode("utf-8")
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        try:
            PP.write_bytes(text.replace('license = "MIT"',
                                       'license = "MIT"\nbogus-key = 1')
                           .encode("utf-8"))
            proc = run_script(out)
        finally:
            PP.write_bytes(original)
        self.assertEqual(PP.read_bytes(), original, "the mutation did not revert")
        self.assertEqual(proc.returncode, bp.INFRA,
                         "a package that cannot build was not reported as "
                         "infrastructure:\n" + proc.stdout + proc.stderr)

    def test_the_staged_source_excludes_build_state(self):
        stage = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, stage, ignore_errors=True)
        bp.stage_source(stage)
        for _root, dirs, _files in os.walk(stage):
            for name in dirs:
                with self.subTest(path=name):
                    self.assertNotIn("__pycache__", name)
                    self.assertNotIn("egg-info", name)


if __name__ == "__main__":
    unittest.main()
