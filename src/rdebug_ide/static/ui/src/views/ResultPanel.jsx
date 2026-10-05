import React from "react";
import {
  Panel,
  KeyValues,
  EmptyState,
  Skeleton,
} from "../components/primitives.jsx";

/**
 * The two result shapes.
 *
 * Told apart by the payload's own shape rather than by a mode flag: a view told
 * "diff" while holding a trace would read undefined fields and render them
 * blank, which reads as "no result" rather than as a mistake.
 */
export function DiffView({ data, t }) {
  const first = data.firstDivergence || {};
  return (
    <>
      <KeyValues
        rows={[
          [t("diff", "comparison"), <StatusPill status={data.comparison} />],
          [t("diff", "firstDivergence"), first.layer ?? "—"],
          [t("diff", "good"), JSON.stringify(first.good ? first.good.value : null)],
          [t("diff", "bad"), JSON.stringify(first.bad ? first.bad.value : null)],
        ]}
      />
      <p className="panel__subtitle">{t("diff", "layers")}</p>
      <ul className="list" data-testid="layers">
        {data.layers.map((l) => (
          <li className="layer" key={l.layer}>
            <span className="layer__name mono">{l.layer}</span>
            <StatusPill status={l.status} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function TraceView({ data, t }) {
  const reads = data.edges.filter((e) => e.label === "reads");
  const written = data.edges.filter((e) => e.label === "written_by");
  const trunc = data.summary && data.summary.truncatedDraws;
  return (
    <>
      {trunc ? (
        // Truncation is reported by the semantic layer. Rendering the graph
        // without saying so would present an incomplete investigation as a
        // complete one.
        <div className="alert alert--warn" role="alert" data-testid="truncation">
          <span className="alert__icon" aria-hidden="true">
            !
          </span>
          <div className="alert__body">
            {t("trace", "truncated", { n: data.summary.modificationCount })}
          </div>
        </div>
      ) : null}
      <KeyValues
        rows={[
          [t("trace", "target"), data.summary.target ?? ""],
          [
            t("trace", "modifications"),
            data.summary.modificationCount +
              (trunc ? t("trace", "truncatedShort") : ""),
          ],
          [t("trace", "finalValue"), JSON.stringify(data.summary.finalValue)],
        ]}
      />
      <p className="panel__subtitle">{t("trace", "reads")}</p>
      {reads.length === 0 ? (
        <EmptyState hint={t("res", "noReads")}>—</EmptyState>
      ) : (
        <ul className="list" data-testid="reads">
          {reads.map((r) => (
            <li key={r.to}>
              <span className="mono">{r.to}</span>
              {written.some((w) => w.from === r.to) ? (
                <ul className="tree">
                  {written
                    .filter((w) => w.from === r.to)
                    .map((w) => (
                      <li key={w.to}>
                        {t("trace", "writtenBy", { id: w.to })}{" "}
                        <span className="muted">
                          ({w.evidence?.[0]?.data?.primitives ?? ""})
                        </span>
                      </li>
                    ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function StatusPill({ status }) {
  return <span className={"st st-" + status}>{status}</span>;
}

export function ResultPanel({ result, t }) {
  return (
    <Panel title={t("h", "result")} tone="result" className="panel--result">
      <div id="result" data-testid="result" aria-live="polite" aria-busy={result?.kind === "loading"}>
        <ResultBody result={result} t={t} />
      </div>
    </Panel>
  );
}

function ResultBody({ result, t }) {
  if (!result) {
    return <EmptyState hint={t("res", "hint")}>{t("res", "blank")}</EmptyState>;
  }
  if (result.kind === "loading") return <Skeleton />;
  if (result.kind === "failure") {
    return (
      <div className="alert alert--warn" role="alert" data-testid="failure-banner">
        <span className="alert__icon" aria-hidden="true">
          !
        </span>
        <div className="alert__body">
          <b>{result.text}</b>
          {result.detail ? <div className="alert__detail">{result.detail}</div> : null}
        </div>
      </div>
    );
  }
  if (result.data?.summary && result.data?.edges) {
    return <TraceView data={result.data} t={t} />;
  }
  return <DiffView data={result.data} t={t} />;
}
