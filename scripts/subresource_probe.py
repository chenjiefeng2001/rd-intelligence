"""C4: probe descriptor-level subresource detail on a real capture.

Measurement tool, not a gate. It never mutates a capture or a manifest.
"""

import argparse
import json

from rdebug.adapter.core import CaptureSession
from rdebug.adapter.descriptors import read_descriptor_access
from rdebug.analysis.subresource import (
    build_coverage,
    resolve_access_subresources,
)


def probe(capture, resource, events):
    rows = {}
    accesses = []
    with CaptureSession(capture) as session:
        for event_id in events:
            detail = read_descriptor_access(session, event_id, resource)
            rows[event_id] = detail
            accesses.append({
                "eventId": event_id,
                "resourceId": resource,
                "usage": "probe",
                "status": "observed",
            })
    resolved = resolve_access_subresources(accesses, rows)
    return {
        "kind": "subresource-probe",
        "capture": capture,
        "resourceId": resource,
        "descriptorAccess": rows,
        "resolved": resolved,
        "coverage": build_coverage(accesses, resolved),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="subresource-probe")
    ap.add_argument("capture")
    ap.add_argument("resource")
    ap.add_argument("events", nargs="+", type=int)
    ap.add_argument("--json", dest="json_path")
    args = ap.parse_args(argv)
    text = json.dumps(probe(args.capture, args.resource, args.events),
                      indent=2, ensure_ascii=False)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
