# Diagnostic Report

schema: `rdebug-diagnostic-report/1`

capture: `defect_frame11.rdc`  
capture sha256: `d9902fbcdc5a50805a107b120e183d94e54112f7d4bf1e153f69715c23a728c2`  
analysis revision: `6c9aeca159e7`

## Executive Summary

status: `present`

```json
{
  "findingCount": 2,
  "anomalyCount": 1,
  "diagnosisCount": 1,
  "recommendationCount": 1,
  "highestSourceLevel": "S4",
  "overallStatus": "diagnosis_in_progress"
}
```

## Analysis Scope

status: `present`

```json
{
  "capture": "defect_frame11.rdc",
  "tooling": "rdebug diagnostics rdebug-diagnostic-report/1",
  "sourceAttribution": [
    {
      "mappingId": "source-map-d512b704c877",
      "eventRefs": [
        {
          "id": "2678efade56c",
          "eventId": 2
        },
        {
          "id": "cec55242299e",
          "eventId": 11
        },
        {
          "id": "2678efade56c"
        },
        {
          "id": "cec55242299e"
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
        "file": "e-cases\\copy_content\\triangle_app_defect.cpp",
        "function": "main",
        "line": 133,
        "lineVerified": true,
        "buildMatchesSourceRevision": true
      },
      "binaryIdentity": {
        "verified": true,
        "sha256": "6c9aeca159e7c7094bb073bd30991ed255e40cbe83959c6a8d586d8a1c83b750"
      },
      "symbolIdentity": {
        "verified": true,
        "guid": "A143CE45-1EFC-475E-B226-649BAF87155A",
        "age": 3
      },
      "sourceRevision": {
        "verified": true,
        "sha256": "b70e4ab83be68fd61ba31eae18c2b236dc3f6a7e9ddfe05a6ef8d5ac3988170e"
      },
      "pathMapping": {},
      "candidates": [],
      "evidenceRefs": [
        {
          "id": "1b3f297252aa"
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
          "capture": "e-cases\\copy_content\\after\\defect_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:subresource",
          "source": "rdebug.analysis.resource_access",
          "id": "82790ab6d94c",
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
          "capture": "e-cases\\copy_content\\after\\defect_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:region",
          "source": "rdebug.analysis.resource_access",
          "id": "d12bb28740c0",
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
          "capture": "e-cases\\copy_content\\after\\defect_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:coverage",
          "source": "rdebug.analysis.resource_access",
          "id": "20f2bf8cc33f",
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
          "capture": "e-cases\\copy_content\\after\\defect_frame11.rdc",
          "resourceId": "ResourceId::47",
          "operation": "unresolved:alias",
          "source": "rdebug.analysis.resource_access",
          "id": "718010ebb6e9",
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
- evidence: ce658fe1842d, 641878c4fe76
- disallowed: confirmed_content_propagation, shader_read_correctness, application_source_location

### finding-5df58e3fdb07

- kind: `anomaly`; status: `inferred`; severity: `critical`; priority: `P0`
- summary: An independent pixel-history oracle reports that final shader output differs from the baseline beyond tolerance.
- evidence: 6b29336f9361, 15e585a45edd
- disallowed: confirmed_application_root_cause, content_flow_proven

## Diagnosis

status: `present`

```json
{
  "chains": [
    {
      "findingRef": "finding-5df58e3fdb07",
      "facts": [
        {
          "factId": "fact-7bc387676f89",
          "statement": "The uploaded resource content may not be the content the shader samples.",
          "evidenceStatus": "inferred",
          "evidenceRefs": [
            {
              "id": "6b29336f9361"
            },
            {
              "id": "15e585a45edd"
            }
          ],
          "sourceAnalysisRefs": [
            "finding-5df58e3fdb07"
          ],
          "limitations": [
            "event_order_only"
          ]
        }
      ],
      "hypotheses": [
        {
          "hypothesisId": "hypothesis-ec1658bc2461",
          "statement": "The uploaded resource content may not be the content the shader samples.",
          "status": "supported",
          "supportingEvidence": [
            "finding-5df58e3fdb07"
          ],
          "contradictingEvidence": [],
          "assumptions": [
            "the reported finding accurately reflects the capture"
          ],
          "missingEvidence": [
            "direct_content_flow_evidence"
          ],
          "discriminatingChecks": [
            "inspect original events named in evidenceRefs"
          ]
        },
        {
          "hypothesisId": "hypothesis-21394dae75de",
          "statement": "A different resource may be bound at the shader slot",
          "status": "candidate",
          "supportingEvidence": [],
          "contradictingEvidence": [],
          "assumptions": [
            "wrong_resource_binding"
          ],
          "missingEvidence": [
            "evidence_to_distinguish_wrong_resource_binding"
          ],
          "discriminatingChecks": [
            "compare descriptor resource ids at the sampling event"
          ]
        },
        {
          "hypothesisId": "hypothesis-70737400151e",
          "statement": "The copy source may carry unintended content",
          "status": "candidate",
          "supportingEvidence": [],
          "contradictingEvidence": [],
          "assumptions": [
            "wrong_upload_source"
          ],
          "missingEvidence": [
            "evidence_to_distinguish_wrong_upload_source"
          ],
          "discriminatingChecks": [
            "inspect the source resource contents before the copy"
          ]
        },
        {
          "hypothesisId": "hypothesis-3907da57d4ca",
          "statement": "The two captures may differ outside the suspected change",
          "status": "candidate",
          "supportingEvidence": [],
          "contradictingEvidence": [],
          "assumptions": [
            "replay_nondeterminism"
          ],
          "missingEvidence": [
            "evidence_to_distinguish_replay_nondeterminism"
          ],
          "discriminatingChecks": [
            "re-run the baseline capture twice and compare the oracle"
          ]
        }
      ],
      "alternatives": [
        {
          "hypothesisId": "hypothesis-21394dae75de",
          "statement": "A different resource may be bound at the shader slot",
          "status": "candidate",
          "supportingEvidence": [],
          "contradictingEvidence": [],
          "assumptions": [
            "wrong_resource_binding"
          ],
          "missingEvidence": [
            "evidence_to_distinguish_wrong_resource_binding"
          ],
          "discriminatingChecks": [
            "compare descriptor resource ids at the sampling event"
          ]
        },
        {
          "hypothesisId": "hypothesis-70737400151e",
          "statement": "The copy source may carry unintended content",
          "status": "candidate",
          "supportingEvidence": [],
          "contradictingEvidence": [],
          "assumptions": [
            "wrong_upload_source"
          ],
          "missingEvidence": [
            "evidence_to_distinguish_wrong_upload_source"
          ],
          "discriminatingChecks": [
            "inspect the source resource contents before the copy"
          ]
        },
        {
          "hypothesisId": "hypothesis-3907da57d4ca",
          "statement": "The two captures may differ outside the suspected change",
          "status": "candidate",
          "supportingEvidence": [],
          "contradictingEvidence": [],
          "assumptions": [
            "replay_nondeterminism"
          ],
          "missingEvidence": [
            "evidence_to_distinguish_replay_nondeterminism"
          ],
          "discriminatingChecks": [
            "re-run the baseline capture twice and compare the oracle"
          ]
        }
      ],
      "relations": [
        {
          "type": "supported_by",
          "from": "finding-5df58e3fdb07",
          "to": "fact-7bc387676f89"
        },
        {
          "type": "explained_by",
          "from": "finding-5df58e3fdb07",
          "to": "hypothesis-ec1658bc2461"
        },
        {
          "type": "challenged_by",
          "from": "hypothesis-ec1658bc2461",
          "to": "hypothesis-21394dae75de"
        },
        {
          "type": "evaluated_as",
          "from": "hypothesis-ec1658bc2461",
          "to": "conclusion-ccd063cbc97f"
        }
      ],
      "conclusion": {
        "conclusionId": "conclusion-ccd063cbc97f",
        "status": "established",
        "hypothesisRefs": [
          "hypothesis-ec1658bc2461"
        ],
        "factRefs": [
          "fact-7bc387676f89"
        ],
        "reason": "an independent oracle and verified source mapping establish the diagnosis",
        "alternativeRefs": [
          "hypothesis-21394dae75de",
          "hypothesis-70737400151e",
          "hypothesis-3907da57d4ca"
        ],
        "probabilisticConfidence": null
      }
    }
  ],
  "count": 1
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

### recommendation-5f7e04f2e557

- action: `code_change`; status: `actionable`
- rationale: Established diagnosis with a verified source mapping; a scoped code change can be proposed at the verified level.
- findings: finding-5df58e3fdb07

## Change Proposals

status: `present`

```json
{
  "changePlans": [
    {
      "changePlanId": "change-ade55274be61",
      "recommendationRef": "recommendation-5f7e04f2e557",
      "target": "e-cases\\copy_content\\triangle_app_defect.cpp",
      "scope": {
        "file": "e-cases\\copy_content\\triangle_app_defect.cpp",
        "function": "main",
        "line": 133,
        "verifiedLevel": "S4"
      },
      "affectedPaths": [
        "e-cases\\copy_content\\triangle_app_defect.cpp"
      ],
      "reason": "Established diagnosis with a verified source mapping; a scoped code change can be proposed at the verified level.",
      "preconditions": [
        "confirm the diagnosis against the capture"
      ],
      "expectedOutcome": {
        "state": "anomaly_no_longer_reproduced"
      },
      "compatibilityRisk": {
        "sourcePrecision": "S4"
      },
      "rollbackStrategy": {},
      "status": "planned"
    }
  ],
  "changePlanCount": 1,
  "status": "planned"
}
```

## Verification Plan

status: `present`

```json
{
  "plans": [
    {
      "recommendationRef": "recommendation-5f7e04f2e557",
      "changePlanRef": "change-ade55274be61",
      "steps": [
        "re-run the resource access index and dependency builder",
        "assert the dependency set stays observation-only unless new evidence appears",
        "replay the after-fix capture and compare shader output with the baseline oracle",
        "assert the independent content comparison status is 'same' at the target event",
        "assert no new anomaly finding appears in the after-fix report",
        "assert no new writer-to-reader anomaly is introduced",
        "run the existing unit, transport and cold-warm controls"
      ],
      "derivedFrom": [
        "copy_sampling_dependency",
        "sampled_content_mismatch"
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
    "15e585a45edd",
    "641878c4fe76",
    "6b29336f9361",
    "ce658fe1842d"
  ],
  "mappingIds": [
    "source-map-d512b704c877"
  ],
  "analysisStatus": "partial"
}
```

