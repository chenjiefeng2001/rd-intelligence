import React from "react";
import { EmptyState, Section } from "../components/primitives.jsx";

/**
 * Side-by-side semantic comparison.
 *
 * The verdict line says one word -- "same" or "different" -- and a single word is
 * exactly what cannot be checked. This shows, for every layer the server
 * compared, what A said, what B said, and the path it compared at, so a verdict
 * can be read against the evidence that produced it rather than believed.
 *
 * The contradiction guard is the reason this is not just prettier DiffView. A
 * summary that says "same" while a layer below it says "different" is worse than
 * a wrong answer, because it is self-contradicting: a reader who checks either
 * half alone finds nothing wrong. The server computes the verdict from the
 * layers, so this should be impossible; it is rendered as a loud failure rather
 * than smoothed over, because the moment it happens the verdict cannot be
 * trusted and saying so is the whole point of the panel.
 */
export function SemanticComparison({ data, t }) {
  const layers = Array.isArray(data.layers) ? data.layers : [];
  if (layers.length === 0) {
    return <EmptyState hint={t("sem", "noLayers")}>—</EmptyState>;
  }

  const verdict = data.comparison;
  const differing = layers.filter((l) => l.status === "different");
  const contradiction =
    (verdict === "same" && differing.length > 0) ||
    (verdict === "different" && differing.length === 0);

  return (
    <>
      {contradiction ? (
        <div className="alert alert--warn" role="alert" data-testid="sem-contradiction">
          <span className="alert__icon" aria-hidden="true">
            !
          </span>
          <div className="alert__body">
            <b>{t("sem", "contradiction")}</b>
            <div className="alert__detail">
              {t("sem", "contradictionDetail", {
                verdict: verdict ?? "?",
                differing: differing.length,
                layers: differing.map((l) => l.layer).join(", ") || "—",
              })}
            </div>
          </div>
        </div>
      ) : null}

      <Section title={t("sem", "perLayer")}>
        <div className="table-wrap">
          <table className="table" data-testid="sem-table">
            <thead>
              <tr>
                <th scope="col">{t("sem", "layer")}</th>
                <th scope="col">{t("sem", "verdict")}</th>
                <th scope="col">A</th>
                <th scope="col">B</th>
              </tr>
            </thead>
            <tbody>
              {layers.map((l) => {
                const isFirst =
                  Boolean(data.firstDivergence) &&
                  data.firstDivergence.layer === l.layer;
                return (
                  <tr
                    key={l.layer}
                    className={"sem-row" + (isFirst ? " sem-row--first" : "")}
                    data-testid="sem-row"
                  >
                    <th scope="row" className="sem-row__layer">
                      <span className="mono">{l.layer}</span>
                      {isFirst ? (
                        <span className="sem-row__flag">
                          {t("sem", "firstDiff")}
                        </span>
                      ) : null}
                      {l.path ? (
                        <span className="sem-row__path mono">{l.path}</span>
                      ) : null}
                    </th>
                    <td>
                      <span className={"st st-" + l.status}>{l.status}</span>
                    </td>
                    <td className="sem-row__value mono">
                      {render(l.good)}
                    </td>
                    <td className="sem-row__value mono">{render(l.bad)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}

/** One side of one layer. Absence is stated rather than rendered as blank. */
function render(side) {
  if (!side) return "—";
  const v = side.value;
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length === 0 ? "[]" : v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}