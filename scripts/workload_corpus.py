"""Generate the workload capture corpus from the triangle fixture.

Produces one canonical capture per draw-count in tests/workload/corpus/:
  w00001_frame11.rdc ... w20000_frame11.rdc   (S/M/L tiers by event count)

The app is handed the stem `w00001.rdc` and emits `w00001_frame11.rdc`. The
canonical name is the emitted one, and every existence check, log line and
count in this file uses that single name. Membership is exact: a wide prefix
match would let `w00001_evil.rdc` satisfy the 1-draw tier.

XL tier (>100k events) requires a real game capture. Such a file is NOT part
of the canonical population and this script neither verifies nor counts it.
"""

import os
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
CORPUS = ROOT / "tests" / "workload" / "corpus"
FIXTURE_SRC = ROOT / "tests" / "integration" / "fixtures" / "triangle_app.cpp"
WORKDIR = Path(os.environ.get(
    "TEMP", str(HERE))) / "rdebug_workload_app"

DRAWS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 10000, 20000]
RDOC_DLL = os.environ.get("RDOC_DLL",
                          r"D:\renderdoc_no_mcp\renderdoc\x64\Release\renderdoc.dll")
RENDERDOCCMD = os.environ.get("RENDERDOCCMD",
                              r"C:\Program Files\RenderDoc\renderdoccmd.exe")
VCVARS = os.environ.get(
    "VCTOOLS_VCVARS",
    r"C:\Program Files\Microsoft Visual Studio\2022\Professional"
    r"\VC\Auxiliary\Build\vcvars64.bat")


def find_exe():
    exe = WORKDIR / "triangle.exe"
    prebuilt = Path(r"C:\Users\14977\AppData\Local\Temp\opencode\capapp\triangle.exe")
    if not exe.exists() and prebuilt.exists():
        WORKDIR.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(prebuilt.read_bytes())
        return exe
    if exe.exists():
        return exe
    if not FIXTURE_SRC.exists():
        raise SystemExit("fixture source not found: " + str(FIXTURE_SRC))
    app_header = ROOT.parent / "renderdoc" / "renderdoc" / "api" / "app"
    cmd = (f'"{VCVARS}" >nul 2>&1 && cl /nologo /O2 /EHsc '
           f'/I "{app_header}" '
           f'/Fe:{exe} {FIXTURE_SRC} /Fo:{WORKDIR}\\')
    subprocess.run(["cmd", "/s", "/c", cmd], check=True,
                   capture_output=True, text=True)
    return exe


def canonical_name(draws):
    """The one canonical fixture filename for a draw tier."""
    return f"w{draws:05d}_frame11.rdc"


def canonical_path(draws, corpus_dir=None):
    """The canonical fixture path for a draw tier."""
    return Path(corpus_dir or CORPUS) / canonical_name(draws)


def population(draws=None, corpus_dir=None):
    """The declared population: one canonical path per draw tier."""
    return [canonical_path(d, corpus_dir) for d in (draws or DRAWS)]


def missing_draws(draws=None, corpus_dir=None):
    """Draw tiers whose canonical fixture is absent.

    Membership is an exact filename test. The previous check globbed
    `w00001*.rdc`, which accepted any file carrying the tier's prefix.
    """
    return [d for d in (draws or DRAWS)
            if not canonical_path(d, corpus_dir).is_file()]


def main():
    WORKDIR.mkdir(parents=True, exist_ok=True)
    CORPUS.mkdir(parents=True, exist_ok=True)
    todo = missing_draws()
    if not todo:
        print(f"corpus ready: {len(population())} captures in {CORPUS}",
              flush=True)
        return 0
    exe = find_exe()
    env = dict(os.environ)
    env["RDEBUG_RENDERDOC_PATH"] = os.environ.get(
        "RDEBUG_RENDERDOC_PATH",
        r"D:\renderdoc_no_mcp\renderdoc\x64\Release\pymodules")
    for draws in todo:
        print("capturing", draws, "draws/frame ...", flush=True)
        subprocess.run(
            [str(exe), "30", str(CORPUS / f"w{draws:05d}.rdc"), RDOC_DLL,
             str(draws)],
            check=True, capture_output=True, text=True, timeout=300,
        )
        produced = canonical_path(draws)
        if not produced.is_file():
            raise SystemExit(
                "producer stem was accepted but the canonical fixture did "
                f"not appear: expected {produced}")
    print(f"corpus ready: {len(population())} captures in {CORPUS}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
