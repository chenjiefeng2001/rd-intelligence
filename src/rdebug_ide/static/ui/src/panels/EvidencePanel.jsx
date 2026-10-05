import React from "react";
import { Panel, Section, Button, EmptyState } from "../components/primitives.jsx";

/**
 * Evidence ids and the grounded prompt.
 *
 * Copy availability follows the prompt that exists rather than the fact that a
 * diff happened, so an empty prompt cannot be copied as if it were real.
 */
export function EvidencePanel({ t, evidence, prompt, canCopy, copied, onOpen, onCopy }) {
  return (
    <Panel title={t("h", "evidence")} className="panel--evidence">
      <div data-testid="evidence">
        {evidence.length === 0 ? (
          <EmptyState hint={t("res", "hintEvidence")}>—</EmptyState>
        ) : (
          <div className="chips">
            {evidence.map((id) => (
              <button key={id} type="button" className="chip mono" onClick={() => onOpen(id)}>
                {id}
              </button>
            ))}
          </div>
        )}
      </div>

      <Section title={t("h", "prompt")}>
        <label className="sr-only" htmlFor="prompt">
          {t("h", "prompt")}
        </label>
        <textarea
          className="prompt"
          id="prompt"
          readOnly
          value={prompt}
          placeholder={t("res", "hint")}
          spellCheck={false}
        />
        <div className="row" style={{ marginTop: "var(--s-3)" }}>
          <Button id="btnCopy" onClick={onCopy} disabled={!canCopy}>
            {copied ? t("b", "copied") : t("b", "copy")}
          </Button>
          {copied ? <span className="muted" style={{ fontSize: 12 }}>{t("b", "copiedHint")}</span> : null}
        </div>
      </Section>
    </Panel>
  );
}