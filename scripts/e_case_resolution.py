"""E5: decide resolution from real before/after reports plus the independent oracle."""

import argparse
import json

from rdebug.diagnostics.content_oracle import compare_shader_outputs
from rdebug.diagnostics.resolution import evaluate_resolution


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="e-case-resolution")
    ap.add_argument("before_report")
    ap.add_argument("after_report")
    ap.add_argument("baseline_pixel_json")
    ap.add_argument("after_pixel_json")
    ap.add_argument("--event-id", type=int, default=11)
    ap.add_argument("--json", dest="json_path", required=True)
    args = ap.parse_args(argv)

    before, after = _load(args.before_report), _load(args.after_report)
    oracle = compare_shader_outputs(
        _load(args.baseline_pixel_json), _load(args.after_pixel_json),
        args.event_id)
    anomaly_ids = [f["findingId"] for f in
                   before["sections"]["findings"]["content"].get("findings", ())
                   if f.get("kind") == "anomaly"]
    evidence = {
        fid: {"passed": oracle["status"] == "same",
              "maxDifference": oracle.get("maxDifference")}
        for fid in anomaly_ids
    }
    result = evaluate_resolution(before, after, evidence, kinds=("anomaly",))
    result.update({
        "oracleStatus": oracle["status"],
        "maxDifference": oracle.get("maxDifference"),
        "eventId": args.event_id,
        "targetFindings": anomaly_ids,
    })
    with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
