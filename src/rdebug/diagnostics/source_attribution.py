"""D4.1/D4.2: source attribution with verified S0-S4 levels.

A level is the highest *verified* precision, never an inferred ambition. Path
translation is not source identity; a symbol filename match is not PDB
identity; a line number is not S4 unless the binary and source revision are
bound to the exact build that produced the event.
"""

import hashlib
import json

LEVELS = ("S0", "S1", "S2", "S3", "S4")


def _mapping_id(event_refs):
    canonical = json.dumps(sorted(str(ref.get("id", ref)) for ref in event_refs),
                           separators=(",", ":"), default=str)
    return "source-map-" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def _identity_ok(identity):
    return bool(identity) and identity.get("verified") is True


def evaluate_level(event_refs, api_call=None, engine_callsite=None,
                   source_location=None, binary_identity=None,
                   symbol_identity=None, source_revision=None,
                   path_mapping=None, evidence_refs=None, candidates=None):
    """Return the highest defensible level and the reasons for each boundary."""
    limitations = []
    if not event_refs:
        return "S0", ["no_event_reference"], limitations
    level = "S0"

    if api_call and evidence_refs:
        level = "S1"
    else:
        limitations.append("api_call_not_established")

    symbols_ok = _identity_ok(symbol_identity)
    binary_ok = _identity_ok(binary_identity)
    if not symbols_ok:
        limitations.append("application_symbols_not_available")
    if not binary_ok:
        limitations.append("binary_identity_not_verified")

    if (level == "S1" and engine_callsite and symbols_ok and binary_ok
            and evidence_refs):
        level = "S2"
    elif engine_callsite:
        limitations.append("symbol_or_binary_identity_not_verified")

    revision_ok = _identity_ok(source_revision)
    if not revision_ok:
        limitations.append("source_revision_not_verified")
    location = source_location or {}
    has_location = bool(location.get("file") and location.get("function"))
    if (level == "S2" and has_location and revision_ok and symbols_ok
            and binary_ok and evidence_refs):
        level = "S3"
    elif has_location and not revision_ok:
        limitations.append("path_mapping_is_not_source_identity")

    if level == "S3" and location.get("line") is not None:
        line_verified = location.get("lineVerified") is True
        build_matched = bool(location.get("buildMatchesSourceRevision"))
        if line_verified and build_matched and revision_ok:
            level = "S4"
        else:
            limitations.append("line_not_verified_against_build")

    if candidates and len(candidates) > 1:
        limitations.append("multiple_candidate_callsites_kept_ambiguous")
    return level, [], limitations


def build_mapping(event_refs, api_call=None, engine_callsite=None,
                  source_location=None, binary_identity=None,
                  symbol_identity=None, source_revision=None,
                  path_mapping=None, evidence_refs=None, candidates=None):
    """Create one attribution record; never fabricate a missing identity."""
    level, _, limitations = evaluate_level(
        event_refs, api_call, engine_callsite, source_location,
        binary_identity, symbol_identity, source_revision, path_mapping,
        evidence_refs, candidates)
    status = "established" if level != "S0" else "not_established"
    return {
        "mappingId": _mapping_id(event_refs or []),
        "eventRefs": [dict(ref) for ref in (event_refs or [])],
        "highestVerifiedLevel": level,
        "mappingStatus": status,
        "apiCall": dict(api_call or {}),
        "engineCallsite": dict(engine_callsite or {}),
        "sourceLocation": dict(source_location or {}),
        "binaryIdentity": dict(binary_identity or {}),
        "symbolIdentity": dict(symbol_identity or {}),
        "sourceRevision": dict(source_revision or {}),
        "pathMapping": dict(path_mapping or {}),
        "candidates": list(candidates or []),
        "evidenceRefs": [dict(ref) for ref in (evidence_refs or [])],
        "limitations": limitations,
    }


def validate_mapping(mapping):
    """Reject a claimed level that the supplied identities cannot support."""
    if mapping["highestVerifiedLevel"] not in LEVELS:
        raise ValueError("invalid source attribution level")
    expected, _, _ = evaluate_level(
        mapping["eventRefs"], mapping["apiCall"] or None,
        mapping["engineCallsite"] or None, mapping["sourceLocation"] or None,
        mapping["binaryIdentity"] or None, mapping["symbolIdentity"] or None,
        mapping["sourceRevision"] or None, mapping["pathMapping"] or None,
        mapping["evidenceRefs"] or None, mapping.get("candidates"))
    if expected != mapping["highestVerifiedLevel"]:
        raise ValueError(
            f"claimed {mapping['highestVerifiedLevel']} but evidence supports {expected}")
    if mapping.get("sourceLocation", {}).get("file") and not mapping["evidenceRefs"]:
        raise ValueError("source location without evidence reference")
    return True
