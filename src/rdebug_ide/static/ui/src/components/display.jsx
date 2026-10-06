import React from "react";
import { EmptyState, Skeleton } from "./primitives.jsx";

/**
 * Display primitives for the history panel.
 *
 * Kept apart from the interactive primitives because these render data someone
 * else produced. The difference matters: a stat tile and a filter control have
 * different failure modes, and putting them in the same file is how a read-only
 * surface quietly grows a side effect.
 */

/**
 * One number with its label. The value is monospaced and tabular so a column of
 * them lines up: a latency figure that shifts as digits change is a figure
 * people stop trusting mid-scan.
 */
export function StatTile({ label, value, tone, hint }) {
  return (
    <div className={"stat stat--" + (tone || "plain")} data-testid="stat">
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
      {hint ? <span className="stat__hint">{hint}</span> : null}
    </div>
  );
}

export function StatRow({ stats }) {
  if (!stats) return null;
  const tiles = [];
  tiles.push(
    <StatTile key="requests" label={stats.labels.requests} value={stats.requests} />,
    <StatTile
      key="failures"
      label={stats.labels.failures}
      value={stats.failures}
      tone={stats.failures > 0 ? "bad" : "plain"}
    />,
    <StatTile
      key="avg"
      label={stats.labels.avg}
      value={stats.avg === null ? "—" : stats.avg + " ms"}
      hint={stats.max === null ? null : "max " + stats.max + " ms"}
    />,
    <StatTile
      key="dropped"
      label={stats.labels.dropped}
      value={stats.dropped}
      tone={stats.dropped > 0 ? "warn" : "plain"}
    />,
  );
  return (
    <div className="stats" data-testid="stats">
      {tiles}
    </div>
  );
}

/** Milliseconds, or a dash when there was nothing to average. */
export function latency(value) {
  if (value === null || value === undefined) return "—";
  if (value < 1) return "<1 ms";
  return Math.round(value) + " ms";
}

export function clockOf(ts) {
  const date = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    pad(date.getHours()) +
    ":" +
    pad(date.getMinutes()) +
    ":" +
    pad(date.getSeconds())
  );
}

/**
 * The recorded observations.
 *
 * A table rather than cards: this is a list of comparable records, and a
 * column of cards makes scanning for one row slower than a row of columns does.
 * The request is rendered verbatim rather than prettified -- the stored value is
 * what was sent, and reformatting it here would hide the difference between
 * `a=320,240` and a request that was actually about something else.
 */
export function ObservationTable({ t, rows, loading, onOpen }) {
  if (loading) return <Skeleton rows={4} testId="history-loading" />;
  if (!rows.length) {
    return <EmptyState hint={t("hist", "emptyHint")}>{t("hist", "empty")}</EmptyState>;
  }
  return (
    <div className="table-wrap">
      <table className="table" data-testid="history-table">
        <thead>
          <tr>
            <th scope="col">{t("hist", "colTime")}</th>
            <th scope="col">{t("hist", "colEndpoint")}</th>
            <th scope="col">{t("hist", "colStatus")}</th>
            <th scope="col">{t("hist", "colLatency")}</th>
            <th scope="col">{t("hist", "colRequest")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-testid="history-row">
              <td className="mono nowrap">{clockOf(row.ts)}</td>
              <td className="mono">{row.endpoint}</td>
              <td>
                <StatusChip ok={row.ok} status={row.status} />
              </td>
              <td className="mono nowrap">{latency(row.latency_ms)}</td>
              <td className="mono request">
                {describe(row.query)}
                {row.error ? (
                  <span className="row__error" title={row.error}>
                    {t("hist", "errored")}
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.some((r) => r.summary && Object.keys(r.summary).length) ? null : null}
    </div>
  );
}

function StatusChip({ ok, status }) {
  // Both facts are shown. A row that failed with HTTP 200 is the documented
  // trap, so a chip reading only "200" would let the most interesting failure
  // in this table look like a success.
  return (
    <span className={"chip-status " + (ok ? "ok" : "bad")}>
      <span className="chip-status__mark" aria-hidden="true">
        {ok ? "✓" : "✕"}
      </span>
      <span className="mono">{status ?? "—"}</span>
      <span className="sr-only">{ok ? "ok" : "error"}</span>
    </span>
  );
}

/** A compact, faithful rendering of the request that was sent. */
export function describe(query) {
  const entries = Object.entries(query || {});
  if (!entries.length) return "—";
  return entries
    .map(([k, v]) => {
      if (Array.isArray(v)) {
        return (
          k + "=" + (v.length === 1 ? String(v[0]) : "[" + v.join(" ") + "]")
        );
      }
      return k + "=" + String(v);
    })
    .join(" ");
}

/** The endpoint breakdown. Ordered by the server, not re-sorted here. */
export function EndpointBreakdown({ t, byEndpoint }) {
  if (!byEndpoint || !byEndpoint.length) return null;
  const worst = Math.max(...byEndpoint.map((e) => e.count));
  return (
    <div className="breakdown" data-testid="breakdown">
      {byEndpoint.map((e) => (
        <div className="breakdown__row" key={e.endpoint}>
          <span className="mono breakdown__name">{e.endpoint}</span>
          <span className="breakdown__bar">
            <span
              className="breakdown__fill"
              style={{ width: Math.round((e.count / worst) * 100) + "%" }}
            />
          </span>
          <span className="mono breakdown__count">{e.count}</span>
          {e.failures > 0 ? (
            <span className="breakdown__fail mono">{e.failures}</span>
          ) : null}
        </div>
      ))}
      <p className="sr-only">{t("hist", "breakdownLabel")}</p>
    </div>
  );
}

export function ErrorRanking({ t, topErrors }) {
  if (!topErrors || !topErrors.length) return null;
  return (
    <ul className="errors" data-testid="top-errors">
      {topErrors.map((e) => (
        <li key={e.error} className="errors__item">
          <span className="mono errors__count">{e.count}</span>
          <span className="errors__text" title={e.error}>
            {e.error}
          </span>
        </li>
      ))}
      <li className="sr-only">{t("hist", "errorsLabel")}</li>
    </ul>
  );
}