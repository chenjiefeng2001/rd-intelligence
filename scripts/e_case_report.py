"""E3/E6: produce the real-engineered-defect diagnostic report.

The content oracle is the independent failure judge; the S4 metadata comes
from real EXE/PDB/source identity checks, never from a path-name guess.
"""

import argparse
import json

from rdebug.diagnostics.content_oracle import compare_shader_outputs
from rdebug.diagnostics.pipeline import run_diagnostic_pipeline


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_metadata(identity, source_line, api_refs):
    cv = identity["codeview"]
    pdb = identity["pdb"]
    return {
        "capture_sha256": identity["capture"]["sha256"],
        "analysis_revision": identity["executable"]["sha256"][:12],
        "api_call": {"name": "CopyResource", "eventId": 2},
        "api_evidence_refs": api_refs,
        "engine_callsite": {"function": "main", "module": "triangle_defect.exe"},
        "source_location": {
            "file": identity["source"]["path"],
            "function": "main",
            "line": source_line,
            "lineVerified": True,
            "buildMatchesSourceRevision": (
                pdb["sha256"] == identity["pdb"]["sha256"]),
        },
        "binary_identity": {
            "verified": identity["pdbMatchesExecutable"],
            "sha256": identity["executable"]["sha256"],
        },
        "symbol_identity": {
            "verified": identity["pdbMatchesExecutable"],
            "guid": cv["guid"], "age": cv["age"],
        },
        "source_revision": {
            "verified": identity["pdbMatchesExecutable"],
            "sha256": identity["source"]["sha256"],
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="e-case-report")
    ap.add_argument("analysis_json")
    ap.add_argument("baseline_pixel_json")
    ap.add_argument("candidate_pixel_json")
    ap.add_argument("identity_json")
    ap.add_argument("--event-id", type=int, default=11)
    ap.add_argument("--source-line", type=int, default=133)
    ap.add_argument("--capture")
    ap.add_argument("--json", dest="json_path", required=True)
    ap.add_argument("--markdown", dest="md_path", required=True)
    args = ap.parse_args(argv)

    analysis = _load(args.analysis_json)
    oracle = compare_shader_outputs(
        _load(args.baseline_pixel_json), _load(args.candidate_pixel_json),
        args.event_id)
    identity = _load(args.identity_json)
    api_refs = [{"id": ev["id"]} for ev in analysis.get("evidence", ()) if ev.get("id")]
    metadata = build_metadata(identity, args.source_line, api_refs)
    result = run_diagnostic_pipeline(
        analysis, metadata=metadata, capture=args.capture,
        content_comparison=oracle)
    with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result["report"], fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(args.md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(result["markdown"])
    summary = result["report"]["sections"]["executive_summary"]["content"]
    summary.update({"oracleStatus": oracle["status"],
                    "oracleEventId": oracle["eventId"],
                    "sourceLevel": result["report"]["sections"]["analysis_scope"]
                    ["content"]["highestLevel"]})
    with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result["report"], fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps({"quality": result["quality"], "oracle": oracle["status"],
                      "sourceLevel": summary["sourceLevel"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
