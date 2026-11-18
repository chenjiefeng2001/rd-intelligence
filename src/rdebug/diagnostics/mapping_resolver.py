"""D4.2/D4.3: resolve attribution from an analysis result and supplied metadata.

The resolver upgrades a level only from verified metadata. With no app symbols,
API call records or source revision, every event stays at S0. It never guesses
a file path from a function name or a project directory convention.
"""

from .source_attribution import build_mapping, validate_mapping


def event_refs_from_analysis(analysis):
    refs = []
    for entry in analysis.get("accesses", ()):
        for ev in entry.get("evidence", ()):
            if ev.get("id"):
                refs.append({"id": ev["id"], "eventId": entry.get("eventId")})
    for edge in analysis.get("causal", {}).get("edges", ()):
        for ref in edge.get("evidenceRefs", ()):
            if ref.get("id") and ref not in refs:
                refs.append(dict(ref))
    return refs[:16]


def resolve_attribution(analysis, metadata=None):
    """Build an attribution record; metadata is optional and evidence-bound."""
    metadata = metadata or {}
    refs = event_refs_from_analysis(analysis)
    api_call = metadata.get("api_call")
    api_evidence = metadata.get("api_evidence_refs") or []
    mapping = build_mapping(
        event_refs=refs,
        api_call=api_call if api_call and api_evidence else None,
        engine_callsite=metadata.get("engine_callsite"),
        source_location=metadata.get("source_location"),
        binary_identity=metadata.get("binary_identity"),
        symbol_identity=metadata.get("symbol_identity"),
        source_revision=metadata.get("source_revision"),
        path_mapping=metadata.get("path_mapping"),
        evidence_refs=api_evidence,
        candidates=metadata.get("candidates"),
    )
    validate_mapping(mapping)
    return mapping


def attach_to_report(report, diagnoses=None, mappings=None):
    """Add D3/D4 content to the fixed twelve-section D1 report structure."""
    from .report_model import set_section

    set_section(report, "diagnosis",
                "present" if diagnoses else "insufficient_evidence",
                None if diagnoses else "no anomaly triggered a diagnosis",
                {"chains": diagnoses or [], "count": len(diagnoses or [])})
    set_section(report, "analysis_scope", "present", None,
                {"sourceAttribution": mappings or [],
                 "highestLevel": max(
                     (m["highestVerifiedLevel"] for m in (mappings or [])),
                     default="S0")})
    set_section(report, "evidence_appendix", "present", None,
                {"mappingIds": [m["mappingId"] for m in (mappings or [])],
                 "eventRefs": [r for m in (mappings or [])
                               for r in m["eventRefs"]]})
    return report
