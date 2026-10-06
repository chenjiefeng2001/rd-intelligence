import React from "react";
import { Panel, EmptyState, Button } from "../components/primitives.jsx";

/**
 * What the server announced, in arrival order.
 *
 * This is the instrument for the tool itself. Every other panel shows what the
 * user asked and what came back; this one shows what the server said happened,
 * including the parts the UI acts on silently -- a resync, a replayed revision,
 * a frame that arrived while a query was in flight. When a debug tool and its
 * own behaviour disagree, this is the panel that says which one is lying.
 *
 * Newest first, and bounded at both ends: the list is capped in the store so a
 * session that runs for hours cannot grow it without limit, and the rendered
 * window is capped in CSS so it cannot push the panels below it down the page.
 * Oldest entries fall off the top, which is stated rather than implied.
 */
export function EventLog({ events, dropped, filter, onFilter, onClear, t }) {
  // Newest first. Reversed here rather than by unrolling the store, so the
  // store keeps arrival order (which is what a filter and a clear operate on)
  // while the reading order is the one a reader wants.
  const rows = events
    .filter((e) => filter === "all" || group(e.kind) === filter)
    .slice()
    .reverse();

  return (
    <Panel
      title={t("h", "log")}
      className="panel--log"
      actions={
        <div className="row">
          <label className="select">
            <span className="sr-only">{t("log", "filter")}</span>
            <select
              id="logFilter"
              value={filter}
              onChange={(e) => onFilter(e.target.value)}
            >
              <option value="all">{t("log", "all")}</option>
              <option value="query">{t("log", "queries")}</option>
              <option value="lifecycle">{t("log", "lifecycle")}</option>
              <option value="gap">{t("log", "gaps")}</option>
            </select>
          </label>
          <Button id="btnLogClear" ghost onClick={onClear} disabled={events.length === 0}>
            {t("log", "clear")}
          </Button>
        </div>
      }
    >
      <div data-testid="log">
        {rows.length === 0 ? (
          <EmptyState hint={t("log", "hint")}>—</EmptyState>
        ) : (
          <>
            <ol className="log__list" data-testid="log-list">
              {rows.map((e) => (
                <li className="log__row" key={e.seq} data-testid="log-row">
                  <span className="log__rev mono" title={t("log", "revision")}>
                    {e.revision != null ? "#" + e.revision : "—"}
                  </span>
                  <span className={"log__kind log__kind--" + group(e.kind)}>
                    {e.kind}
                  </span>
                  <span className="log__detail mono">{describe(e, t)}</span>
                  <span className="log__time mono muted">{clock(e.at)}</span>
                </li>
              ))}
            </ol>
            {/* Stating the cap: a list that silently forgets is a list whose
                silence is indistinguishable from an idle server. */}
            <p className="log__foot muted" data-testid="log-foot">
              {events.length > 0
                ? t("log", "holding", { n: events.length })
                : ""}
              {dropped > 0 ? " " + t("log", "dropped", { n: dropped }) : ""}
            </p>
          </>
        )}
      </div>
    </Panel>
  );
}

/** Which filter a kind belongs to. `gap` is separated because a resync means
 *  the client missed something, which is the one entry worth noticing. */
function group(kind) {
  if (kind === "query") return "query";
  if (kind === "resync") return "gap";
  return "lifecycle";
}

function describe(e, t) {
  const d = e.detail;
  if (!d) return "";
  if (typeof d === "string") return d;
  if (e.kind === "query") {
    const bits = [d.endpoint];
    if (d.status != null) bits.push("→" + d.status);
    if (d.ok === false) bits.push(t("log", "failed"));
    if (d.recorded === false) bits.push(t("log", "notRecorded"));
    if (d.latencyMs != null) bits.push(d.latencyMs + "ms");
    return bits.filter(Boolean).join("  ");
  }
  if (e.kind === "configured") return String(d);
  return "";
}

function clock(ms) {
  if (!ms) return "";
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
}