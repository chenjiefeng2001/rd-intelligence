"""D5.4: targeted verification steps derived from the finding, not a boilerplate list."""

CATEGORY_CHECKS = {
    "lifetime_order_conflict": (
        "replay and confirm create/access/release event order",
        "assert the lifetime endpoint status is no longer order_conflict",
    ),
    "subresource_mismatch": (
        "replay and compare bound-view mip/layer/byte ranges",
        "assert the observed range comparison no longer reports a mismatch",
    ),
    "copy_sampling_dependency": (
        "re-run the resource access index and dependency builder",
        "assert the dependency set stays observation-only unless new evidence appears",
    ),
    "sampled_content_mismatch": (
        "replay the after-fix capture and compare shader output with the baseline oracle",
        "assert the independent content comparison status is 'same' at the target event",
        "assert no new anomaly finding appears in the after-fix report",
    ),
}


def build_verification_plans(recommendation_result, change_result=None,
                             finding_result=None):
    """Give each recommendation checks tied to its finding category."""
    categories = {f.get("category") for f in
                  (finding_result or {}).get("findings", ())}
    checks = []
    for category in sorted(categories):
        checks.extend(CATEGORY_CHECKS.get(category, (
            "replay the capture that produced this finding",
            "assert the original finding no longer reproduces",
        )))
    checks.extend((
        "assert no new writer-to-reader anomaly is introduced",
        "run the existing unit, transport and cold-warm controls",
    ))
    plans = []
    for item in recommendation_result.get("recommendations", ()):
        if item["actionType"] == "no_change":
            steps = ["keep the original analysis output for comparison"]
        else:
            steps = list(checks)
        plans.append({
            "recommendationRef": item["recommendationId"],
            "changePlanRef": next(
                (p["changePlanId"] for p in (change_result or {}).get("changePlans", ())
                 if p.get("recommendationRef") == item["recommendationId"]), None),
            "steps": steps,
            "derivedFrom": sorted(categories),
        })
    return {"plans": plans, "planCount": len(plans)}
