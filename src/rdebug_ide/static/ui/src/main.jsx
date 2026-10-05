import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  api,
  isStale,
  eidParam,
  parseCoord,
  canonicalResourceId,
} from "./api.js";
import { useEventStream } from "./useEventStream.js";
import { I18N, translator } from "./i18n.js";
import "./styles.css";

const MAX_DRAWS = 16; // explicit scope; truncation is surfaced, not hidden

function collectEvidenceIds(node) {
  let out = [];
  if (Array.isArray(node)) return node.flatMap(collectEvidenceIds);
  if (node && typeof node === "object") {
    if (node.id && node.operation) out.push(node);
    Object.values(node).forEach((v) => {
      out = out.concat(collectEvidenceIds(v));
    });
  }
  return out;
}

// The eid scope note carries emphasis, so it is markup rather than plain text.
// It is rendered from the translation table as React elements rather than
// through dangerouslySetInnerHTML: the strings are ours, but an innerHTML sink
// in a debugging tool is one nobody should have to audit later, and the
// structure here is fixed enough to write out.
function EidScope({ lang }) {
  const parts = {
    en: (
      <>
        Applies to: <b>Trace</b>, <b>Resource</b>. Does not apply to:{" "}
        <b>Diff</b>, <b>Generate AI Prompt</b> (they use the default event).
      </>
    ),
    zh: (
      <>
        生效于：<b>追踪</b>、<b>资源</b>。不生效于：<b>对比</b>、
        <b>生成 AI 提示词</b>（二者使用默认事件）。
      </>
    ),
  };
  return (
    <p className="note" data-testid="eid-scope">
      {parts[lang] ?? parts.en}
    </p>
  );
}

function FailureBanner({ text, detail }) {
  // role="alert" rather than a plain div: a failure that arrives after the user
  // has looked away is exactly what an assertive live region is for. The frozen
  // page could not make that claim, because it has no live region at all.
  return (
    <div className="banner banner-warn" role="alert" data-testid="failure-banner">
      <b>{text}</b>
      {detail ? <div className="banner-detail">{detail}</div> : null}
    </div>
  );
}

function ResultView({ result, t }) {
  if (!result) return <p className="muted">{t("res", "blank")}</p>;
  if (result.kind === "failure") {
    return <FailureBanner text={result.text} detail={result.detail} />;
  }
  if (result.kind === "loading") {
    return (
      <p className="muted" data-testid="loading">
        {t("res", "loading")}
      </p>
    );
  }
  // A trace and a diff are told apart by their own shape rather than by a mode
  // flag. A view told "diff" while holding a trace would read undefined fields
  // and render them blank, which reads as "no result" rather than as a mistake.
  if (result.data?.summary && result.data?.edges) {
    return <TraceView data={result.data} t={t} />;
  }
  return <DiffView data={result.data} t={t} />;
}

