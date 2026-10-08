import React from "react";
import {
  Panel,
  Section,
  KeyValues,
  EmptyState,
  Skeleton,
} from "../components/primitives.jsx";
import { SemanticComparison } from "./SemanticComparison.jsx";

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
      <SemanticComparison data={data} t={t} />
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

/**
 * The resource view.
 *
 * A third result shape, not a flavour of one of the other two. `/api/resource`
 * answers with `{resource, contextEventId, writers, readers, other, summary,
 * evidence}` -- it has a `summary` but no `edges` and no `layers`. Dispatching
 * on `summary && edges` therefore sent it to DiffView, which read
 * `data.layers.map` and threw. React unmounts the tree on an uncaught render
 * error, so opening any resource id -- from the evidence chips or from the
 * chain -- blanked the page. It is recorded here because the shape was assumed
 * to be one of two, and nothing tested the third.
 */
export function ResourceView({ data, t }) {
  const s = data.summary || {};
  // `resource` arrives as `{id, name}`, not as a string. Rendering it as a child
  // is what produced React error #31 and a blank page; naming the two fields is
  // both the fix and the honest description of what came back.
  const res = data.resource;
  const resourceId =
    res == null ? "—" : typeof res === "string" ? res : res.id || "—";
  const resourceName = res && typeof res === "object" ? res.name : null;
  const groups = [
    ["write", data.writers, t("res", "writers")],
    ["read", data.readers, t("res", "readers")],
    ["other", data.other, t("res", "other")],
  ];
  return (
    <>
      <KeyValues
        rows={[
          [t("res", "resource"), resourceId],
          ...(resourceName ? [[t("res", "resourceName"), resourceName]] : []),
          [t("res", "usageCount"), String(s.usageCount ?? 0)],
          [
            t("res", "contextEid"),
            data.contextEventId != null ? String(data.contextEventId) : "—",
          ],
        ]}
      />
      {groups.map(([kind, list, label]) => (
        <Section key={kind} title={label + " (" + ((list && list.length) || 0) + ")"}>
          {!list || list.length === 0 ? (
            <EmptyState>{t("res", "noneInGroup")}</EmptyState>
          ) : (
            <ul className="list" data-testid={"resource-" + kind}>
              {list.map((item, i) => (
                <li key={item.eventId != null ? item.eventId : i}>
                  <span className="mono">
                    {t("res", "event")} {item.eventId}
                  </span>
                  <span className="muted mono"> {item.usage || "—"}</span>
                  {item.actionName ? (
                    <span className="muted"> {item.actionName}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Section>
      ))}
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
  // Told apart by the payload's own shape, and every shape is handled
  // explicitly. The fallback is an empty state rather than a guess: a view
  // handed a shape it does not know must say so, because reading undefined
  // fields out of it throws, and a throw here unmounts the whole page.
  const data = result.data || {};
  if (Array.isArray(data.edges)) return <TraceView data={data} t={t} />;
  if (Array.isArray(data.writers) || Array.isArray(data.readers)) {
    return <ResourceView data={data} t={t} />;
  }
  if (Array.isArray(data.layers)) return <DiffView data={data} t={t} />;
  return (
    <EmptyState hint={t("res", "unknownShape")}>{t("res", "blank")}</EmptyState>
  );
}
