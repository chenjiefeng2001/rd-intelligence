# Diagnostic Report

schema: `rdebug-diagnostic-report/1`

capture: `N3-02.rdc`  
capture sha256: `None`  
analysis revision: `None`

## Executive Summary

status: `present`

```json
{
  "findingCount": 0,
  "anomalyCount": 0,
  "diagnosisCount": 0,
  "recommendationCount": 1,
  "highestSourceLevel": "S0",
  "overallStatus": "no_defect_reported"
}
```

## Analysis Scope

status: `present`

```json
{
  "capture": "N3-02.rdc",
  "tooling": "rdebug diagnostics rdebug-diagnostic-report/1",
  "sourceAttribution": [
    {
      "mappingId": "source-map-97d170e1550e",
      "eventRefs": [],
      "highestVerifiedLevel": "S0",
      "mappingStatus": "not_established",
      "apiCall": {},
      "engineCallsite": {},
      "sourceLocation": {},
      "binaryIdentity": {},
      "symbolIdentity": {},
      "sourceRevision": {},
      "pathMapping": {},
      "candidates": [],
      "evidenceRefs": [],
      "limitations": []
    }
  ],
  "highestLevel": "S0"
}
```

## Workload Overview

status: `present`

```json
{
  "resource": null,
  "summary": null,
  "accessCount": 0
}
```

## Evidence Coverage

status: `present`

```json
{
  "analysisStatus": null,
  "unresolved": [],
  "limitations": [
    {
      "category": "copy_sampling_dependency",
      "status": "not_established",
      "reason": "no CopyDst writer with PS_Resource readers on this resource"
    },
    {
      "category": "findings",
      "status": "not_established",
      "reason": "no rule was triggered by the supplied evidence"
    }
  ]
}
```

## Findings

status: `present`

## Diagnosis

status: `insufficient_evidence` — no anomaly triggered a diagnosis

```json
{
  "diagnoses": [],
  "diagnosisCount": 0,
  "observationOnly": false,
  "status": "not_established"
}
```

## Impact Analysis

status: `present`

```json
{
  "affectedResources": [],
  "affectedEvents": [],
  "claim": "event-order scope; no content-flow conclusion"
}
```

## Recommendations

status: `present`

### recommendation-b7e805a984a0

- action: `no_change`; status: `actionable`
- rationale: No finding was produced from the supplied evidence.
- findings: none

## Change Proposals

status: `insufficient_evidence` — no actionable change was proposed

```json
{
  "changePlans": [],
  "changePlanCount": 0,
  "status": "not_applicable"
}
```

## Verification Plan

status: `present`

```json
{
  "plans": [
    {
      "recommendationRef": "recommendation-b7e805a984a0",
      "changePlanRef": null,
      "steps": [
        "keep the original analysis output for comparison"
      ],
      "derivedFrom": []
    }
  ],
  "planCount": 1
}
```

## Limitations

status: `present`

```json
{
  "items": [
    {
      "category": "copy_sampling_dependency",
      "status": "not_established",
      "reason": "no CopyDst writer with PS_Resource readers on this resource"
    },
    {
      "category": "findings",
      "status": "not_established",
      "reason": "no rule was triggered by the supplied evidence"
    }
  ]
}
```

## Evidence Appendix

status: `present`

```json
{
  "evidenceRefs": [],
  "mappingIds": [
    "source-map-97d170e1550e"
  ],
  "analysisStatus": null
}
```

