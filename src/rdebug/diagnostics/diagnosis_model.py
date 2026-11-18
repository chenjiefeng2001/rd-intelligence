"""D3.1: the diagnosis chain contract.

Facts, hypotheses, alternatives and conclusions are separate objects with
separate status vocabularies. This model never converts a hypothesis into a
root cause, never counts supporting evidence into a probability, and never
overrides the evidence layer's observed/inferred/unknown status.

Traceability is part of the contract:
  Conclusion -> Hypothesis -> Facts -> EvidenceRefs -> Original Events
"""

import hashlib
import json

FACT_STATUSES = ("observed", "inferred", "unverified")
HYPOTHESIS_STATUSES = ("candidate", "supported", "weakened", "ruled_out",
                       "untestable")
CONCLUSION_STATUSES = ("established", "provisional", "not_established",
                       "ruled_out")
DIAGNOSIS_RELATIONS = ("supported_by", "explained_by", "challenged_by",
                       "evaluated_as")


def _stable_id(prefix, parts):
    canonical = json.dumps(parts, separators=(",", ":"), default=str)
    return prefix + "-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def fact(statement, evidence_status, evidence_refs, source_analysis_refs=None,
         limitations=None):
    """Record only what the supplied evidence actually supports."""
    if evidence_status not in FACT_STATUSES:
        raise ValueError("invalid fact evidence status: " + str(evidence_status))
    if not evidence_refs:
        raise ValueError("a fact requires at least one evidence reference")
    if evidence_status == "observed" and not evidence_refs:
        raise ValueError("observed fact requires direct evidence")
    return {
        "factId": _stable_id("fact", [statement, evidence_status,
                                      sorted(ref.get("id", "") for ref in evidence_refs)]),
        "statement": statement,
        "evidenceStatus": evidence_status,
        "evidenceRefs": [dict(ref) for ref in evidence_refs],
        "sourceAnalysisRefs": list(source_analysis_refs or []),
        "limitations": list(limitations or []),
    }


def hypothesis(statement, status="candidate", supporting=None, contradicting=None,
               assumptions=None, missing=None, discriminating_checks=None):
    """A testable claim with its support, counter-evidence and gaps kept apart."""
    if status not in HYPOTHESIS_STATUSES:
        raise ValueError("invalid hypothesis status: " + str(status))
    return {
        "hypothesisId": _stable_id("hypothesis", [statement, status]),
        "statement": statement,
        "status": status,
        "supportingEvidence": list(supporting or []),
        "contradictingEvidence": list(contradicting or []),
        "assumptions": list(assumptions or []),
        "missingEvidence": list(missing or []),
        "discriminatingChecks": list(discriminating_checks or []),
    }


def conclusion(status, hypothesis_refs, fact_refs, reason, alternatives=None):
    """A conclusion is only valid with a traceable chain and a stated reason."""
    if status not in CONCLUSION_STATUSES:
        raise ValueError("invalid conclusion status: " + str(status))
    if not hypothesis_refs and status != "not_established":
        raise ValueError("a non-trivial conclusion requires a hypothesis")
    if not reason:
        raise ValueError("a conclusion requires a reason")
    return {
        "conclusionId": _stable_id(
            "conclusion", [status, sorted(hypothesis_refs), reason]),
        "status": status,
        "hypothesisRefs": list(hypothesis_refs),
        "factRefs": list(fact_refs),
        "reason": reason,
        "alternativeRefs": list(alternatives or []),
        "probabilisticConfidence": None,
    }


def chain(finding_ref, facts=None, hypotheses=None, alternatives=None,
          relations=None, result=None):
    """Bundle the diagnosis chain for one finding."""
    return {
        "findingRef": finding_ref,
        "facts": list(facts or []),
        "hypotheses": list(hypotheses or []),
        "alternatives": list(alternatives or []),
        "relations": list(relations or []),
        "conclusion": result,
    }


def validate_chain(item):
    """Check ids, relation vocabulary and reverse traceability."""
    for rel in item.get("relations", ()):
        if rel.get("type") not in DIAGNOSIS_RELATIONS:
            raise ValueError("invalid diagnosis relation: " + str(rel.get("type")))
    fact_ids = {f["factId"] for f in item.get("facts", ())}
    hypothesis_ids = {h["hypothesisId"] for h in item.get("hypotheses", ())}
    result = item.get("conclusion")
    if result is not None:
        if result["status"] not in CONCLUSION_STATUSES:
            raise ValueError("invalid conclusion status")
        for ref in result.get("hypothesisRefs", ()):
            if ref not in hypothesis_ids and result["status"] != "not_established":
                raise ValueError("conclusion points at an absent hypothesis")
        for ref in result.get("factRefs", ()):
            if ref not in fact_ids:
                raise ValueError("conclusion points at an absent fact")
        if result.get("probabilisticConfidence") is not None:
            raise ValueError("diagnosis must not carry a probability")
    return True
