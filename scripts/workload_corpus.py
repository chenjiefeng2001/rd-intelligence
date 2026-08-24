"""Generate the workload capture corpus from the triangle fixture.

Produces one .rdc per draw-count in tests/workload/corpus/:
  w00001.rdc ... w20000.rdc   (S/M/L tiers by event count)
XL tier (>100k events) requires a real game capture — place any *.rdc into
the corpus directory and it will be discovered automatically."""

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


def main():
    WORKDIR.mkdir(parents=True, exist_ok=True)
    CORPUS.mkdir(parents=True, exist_ok=True)
    exe = find_exe()
    env = dict(os.environ)
    env["RDEBUG_RENDERDOC_PATH"] = os.environ.get(
        "RDEBUG_RENDERDOC_PATH",
        r"D:\renderdoc_no_mcp\renderdoc\x64\Release\pymodules")

    generated = 0
    for draws in DRAWS:
        stem = CORPUS / f"w{draws:05d}"
        rdc = Path(str(stem) + "_frame11.rdc")
        if rdc.exists():
            generated += 1
            continue
        print("capturing", draws, "draws/frame ...", flush=True)
        subprocess.run(
            [str(exe), "30", str(CORPUS / f"w{draws:05d}.rdc"), RDOC_DLL,
             str(draws)],
            check=True, capture_output=True, text=True, timeout=300,
        )
        for _p in CORPUS.glob(f"w{draws:05d}*.rdc"):
            generated += 1
    print(f"corpus ready: {generated} captures in {CORPUS}")


if __name__ == "__main__":
    main()
