"""D5.3: turn a recommendation into an executable change plan.

The plan is separate from the opinion: it names the target, scope, affected
paths, preconditions, expected outcome, compatibility risk and rollback. It
never asserts a file/line that was not supplied by a verified attribution.
"""

import hashlib
import json


def _plan_id(recommendation_id, target):
    canonical = json.dumps([recommendation_id, str(target)],
                           separators=(",", ":"), default=str)
    return "change-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def build_change_plans(recommendation_result, mappings=None):
    """One change plan per actionable change recommendation."""
    plans = []
    for item in recommendation_result.get("recommendations", ()):
        if item["actionType"] == "no_change" or item["status"] != "actionable":
            continue
        locations = item.get("sourceLocations", ())
        target = locations[0].get("file") if locations else "api_or_event_surface"
        plans.append({
            "changePlanId": _plan_id(item["recommendationId"], target),
            "recommendationRef": item["recommendationId"],
            "target": target,
            "scope": {
                "file": locations[0].get("file") if locations else None,
                "function": locations[0].get("function") if locations else None,
                "line": locations[0].get("line") if locations else None,
                "verifiedLevel": item.get("proposedChange", {}).get("verifiedLevel"),
            },
            "affectedPaths": [loc.get("file") for loc in locations if loc.get("file")],
            "reason": item["rationale"],
            "preconditions": list(item.get("preconditions", ())),
            "expectedOutcome": dict(item.get("expectedOutcome", {})),
            "compatibilityRisk": dict(item.get("risk", {})),
            "rollbackStrategy": dict(item.get("rollbackStrategy", {})),
            "status": "planned" if locations else "event_level_only",
        })
    return {
        "changePlans": plans,
        "changePlanCount": len(plans),
        "status": "planned" if plans else "not_applicable",
    }
