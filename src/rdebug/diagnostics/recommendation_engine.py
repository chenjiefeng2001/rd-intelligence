"""D5.2: evidence-gated recommendation generation.

The gate is evaluated before an action type is chosen. An established
diagnosis does not imply a code change: a legal RAW dependency correctly
produces `no_change`. An unestablished diagnosis can still justify gathering
evidence, but that is never dressed up as a confirmed fix.
"""

from .recommendation_model import recommendation, validate_recommendation

LEVEL_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}


def _conclusion_status(diagnosis_result):
    chains = diagnosis_result.get("diagnoses", ())
    if not chains:
        return None
    result = chains[0].get("conclusion") or {}
    return result.get("status")


def _verified_locations(mapping, level):
    """Only S3+ mappings with a source record may contribute a location."""
    if LEVEL_ORDER.get(level, 0) < 3:
        return []
    location = mapping.get("sourceLocation", {})
    if not (location.get("file") and location.get("function")):
        return []
    return [{
        "file": location.get("file"),
        "function": location.get("function"),
        "line": location.get("line") if level == "S4" else None,
        "verifiedByAttribution": True,
        "mappingId": mapping.get("mappingId"),
    }]


def build_recommendations(finding_result, diagnosis_result, mappings=None,
                          capture=None):
    """Return an evidence-bound recommendation set for the supplied inputs."""
    findings = finding_result.get("findings", ())
    mappings = mappings or []
    mapping = mappings[0] if mappings else {}
    level = mapping.get("highestVerifiedLevel", "S0")
    conclusion_status = _conclusion_status(diagnosis_result)
    items = []

    if not findings:
        items.append(recommendation(
            finding_refs=[], diagnosis_refs=[], action_type="no_change",
            status="actionable", priority="P3",
            rationale="No finding was produced from the supplied evidence.",
            expected_outcome={"state": "no_defect_reported"},
            verification_steps=["re-run the analysis if new evidence is supplied"],
        ))
    elif all(f.get("kind") == "observation" for f in findings):
        items.append(recommendation(
            finding_refs=[f["findingId"] for f in findings],
            diagnosis_refs=[], action_type="no_change", status="actionable",
            priority="P3",
            rationale="Observations describe a normal resource dependency; "
                      "no anomaly was detected and no code change is justified.",
            evidence_refs=[ref for f in findings for ref in f.get("evidenceRefs", ())][:4],
            expected_outcome={"state": "no_defect_reported"},
            verification_steps=["keep the captured evidence for comparison"],
        ))
    else:
        anomaly_refs = [f["findingId"] for f in findings
                        if f.get("kind") == "anomaly"]
        diagnosis_refs = [c["conclusion"]["conclusionId"]
                          for c in diagnosis_result.get("diagnoses", ())
                          if c.get("conclusion")]
        evidence = [ref for f in findings if f.get("kind") == "anomaly"
                    for ref in f.get("evidenceRefs", ())]
        if conclusion_status in (None, "not_established"):
            items.append(recommendation(
                finding_refs=anomaly_refs, diagnosis_refs=diagnosis_refs,
                action_type="instrumentation", status="insufficient_evidence",
                priority="P2",
                rationale="An anomaly was reported but no diagnosis is established; "
                          "gather discriminating evidence before proposing a fix.",
                evidence_refs=evidence[:4],
                expected_outcome={"state": "evidence_sufficient_for_diagnosis"},
                preconditions=["run the discriminating checks from the diagnosis chain"],
                verification_steps=["re-run the diagnosis with the new evidence"],
            ))
        elif conclusion_status == "provisional":
            items.append(recommendation(
                finding_refs=anomaly_refs, diagnosis_refs=diagnosis_refs,
                action_type="capture_workload", status="insufficient_evidence",
                priority="P2",
                rationale="The diagnosis is provisional and competing explanations "
                          "remain; obtain a workload that distinguishes them.",
                evidence_refs=evidence[:4],
                expected_outcome={"state": "alternative_explanations_distinguished"},
                preconditions=["do not treat this as a confirmed fix"],
                verification_steps=["compare the new capture against the competing hypotheses"],
            ))
        else:
            locations = _verified_locations(mapping, level)
            if LEVEL_ORDER.get(level, 0) >= 3 and locations:
                action = "code_change"
                rationale = ("Established diagnosis with a verified source mapping; "
                             "a scoped code change can be proposed at the verified level.")
            elif LEVEL_ORDER.get(level, 0) >= 2:
                action = "api_state_correction"
                rationale = ("Established diagnosis at engine level; propose an "
                             "API/state check, not an application source edit.")
            else:
                action = "api_state_correction"
                rationale = ("Established diagnosis without source mapping; restrict "
                             "the proposal to API/event level checks.")
            items.append(recommendation(
                finding_refs=anomaly_refs, diagnosis_refs=diagnosis_refs,
                action_type=action, status="actionable", priority="P1",
                rationale=rationale,
                evidence_refs=evidence[:4],
                source_locations=locations,
                proposed_change={"scope": action, "verifiedLevel": level},
                expected_outcome={"state": "anomaly_no_longer_reproduced"},
                risk={"sourcePrecision": level},
                preconditions=["confirm the diagnosis against the capture"],
                verification_steps=[
                    "replay the original capture and confirm the finding scope",
                    "replay after the change and assert the anomaly is gone",
                    "assert no new resource dependency anomaly is introduced",
                ],
            ))

    for item in items:
        validate_recommendation(item)
    return {
        "recommendations": items,
        "recommendationCount": len(items),
        "evidenceGate": conclusion_status or "no_diagnosis",
        "sourceLevel": level,
    }
