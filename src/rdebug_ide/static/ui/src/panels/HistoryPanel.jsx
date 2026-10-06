import React from "react";
import { Panel, Section, Button, Badge } from "../components/primitives.jsx";
import {
  StatRow,
  ObservationTable,
  EndpointBreakdown,
  ErrorRanking,
  latency,
} from "../components/display.jsx";

/**
 * The recorded history of this session.
 *
 * Three states, kept visibly distinct because they mean different things:
 * not configured, still loading, and loaded-but-empty. Collapsing any two of
 * them produces a claim nobody can check -- an unconfigured store rendered as
 * "0 requests" reads as a measurement that was never taken.
 */
export function HistoryPanel({
  t,
  enabled,
  loading,
  rows,
  summary,
  store,
  scopePixel,
  failuresOnly,
  endpointFilter,
  scopeAvailable,
  scopePixelText,
  onRefresh,
  onToggleFailures,
  onToggleScope,
  onEndpoint,
}) {
  return (
    <Panel
      title={t("hist", "title")}
      className="panel--history"
      actions={
        <div className="row">
          {store ? (
            <Badge tone={store.dropped > 0 ? "fail" : "live"} dot>
              {store.rows + " " + t("hist", "rows")}
            </Badge>
          ) : null}
          <Button ghost onClick={onRefresh} disabled={!enabled || loading}>
            {t("hist", "refresh")}
          </Button>
        </div>
      }
    >
      {!enabled ? (
        <div className="alert alert--warn" role="status" data-testid="history-disabled">
          <span className="alert__icon" aria-hidden="true">
            i
          </span>
          <div className="alert__body">
            <b>{t("hist", "disabledTitle")}</b>
            <div className="alert__detail">{t("hist", "disabledHint")}</div>
          </div>
        </div>
      ) : (
        <>
          <StatRow stats={summarise(t, summary, store)} />

          <Section title={t("hist", "filters")}>
            <div className="filters">
              <label className="toggle">
                <input
                  type="checkbox"
                  id="histFailures"
                  checked={failuresOnly}
                  onChange={onToggleFailures}
                />
                <span>{t("hist", "onlyFailures")}</span>
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  id="histScope"
                  checked={scopePixel}
                  onChange={onToggleScope}
                  disabled={!scopeAvailable}
                />
                <span>
                  {t("hist", "scopePixel")}
                  {scopeAvailable ? (
                    <span className="mono muted"> {scopePixelText}</span>
                  ) : (
                    <span className="muted"> {t("hist", "scopeUnavailable")}</span>
                  )}
                </span>
              </label>
              <label className="select">
                <span className="sr-only" id="histEndpointLabel">
                  {t("hist", "endpoint")}
                </span>
                <select
                  id="histEndpoint"
                  aria-labelledby="histEndpointLabel"
                  value={endpointFilter}
                  onChange={(e) => onEndpoint(e.target.value)}
                >
                  <option value="">{t("hist", "anyEndpoint")}</option>
                  {(endpointsOf(summary) || []).map((e) => (
                    <option key={e} value={e}>
                      {e}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </Section>

          <Section title={t("hist", "observations")}>
            <ObservationTable t={t} rows={rows} loading={loading} />
          </Section>

          {summary && summary.byEndpoint && summary.byEndpoint.length ? (
            <Section title={t("hist", "byEndpoint")}>
              <EndpointBreakdown t={t} byEndpoint={summary.byEndpoint} />
            </Section>
          ) : null}

          {summary && summary.topErrors && summary.topErrors.length ? (
            <Section title={t("hist", "topErrors")}>
              <ErrorRanking t={t} topErrors={summary.topErrors} />
            </Section>
          ) : null}
        </>
      )}
    </Panel>
  );
}

/** Fold the server's aggregate into the shape the tiles need. */
function summarise(t, summary, store) {
  if (!summary) return null;
  return {
    requests: summary.requests ?? 0,
    failures: summary.failures ?? 0,
    avg: summary.latencyMs ? summary.latencyMs.avg : null,
    max: summary.latencyMs ? summary.latencyMs.max : null,
    dropped: (store && store.dropped) || summary.dropped || 0,
    labels: {
      requests: t("hist", "statRequests"),
      failures: t("hist", "statFailures"),
      avg: t("hist", "statAvg"),
      dropped: t("hist", "statDropped"),
    },
  };
}

function endpointsOf(summary) {
  if (!summary || !summary.byEndpoint) return [];
  return summary.byEndpoint.map((e) => e.endpoint);
}

export function scopeOf(a, b) {
  const parsed = (raw) => {
    const m = /^(-?\d+)\s*,\s*(-?\d+)$/.exec(String(raw || "").trim());
    return m ? { x: parseInt(m[1], 10), y: parseInt(m[2], 10) } : null;
  };
  return { a: parsed(a), b: parsed(b) };
}

export { latency };