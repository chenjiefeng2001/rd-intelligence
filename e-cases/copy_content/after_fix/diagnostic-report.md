# Diagnostic Report

schema: `rdebug-diagnostic-report/1`

capture: `fixed_frame11.rdc`  
capture sha256: `ee062c02a98fd036c2e4663e1ce1961354f05c3f3764068b9d7214f92f67c790`  
analysis revision: `9e37d2be2360`

## Executive Summary

status: `present`

```json
{
  "findingCount": 1,
  "anomalyCount": 0,
  "diagnosisCount": 0,
  "recommendationCount": 1,
  "highestSourceLevel": "S4",
  "overallStatus": "no_defect_reported"
}
```

## Analysis Scope

status: `present`

```json
{
  "capture": "fixed_frame11.rdc",
  "tooling": "rdebug diagnostics rdebug-diagnostic-report/1",
  "sourceAttribution": [
    {
      "mappingId": "source-map-d9e21762c0cc",
      "eventRefs": [
        {
          "id": "6d3293a5cdb3",
          "eventId": 2
        },
        {
          "id": "9478e783dc1c",
          "eventId": 11
        },
        {
          "id": "6d3293a5cdb3"
        },
        {
          "id": "9478e783dc1c"
        }
      ],
      "highestVerifiedLevel": "S4",
      "mappingStatus": "established",
      "apiCall": {
        "name": "CopyResource",
        "eventId": 2
      },
      "engineCallsite": {
        "function": "main",
        "module": "triangle_defect.exe"
      },
      "sourceLocation": {
        "file": "e-cases\\copy_content\\triangle_app_fixed.cpp",
        "function": "main",
        "line": 133,
        "lineVerified": true,
        "buildMatchesSourceRevision": true
      },
      "binaryIdentity": {
        "verified": true,
        "sha256": "9e37d2be236049a8d84cef05f50617487c00030e0e565d659e25b1177ecfac21"
      },
      "symbolIdentity": {
        "verified": true,
        "guid": "3E240F3A-45D8-4DBB-8784-200CE3E2007A",
        "age": 3
      },
      "sourceRevision": {
        "verified": true,
        "sha256": "0f79996a5d38820b0814adf8d6e567d4854328f72e06b79af204e8f6ac903640"
      },
      "pathMapping": {},
      "candidates": [],
      "evidenceRefs": [
        {
          "id": "9e71a3b72f49"
        }
      ],
      "limitations": []
    }
  ],
  "highestLevel": "S4"
}
```

## Workload Overview

status: `present`

```json
{
  "resource": {
    "id": "ResourceId::47",
    "name": ""
  },
  "summary": {
    "usageCount": 2,
    "writerCount": 1,
    "readerCount": 1,
    "otherCount": 0,
    "firstWriterEventId": 2,
    "lastWriterEventId": 2,
    "lastReaderEventId": 11,
    "unknownCount": 0,
    "versionCount": 1
  },
  "accessCount": 2
}
```

## Evidence Coverage

status: `present`

```json
{
  "analysisStatus": "partial",
  "unresolved": [
    {
      "field": "subresource",
      "reason": "ReplayController.GetUsage does not expose mip/layer/slice",
      "status": "unknown",
      "evidence": [
        {
          "capture": "e-cases\\copy_content\\after_fix\\fixed_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:subresource",
          "source": "rdebug.analysis.resource_access",
          "id": "99e21a61ba8b",
          "status": "unknown"
        }
      ]
    },
    {
      "field": "region",
      "reason": "ReplayController.GetUsage does not expose a written region",
      "status": "unknown",
      "evidence": [
        {
          "capture": "e-cases\\copy_content\\after_fix\\fixed_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:region",
          "source": "rdebug.analysis.resource_access",
          "id": "9dd75ddb0125",
          "status": "unknown"
        }
      ]
    },
    {
      "field": "coverage",
      "reason": "ReplayController.GetUsage does not expose full vs partial coverage",
      "status": "unknown",
      "evidence": [
        {
          "capture": "e-cases\\copy_content\\after_fix\\fixed_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:coverage",
          "source": "rdebug.analysis.resource_access",
          "id": "4b26f868a844",
          "status": "unknown"
        }
      ]
    },
    {
      "field": "alias",
      "reason": "equal resource ids do not prove physical memory aliasing",
      "status": "unknown",
      "evidence": [
        {
          "capture": "e-cases\\copy_content\\after_fix\\fixed_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:alias",
          "source": "rdebug.analysis.resource_access",
          "id": "858d803027db",
          "status": "unknown"
        }
      ]
    }
  ],
  "limitations": [
    {
      "category": "subresource",
      "status": "unknown",
      "reason": "ReplayController.GetUsage does not expose mip/layer/slice"
    },
    {
      "category": "region",
      "status": "unknown",
      "reason": "ReplayController.GetUsage does not expose a written region"
    },
    {
      "category": "coverage",
      "status": "unknown",
      "reason": "ReplayController.GetUsage does not expose full vs partial coverage"
    },
    {
      "category": "alias",
      "status": "unknown",
      "reason": "equal resource ids do not prove physical memory aliasing"
    }
  ]
}
```

## Findings

status: `present`

### finding-5d8274009073

- kind: `observation`; status: `inferred`; severity: `info`; priority: `P3`
- summary: A CopyDst write precedes PS_Resource reads on one resource; the relationship is inferred from event order only.
- evidence: 457dd37070e5, ae71bb62c778
- disallowed: confirmed_content_propagation, shader_read_correctness, application_source_location

## Diagnosis

status: `insufficient_evidence` — no anomaly triggered a diagnosis

```json
{
  "chains": [],
  "count": 0
}
```

## Impact Analysis

status: `present`

```json
{
  "affectedResources": [
    "ResourceId::47"
  ],
  "affectedEvents": [
    2,
    11
  ],
  "claim": "event-order scope; no content-flow conclusion"
}
```

## Recommendations

status: `present`

### recommendation-da387800ed6b

- action: `no_change`; status: `actionable`
- rationale: Observations describe a normal resource dependency; no anomaly was detected and no code change is justified.
- findings: finding-5d8274009073

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
      "recommendationRef": "recommendation-da387800ed6b",
      "changePlanRef": null,
      "steps": [
        "keep the original analysis output for comparison"
      ],
      "derivedFrom": [
        "copy_sampling_dependency"
      ]
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
      "category": "subresource",
      "status": "unknown",
      "reason": "ReplayController.GetUsage does not expose mip/layer/slice"
    },
    {
      "category": "region",
      "status": "unknown",
      "reason": "ReplayController.GetUsage does not expose a written region"
    },
    {
      "category": "coverage",
      "status": "unknown",
      "reason": "ReplayController.GetUsage does not expose full vs partial coverage"
    },
    {
      "category": "alias",
      "status": "unknown",
      "reason": "equal resource ids do not prove physical memory aliasing"
    }
  ]
}
```

## Evidence Appendix

status: `present`

```json
{
  "evidenceRefs": [
    "457dd37070e5",
    "ae71bb62c778"
  ],
  "mappingIds": [
    "source-map-d9e21762c0cc"
  ],
  "analysisStatus": "partial"
}
```

