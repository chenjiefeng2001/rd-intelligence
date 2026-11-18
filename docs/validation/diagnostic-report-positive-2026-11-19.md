# Diagnostic Report

schema: `rdebug-diagnostic-report/1`

capture: `a-d3d11-fixture.rdc`  
capture sha256: `None`  
analysis revision: `None`

## Executive Summary

status: `present`

```json
{
  "findingCount": 1,
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
  "capture": "a-d3d11-fixture.rdc",
  "tooling": "rdebug diagnostics rdebug-diagnostic-report/1",
  "sourceAttribution": [
    {
      "mappingId": "source-map-eca7092464fc",
      "eventRefs": [
        {
          "id": "18acf17fdcc8",
          "eventId": 2
        },
        {
          "id": "481a53da944d",
          "eventId": 11
        },
        {
          "id": "d86b76459c1c",
          "eventId": 12
        },
        {
          "id": "2e6e8ce977b7",
          "eventId": 13
        },
        {
          "id": "a8c169d1c83c",
          "eventId": 14
        },
        {
          "id": "510fd2660a66",
          "eventId": 15
        },
        {
          "id": "99d3f6d65c15",
          "eventId": 16
        },
        {
          "id": "5ec3369f5449",
          "eventId": 17
        },
        {
          "id": "d83343fc7f8d",
          "eventId": 18
        },
        {
          "id": "f50028eb8637",
          "eventId": 19
        },
        {
          "id": "5fa8da0380b4",
          "eventId": 20
        },
        {
          "id": "2d6040b847fc",
          "eventId": 21
        },
        {
          "id": "90dc63257edf",
          "eventId": 22
        },
        {
          "id": "5dd1d46a0008",
          "eventId": 23
        },
        {
          "id": "44d5d647aaca",
          "eventId": 24
        },
        {
          "id": "e5c0dcd675e1",
          "eventId": 25
        }
      ],
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
      "limitations": [
        "api_call_not_established",
        "application_symbols_not_available",
        "binary_identity_not_verified",
        "source_revision_not_verified"
      ]
    }
  ],
  "highestLevel": "S0"
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
    "usageCount": 257,
    "writerCount": 1,
    "readerCount": 256,
    "otherCount": 0,
    "firstWriterEventId": 2,
    "lastWriterEventId": 2,
    "lastReaderEventId": 266,
    "unknownCount": 0,
    "versionCount": 1
  },
  "accessCount": 257
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
          "capture": "D:\\renderdoc_no_mcp\\rdebug-validation\\captures\\a-d3d11-fixture.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:subresource",
          "source": "rdebug.analysis.resource_access",
          "id": "148612e21950",
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
          "capture": "D:\\renderdoc_no_mcp\\rdebug-validation\\captures\\a-d3d11-fixture.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:region",
          "source": "rdebug.analysis.resource_access",
          "id": "35b13b6705fa",
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
          "capture": "D:\\renderdoc_no_mcp\\rdebug-validation\\captures\\a-d3d11-fixture.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:coverage",
          "source": "rdebug.analysis.resource_access",
          "id": "d2a84234d0e0",
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
          "capture": "D:\\renderdoc_no_mcp\\rdebug-validation\\captures\\a-d3d11-fixture.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:alias",
          "source": "rdebug.analysis.resource_access",
          "id": "1367346e01a7",
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

### finding-589cd7790d0d

- kind: `observation`; status: `inferred`; severity: `info`; priority: `P3`
- summary: A CopyDst write precedes PS_Resource reads on one resource; the relationship is inferred from event order only.
- evidence: cf65b46ebe5e, 467baed67a2d, c800938c1ade, 62cf549b3c26
- disallowed: confirmed_content_propagation, shader_read_correctness, application_source_location

## Diagnosis

status: `insufficient_evidence` — no anomaly triggered a diagnosis

```json
{
  "diagnoses": [],
  "diagnosisCount": 0,
  "observationOnly": true,
  "status": "not_established"
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
    11,
    12,
    13
  ],
  "claim": "event-order scope; no content-flow conclusion"
}
```

## Recommendations

status: `present`

### recommendation-401f8208ed8e

- action: `no_change`; status: `actionable`
- rationale: Observations describe a normal resource dependency; no anomaly was detected and no code change is justified.
- findings: finding-589cd7790d0d

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
      "recommendationRef": "recommendation-401f8208ed8e",
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
    },
    {
      "category": "source_attribution",
      "status": "unknown",
      "reason": "api_call_not_established"
    },
    {
      "category": "source_attribution",
      "status": "unknown",
      "reason": "application_symbols_not_available"
    },
    {
      "category": "source_attribution",
      "status": "unknown",
      "reason": "binary_identity_not_verified"
    },
    {
      "category": "source_attribution",
      "status": "unknown",
      "reason": "source_revision_not_verified"
    }
  ]
}
```

## Evidence Appendix

status: `present`

```json
{
  "evidenceRefs": [
    "467baed67a2d",
    "62cf549b3c26",
    "c800938c1ade",
    "cf65b46ebe5e"
  ],
  "mappingIds": [
    "source-map-eca7092464fc"
  ],
  "analysisStatus": "partial"
}
```

