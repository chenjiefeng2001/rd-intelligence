import React from "react";
import { Panel, EmptyState, Section } from "../components/primitives.jsx";

/**
 * The evidence chain: how this answer was reached.
 *
 * A diff answers "are these two pixels the same" and stops. That is a conclusion
 * with the reasoning removed, and for a debugging tool the reasoning is the
 * useful part -- a pixel difference with no chain behind it cannot be acted on.
 * The server already returns the chain in both payloads, so this panel walks it
 * rather than reconstructing anything.
 *
 * Diff shape: `layers[]` in comparison order, and `firstDivergence` naming the
 * layer where the two sides parted, with the evidence for each side inside it.
 * Trace shape: `edges[]`, each hop carrying the evidence for that hop.
 *
 * Told apart by the payload's own shape, never by a mode flag -- the same
 * decision ResultPanel makes, for the same reason: a view told "diff" while
 * holding a trace would read undefined fields and render them blank, which
 * reads as "no data" rather than as a mistake.
 */
export function EvidenceChain({ result, t, onOpen }) {
  return (
    <Panel title={t("h", "chain")} className="panel--chain">
      <div data-testid="chain">
        <ChainBody result={result} t={t} onOpen={onOpen} />
      </div>
    </Panel>
  );
}

function ChainBody({ result, t, onOpen }) {
  if (!result || result.kind === "loading") {
    return (
      <EmptyState hint={t("chain", "hint")}>{t("res", "blank")}</EmptyState>
    );
  }
  if (result.kind === "failure") {
    // A failed query has no chain. Saying so is better than showing the chain
    // of the last query that worked, which would look like an answer.
    return <EmptyState hint={t("chain", "noChainOnFailure")}>—</EmptyState>;
  }
  const data = result.data || {};
  if (Array.isArray(data.layers)) {
    return <DiffChain data={data} t={t} onOpen={onOpen} />;
  }
  if (Array.isArray(data.edges)) {
    return <TraceChain data={data} t={t} onOpen={onOpen} />;
  }
  return (
    <EmptyState hint={t("chain", "notAQuery")}>{t("res", "blank")}</EmptyState>
  );
}

/** One observation, and where it came from. */
function EvidenceRow({ ev, t, onOpen }) {
  if (!ev) return null;
  const openable = Boolean(ev.resourceId) && Boolean(onOpen);
  const title = [
    ev.operation,
    ev.source,
    ev.eventId != null ? t("chain", "atEvent", { id: ev.eventId }) : null,
    ev.resourceId,
  ]
    .filter(Boolean)
    .join("  ·  ");
  return (
    <li className="chain__ev" data-testid="chain-evidence">
      <span className="chain__op mono">{ev.operation || "—"}</span>
      <span className="chain__src muted">{ev.source || ""}</span>
      {openable ? (
        <button
          type="button"
          className="chip chip--link mono"
          title={title}
          onClick={() => onOpen(ev.resourceId)}
        >
          {ev.resourceId}
        </button>
      ) : (
        <span className="muted mono">{ev.resourceId || ""}</span>
      )}
      <span className="chain__id mono muted" title={title}>
        {ev.id}
      </span>
    </li>
  );
}

function EvidenceList({ items, t, onOpen, emptyHint }) {
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  if (list.length === 0) {
    return <p className="chain__none muted">{emptyHint || t("chain", "noEvidence")}</p>;
  }
  return (
    <ul className="chain__evlist">
      {list.map((ev, i) => (
        <EvidenceRow key={ev.id || i} ev={ev} t={t} onOpen={onOpen} />
      ))}
    </ul>
  );
}

function DiffChain({ data, t, onOpen }) {
  const layers = data.layers || [];
  const first = data.firstDivergence || null;
  return (
    <>
      <Section title={t("chain", "ladder")}>
        {/* The ladder is the reasoning in order: each layer is a check, and the
            chain ends at the first one that parted. */}
        <ol className="chain__ladder" data-testid="chain-ladder">
          {layers.map((l) => {
            const isFirst = Boolean(first && first.layer === l.layer);
            return (
              <li
                key={l.layer}
                className={
                  "chain__step" + (isFirst ? " chain__step--first" : "")
                }
                data-testid="chain-step"
              >
                <span className={"st st-" + l.status}>{l.status}</span>
                <span className="chain__stepName mono">{l.layer}</span>
                {isFirst ? (
                  <span className="chain__marker">{t("chain", "firstHere")}</span>
                ) : null}
              </li>
            );
          })}
        </ol>
      </Section>

      {first ? (
        <Section title={t("chain", "divergence")}>
          <p className="chain__path mono" data-testid="chain-path">
            {first.path || first.layer}
          </p>
          <div className="chain__sides">
            <div className="chain__side chain__side--good">
              <p className="chain__sideLabel">
                {t("diff", "good")} · A
              </p>
              <p className="chain__value mono">{render(first.good)}</p>
              <EvidenceList
                items={first.good && first.good.evidence}
                t={t}
                onOpen={onOpen}
              />
            </div>
            <div className="chain__side chain__side--bad">
              <p className="chain__sideLabel">
                {t("diff", "bad")} · B
              </p>
              <p className="chain__value mono">{render(first.bad)}</p>
              <EvidenceList
                items={first.bad && first.bad.evidence}
                t={t}
                onOpen={onOpen}
              />
            </div>
          </div>
        </Section>
      ) : (
        // No divergence is itself the finding, and it needs saying: an empty
        // section here would read as "not investigated".
        <p className="chain__none muted" data-testid="chain-no-divergence">
          {data.comparison === "same"
            ? t("chain", "identical")
            : t("chain", "noDivergence")}
        </p>
      )}
    </>
  );
}

function TraceChain({ data, t, onOpen }) {
  const edges = data.edges || [];
  return (
    <>
      <Section title={t("chain", "path")}>
        {/* Each hop is one causal step: what wrote or fed the next thing, and
            the observation that establishes it. */}
        <ol className="chain__path" data-testid="chain-path">
          {edges.map((e, i) => (
            <li className="chain__hop" key={e.from + ">" + e.to + i}>
              <div className="chain__hopHead">
                <span className="chain__node mono">{e.from}</span>
                <span className="chain__arrow" aria-hidden="true">
                  <span className="chain__label">{e.label}</span>
                  →
                </span>
                <span className="chain__node mono">{e.to}</span>
              </div>
              <EvidenceList
                items={e.evidence}
                t={t}
                onOpen={onOpen}
                emptyHint={t("chain", "noHopEvidence")}
              />
            </li>
          ))}
        </ol>
      </Section>
    </>
  );
}

/** A compared value, rendered so an empty list is not mistaken for a blank. */
function render(side) {
  if (!side) return "—";
  const v = side.value;
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length === 0 ? "[]" : v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}