function DiffView({ data, t }) {
  const first = data.firstDivergence || {};
  return (
    <>
      <dl className="kv">
        <dt>{t("diff", "comparison")}</dt>
        <dd>
          <span className={"st st-" + data.comparison}>{data.comparison}</span>
        </dd>
        <dt>{t("diff", "firstDivergence")}</dt>
        <dd>{first.layer ?? "—"}</dd>
        <dt>{t("diff", "good")}</dt>
        <dd className="mono">{JSON.stringify(first.good ? first.good.value : null)}</dd>
        <dt>{t("diff", "bad")}</dt>
        <dd className="mono">{JSON.stringify(first.bad ? first.bad.value : null)}</dd>
      </dl>
      <h2 className="sub">{t("diff", "layers")}</h2>
      <ul className="layers" data-testid="layers">
        {data.layers.map((l) => (
          <li className="layer" key={l.layer}>
            <span className="layer-name">{l.layer}</span>
            <span className={"st st-" + l.status}>{l.status}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function TraceView({ data, t }) {
  const reads = data.edges.filter((e) => e.label === "reads");
  const written = data.edges.filter((e) => e.label === "written_by");
  const trunc = data.summary && data.summary.truncatedDraws;
  return (
    <>
      {trunc && (
        <div className="banner banner-warn" role="alert" data-testid="truncation">
          {t("trace", "truncated", { n: data.summary.modificationCount })}
        </div>
      )}
      <dl className="kv">
        <dt>{t("trace", "target")}</dt>
        <dd className="mono">{data.summary.target ?? ""}</dd>
        <dt>{t("trace", "modifications")}</dt>
        <dd>
          {data.summary.modificationCount}
          {trunc ? t("trace", "truncatedShort") : ""}
        </dd>
        <dt>{t("trace", "finalValue")}</dt>
        <dd className="mono">{JSON.stringify(data.summary.finalValue)}</dd>
      </dl>
      <h2 className="sub">{t("trace", "reads")}</h2>
      <ul className="reads" data-testid="reads">
        {reads.map((r) => (
          <li key={r.to}>
            <span className="mono">{r.to}</span>
            <ul className="tree">
              {written
                .filter((w) => w.from === r.to)
                .map((w) => (
                  <li key={w.to}>
                    <span className="muted">
                      {t("trace", "writtenBy", { id: w.to })}{" "}
                      ({w.evidence?.[0]?.data?.primitives ?? ""})
                    </span>
                  </li>
                ))}
            </ul>
          </li>
        ))}
      </ul>
    </>
  );
}

function App() {
  const [lang, setLang] = useState("en");
  const [a, setA] = useState("320,240");
  const [b, setB] = useState("10,10");
  const [deep, setDeep] = useState(false);
  const [eid, setEid] = useState("");
  const [result, setResult] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [evidence, setEvidence] = useState([]);
  const [resyncs, setResyncs] = useState(0);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [ci, setCi] = useState(null);

  const t = translator(lang);

  // The declared language has to follow the rendered language, or assistive
  // technology is told the page is Chinese while it reads English.
  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const [serverState, setServerState] = useState(null);
  const { connected, lastRevision } = useEventStream({
    onState: setServerState,
    onResync: () => setResyncs((n) => n + 1),
  });

  // One claim per user action, shared by every render target. A response that
  // is no longer the current one writes nothing at all.
  const seqRef = useRef(0);
  // A request the user has already moved on from is not merely ignored when it
  // lands -- it is cancelled, so the server is not left doing replay work whose
  // answer nobody will read. Ignored-but-in-flight was the old behaviour and it
  // is why the page could queue three traces by clicking three times.
  const abortRef = useRef(null);

  const fail = useCallback(
    (kind, detail) => {
      const table = I18N[lang] ? I18N[lang].failure : I18N.en.failure;
      setResult({
        kind: "failure",
        text: table[kind] || table.api_error,
        detail: detail || "",
      });
    },
    [lang],
  );

  const applyResult = useCallback(
    (res) => {
      if (res.kind === "cancelled") return false;
      if (!res.ok) {
        fail(res.kind, res.message);
        return false;
      }
      setResult({ kind: "ok", data: res.data });
      return true;
    },
    [fail],
  );

  // The prompt follows what the prompt is. Copy is available when there is
  // something to copy, not because a diff happened: an empty prompt that can be
  // copied as if it were real is the failure this rule replaces. That is why
  // `copied` is cleared by any run rather than set once and left.
  const canCopy = prompt.length > 0;

  // Applying an explain response is the only thing that writes the prompt. A
  // failure is reported rather than swallowed, and the prompt is emptied so a
  // prompt describing an earlier diff cannot be mistaken for this one.
  const applyPrompt = useCallback(
    (res) => {
      if (res.kind === "cancelled") return false;
      if (!res.ok) {
        setPrompt("");
        fail(res.kind, res.message);
        return false;
      }
      setPrompt(res.data?.prompt || "");
      return true;
    },
    [fail],
  );

  async function run(kind) {
    const seq = ++seqRef.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setResult({ kind: "loading" });
    setBusy(true);
    setCopied(false);

    try {
      if (kind === "diff") {
        const d = await api(
          `/api/diff?a=${a}&b=${b}&deep=${deep ? 1 : 0}`,
          { signal: controller.signal },
        );
        if (isStale(seq)) return;
        if (!applyResult(d)) return;
        setEvidence([...new Set(collectEvidenceIds(d.data.layers).map((e) => e.id))]);
        // The prompt is still produced as part of a diff. It is a follow-up
        // rather than a result, which only means it is a stale write once the
        // user has moved on; it does not make its failure invisible.
        const p = await api(`/api/explain?a=${a}&b=${b}&deep=${deep ? 1 : 0}`, {
          signal: controller.signal,
        });
        if (isStale(seq)) return;
        applyPrompt(p);
        return;
      }

      if (kind === "explain") {
        // This asks only for the prompt. It deliberately does not re-run the
        // diff, because making this button a second diff button lost the user
        // the result they were looking at.
        const p = await api(`/api/explain?a=${a}&b=${b}&deep=${deep ? 1 : 0}`, {
          signal: controller.signal,
        });
        if (isStale(seq)) return;
        applyPrompt(p);
        return;
      }

      const c = parseCoord(a);
      if (!c.ok) {
        fail(c.kind, c.message);
        return;
      }
      const { x, y } = c.data;
      const g = await api(
        `/api/trace?x=${x}&y=${y}&max_draws=${MAX_DRAWS}${eidParam(eid)}`,
        { signal: controller.signal },
      );
      if (isStale(seq)) return;
      if (!applyResult(g)) return;
      // A trace has no diff behind it, so there is no prompt describing one. The
      // prompt is emptied rather than left describing the previous diff.
      setPrompt("");
      setEvidence([]);
    } finally {
      if (!isStale(seq)) setBusy(false);
    }
  }

  async function openResource(id) {
    const seq = ++seqRef.current;
    const c = canonicalResourceId(id);
    if (!c.ok) {
      fail(c.kind, c.message);
      return;
    }
    const r = await api(
      `/api/resource?id=${encodeURIComponent(c.data.id)}${eidParam(eid)}`,
    );
    if (isStale(seq)) return;
    applyResult(r);
  }

  async function copyPrompt() {
    if (!canCopy) return;
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
    } catch {
      // Clipboard access can be refused. Reporting that is better than a button
      // that appears to work and copies nothing.
      setCopied(false);
      fail("api_error", "clipboard write was refused by the browser");
    }
  }

  // Enter runs the primary action from either coordinate field. A debug tool is
  // typed into; making the user reach for the mouse between typing a pixel and
  // asking about it is the kind of friction nobody notices until it is gone.
  function onCoordKey(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      run(event.target.id === "b" ? "diff" : "trace");
    }
  }

  useEffect(() => {
    api("/api/info").then((i) => {
      if (i.ok) setServerState((s) => ({ ...(s || {}), capture: i.data.capture }));
    });
    api("/api/ci").then((c) => {
      if (c.ok) setCi(c.data);
    });
  }, []);

  // Unmounting mid-request must not leave a rejection unhandled or a controller
  // dangling.
  useEffect(() => () => abortRef.current?.abort(), []);

  const ciNode =
    ci && !ci.enabled ? null : ci ? (
      <span className={"badge " + (ci.status === "pass" ? "ci-pass" : "ci-fail")}>
        {ci.status === "pass" ? t("ci", "pass") : "CI " + String(ci.status).toUpperCase()}
      </span>
    ) : null;

  return (
    <>
      <header>
        <h1>rdebug-ide</h1>
        <span className="muted mono" id="capture" title={serverState?.capture || ""}>
          {serverState?.capture || ""}
        </span>
        {ciNode}
        <span
          className={"badge " + (connected ? "stream-live" : "stream-down")}
          data-testid="stream-status"
          title={lastRevision != null ? t("stream", "rev") + " " + lastRevision : ""}
        >
          {connected ? t("stream", "live") : t("stream", "down")}
        </span>
        <button
          id="btnLang"
          onClick={() => setLang(lang === "zh" ? "en" : "zh")}
          aria-label={I18N[lang].langLabel}
        >
          {I18N[lang].langLabel}
        </button>
      </header>

      <main>
        <section className="card card-query" aria-labelledby="h-query">
          <h2 id="h-query">{t("h", "query")}</h2>
          <div className="fields">
            <div className="field">
              <label htmlFor="a">{t("l", "a")}</label>
              <input
                id="a"
                value={a}
                onChange={(e) => setA(e.target.value)}
                onKeyDown={onCoordKey}
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                size={8}
              />
            </div>
            <div className="field">
              <label htmlFor="b">{t("l", "b")}</label>
              <input
                id="b"
                value={b}
                onChange={(e) => setB(e.target.value)}
                onKeyDown={onCoordKey}
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                size={8}
              />
            </div>
            <div className="field field-check">
              <input
                type="checkbox"
                id="deep"
                checked={deep}
                onChange={(e) => setDeep(e.target.checked)}
              />
              <label htmlFor="deep">{t("l", "deep")}</label>
            </div>
            <div className="field">
              <label htmlFor="eid">{t("l", "eid")}</label>
              <input
                id="eid"
                value={eid}
                onChange={(e) => setEid(e.target.value)}
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                size={6}
              />
            </div>
            <EidScope lang={lang} />
            <div className="actions">
              <button id="btnDiff" onClick={() => run("diff")} disabled={busy}>
                {t("b", "diff")}
              </button>
              <button id="btnTrace" onClick={() => run("trace")} disabled={busy}>
                {t("b", "trace")}
              </button>
              <button id="btnExplain" onClick={() => run("explain")} disabled={busy}>
                {t("b", "explain")}
              </button>
            </div>
          </div>
        </section>

        <section className="card card-result" aria-labelledby="h-result">
          <h2 id="h-result">{t("h", "result")}</h2>
          {/* aria-live: the result arrives after the click that asked for it, so
              without this a screen reader user is told nothing happened. */}
          <div id="result" data-testid="result" aria-live="polite" aria-busy={busy}>
            <ResultView result={result} t={t} />
          </div>
        </section>

        <section className="card card-evidence" aria-labelledby="h-evidence">
          <h2 id="h-evidence">{t("h", "evidence")}</h2>
          <div data-testid="evidence">
            {evidence.length === 0 ? (
              <span className="muted">—</span>
            ) : (
              evidence.map((id) => (
                <button key={id} className="chip mono" onClick={() => openResource(id)}>
                  {id}
                </button>
              ))
            )}
          </div>
          <h2 className="sub">{t("h", "prompt")}</h2>
          <label className="sr-only" htmlFor="prompt">
            {t("h", "prompt")}
          </label>
          <textarea
            id="prompt"
            readOnly
            value={prompt}
            placeholder={t("res", "hint")}
            spellCheck={false}
          />
          <button id="btnCopy" onClick={copyPrompt} disabled={!canCopy}>
            {copied ? t("b", "copied") : t("b", "copy")}
          </button>
        </section>
      </main>
      <footer className="muted" data-testid="resyncs">
        resyncs: {resyncs}
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);