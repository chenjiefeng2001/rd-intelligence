import React from "react";
import { Panel, Section, Field, Checkbox, Button, Badge } from "../components/primitives.jsx";

/**
 * The query form.
 *
 * Diff is the primary action: this page exists to compare two pixels, and the
 * trace is the follow-up. Trace and prompt are secondary. The visual weight
 * matches that rather than being arbitrary.
 */
export function QueryPanel({
  t,
  a,
  b,
  deep,
  eid,
  busy,
  onA,
  onB,
  onDeep,
  onEid,
  onDiff,
  onTrace,
  onExplain,
  onCoordKey,
  lang,
}) {
  return (
    <Panel title={t("h", "query")} className="panel--query">
      <div className="stack">
        <Field id="a" label={t("l", "a")}>
          <input
            className="input"
            id="a"
            value={a}
            onChange={(e) => onA(e.target.value)}
            onKeyDown={onCoordKey}
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field id="b" label={t("l", "b")}>
          <input
            className="input"
            id="b"
            value={b}
            onChange={(e) => onB(e.target.value)}
            onKeyDown={onCoordKey}
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Checkbox id="deep" label={t("l", "deep")} checked={deep} onChange={onDeep} />
        <Field id="eid" label={t("l", "eid")}>
          <input
            className="input"
            id="eid"
            value={eid}
            onChange={(e) => onEid(e.target.value)}
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>

        {/* The scope note carries emphasis, so it is markup. It is React
            elements rather than dangerouslySetInnerHTML: the strings are ours,
            but an innerHTML sink in a debugging tool is one nobody should have
            to audit later. */}
        <p className="note" data-testid="eid-scope">
          {lang === "zh" ? (
            <>
              生效于：<b>追踪</b>、<b>资源</b>。不生效于：<b>对比</b>、
              <b>生成 AI 提示词</b>（二者使用默认事件）。
            </>
          ) : (
            <>
              Applies to: <b>Trace</b>, <b>Resource</b>. Does not apply to:{" "}
              <b>Diff</b>, <b>Generate AI Prompt</b> (they use the default event).
            </>
          )}
        </p>

        <div className="actions">
          <Button id="btnDiff" primary onClick={onDiff} disabled={busy}>
            {t("b", "diff")}
          </Button>
          <Button id="btnTrace" onClick={onTrace} disabled={busy}>
            {t("b", "trace")}
          </Button>
          <Button id="btnExplain" onClick={onExplain} disabled={busy}>
            {t("b", "explain")}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

/** The header. Connection state and the capture name are both ambient facts. */
export function TopBar({ t, capture, connected, revision, ci, lang, onToggleLang }) {
  return (
    <header className="topbar">
      <h1>rdebug-ide</h1>
      <span className="muted mono" id="capture" title={capture || ""}>
        {capture || ""}
      </span>
      <div className="topbar__spacer" />
      <div className="topbar__tools">
        {ci ? (
          <Badge tone={ci.status === "pass" ? "pass" : "fail"}>
            {ci.status === "pass" ? t("ci", "pass") : "CI " + String(ci.status).toUpperCase()}
          </Badge>
        ) : null}
        <Badge
          tone={connected ? "live" : "down"}
          dot
          title={revision != null ? t("stream", "rev") + " " + revision : ""}
          data-testid="stream-status"
        >
          {connected ? t("stream", "live") : t("stream", "down")}
        </Badge>
        <Button id="btnLang" ghost onClick={onToggleLang} aria-label={t("lang", "switch")}>
          {t("lang", "other")}
        </Button>
      </div>
    </header>
  );
}

export function StatusBar({ resyncs }) {
  return (
    <footer className="statusbar">
      <span data-testid="resyncs">resyncs: {resyncs}</span>
    </footer>
  );
}