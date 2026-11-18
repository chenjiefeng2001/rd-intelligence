"""D6/D7: generate the paired JSON and Markdown diagnostic reports.

Both files come from the same report object; the Markdown renderer is not
allowed to introduce a conclusion absent from the JSON.
"""

import argparse
import json

from rdebug.diagnostics.pipeline import run_diagnostic_pipeline


def main(argv=None):
    ap = argparse.ArgumentParser(prog="diagnostic-report")
    ap.add_argument("analysis_json")
    ap.add_argument("--json", dest="json_path", required=True)
    ap.add_argument("--markdown", dest="md_path", required=True)
    ap.add_argument("--capture")
    args = ap.parse_args(argv)
    with open(args.analysis_json, encoding="utf-8") as fh:
        analysis = json.load(fh)
    result = run_diagnostic_pipeline(analysis, capture=args.capture)
    with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result["report"], fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(args.md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(result["markdown"])
    print(json.dumps(result["quality"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
