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

function ResultView({ result, t }) {
  if (!result) return <div className="muted">{t("res", "blank")}</div>;
  if (result.kind === "failure") {
    // Containment, not a state machine: it reports and stops.
    return (
      <div className="banner banner-warn" role="alert" data-testid="failure-banner">
        <b>{result.text}</b>
        <div>{result.detail}</div>
      </div>
    );
  }
  if (result.kind === "loading") {
    return <div className="muted">{t("res", "loading")}</div>;
  }
  // A trace and a diff are told apart by their own shape, not by a mode flag
  // the view has to be told about separately. A view told "diff" while holding a
  // trace would read undefined fields and render them as blank, which reads as
  // "no result" rather than as a mistake.
  if (result.data && result.data.summary && result.data.edges) {
    return <TraceView data={result.data} t={t} />;
  }
  return <DiffView data={result.data} t={t} />;
}

function DiffView({ data, t }) {
  const first = data.firstDivergence || {};
  const ids = [...new Set(collectEvidenceIds(data.layers).map((e) => e.id))];
  return (
    <>
      <div className="kv">
        <span className="k">{t("diff", "comparison")}</span>
        <span>
          <span className={"st-" + data.comparison}>{data.comparison}</span>
        </span>
        <span className="k">{t("diff", "firstDivergence")}</span>
        <span>{first.layer ?? "—"}</span>
        <span className="k">{t("diff", "good")}</span>
        <span>{JSON.stringify(first.good ? first.good.value : null)}</span>
        <span className="k">{t("diff", "bad")}</span>
        <span>{JSON.stringify(first.bad ? first.bad.value : null)}</span>
      </div>
      <h2 className="sub">{t("diff", "layers")}</h2>
      {data.layers.map((l) => (
        <div className="layer" key={l.layer}>
          <span className="layer-name">{l.layer}</span>
          <span className={"st-" + l.status}>{l.status}</span>
        </div>
      ))}
      <div data-testid="evidence-ids">{ids.join(",")}</div>
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
      <div className="kv">
        <span className="k">{t("trace", "target")}</span>
        <span>{data.summary.target ?? ""}</span>
        <span className="k">{t("trace", "modifications")}</span>
        <span>
          {data.summary.modificationCount}
          {trunc ? t("trace", "truncatedShort") : ""}
        </span>
        <span className="k">{t("trace", "finalValue")}</span>
        <span>{JSON.stringify(data.summary.finalValue)}</span>
      </div>
      <h2 className="sub">{t("trace", "reads")}</h2>
      {reads.map((r) => (
        <div key={r.to}>
          <div>{r.to}</div>
          <div className="tree">
            {written
              .filter((w) => w.from === r.to)
              .map((w) => (
                <div key={w.to}>
                  {t("trace", "writtenBy", { id: w.to })}{" "}
                  <span className="muted">
                    ({w.evidence[0].data?.primitives ?? ""})
                  </span>
                </div>
              ))}
          </div>
        </div>
      ))}
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

  const t = translator(lang);

  // The declared language has to follow the rendered language, or assistive
  // technology is told the page is Chinese while it reads English. The frozen
  // page does this on its <html> element too, and getting it wrong there is
  // exactly the kind of small untruth that is easy to reintroduce.
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

  const fail = useCallback((kind, detail) => {
    const table = I18N[lang] ? I18N[lang].failure : I18N.en.failure;
    setResult({
      kind: "failure",
      text: table[kind] || table.api_error,
      detail: detail || "",
    });
  }, [lang]);

  const applyResult = useCallback((res) => {
    if (res.kind === "cancelled") return;
    if (!res.ok) return fail(res.kind, res.message);
    setResult({ kind: "ok", data: res.data });
    return true;
  }, [fail]);

  async function run(kind) {
    const seq = ++seqRef.current;
    setResult({ kind: "loading" });

    if (kind === "diff") {
      const d = await api(
        `/api/diff?a=${a}&b=${b}&deep=${deep ? 1 : 0}`,
      );
      if (isStale(seq)) return;
      if (!applyResult(d)) return;
      const p = await api(`/api/explain?a=${a}&b=${b}&deep=${deep ? 1 : 0}`);
      if (isStale(seq)) return;
      if (p.ok) setPrompt(p.data.prompt || "");
      else setPrompt("");
      return;
    }

    const c = parseCoord(a);
    if (!c.ok) return fail(c.kind, c.message);
    const { x, y } = c.data;
    const g = await api(
      `/api/trace?x=${x}&y=${y}&max_draws=${MAX_DRAWS}${eidParam(eid)}`,
    );
    if (isStale(seq)) return;
    if (!applyResult(g)) return;
    setPrompt("");
    setEvidence([]);
  }

  async function openResource(id) {
    const seq = ++seqRef.current;
    const c = canonicalResourceId(id);
    if (!c.ok) return fail(c.kind, c.message);
    const r = await api(`/api/resource?id=${encodeURIComponent(c.data.id)}${eidParam(eid)}`);
    if (isStale(seq)) return;
    applyResult(r);
  }

  useEffect(() => {
    api("/api/info").then((i) => {
      if (i.ok) setServerState((s) => ({ ...(s || {}), capture: i.data.capture }));
    });
  }, []);

  // The diff view's evidence ids, kept in state so a chip can be clicked.
  useEffect(() => {
    if (result && result.kind === "ok" && result.data.layers) {
      setEvidence([...new Set(collectEvidenceIds(result.data.layers).map((e) => e.id))]);
    }
  }, [result]);

  return (
    <>
      <header>
        <h1>rdebug-ide</h1>
        <span className="muted">{serverState?.capture || ""}</span>
        <span
          className={connected ? "badge stream-live" : "badge stream-down"}
          data-testid="stream-status"
        >
          {t("h", "stream")}: {connected ? t("stream", "live") : t("stream", "down")}
          {lastRevision != null ? ` (${t("stream", "rev")} ${lastRevision})` : ""}
        </span>
        <button id="btnLang" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>
          {I18N[lang].langLabel}
        </button>
      </header>
      <main>
        <div className="card" style={{ maxWidth: 420 }}>
          <h2>{t("h", "query")}</h2>
          <div style={{ display: "grid", gap: 6 }}>
            <label>
              {t("l", "a")}{" "}
              <input value={a} onChange={(e) => setA(e.target.value)} size={8} />
            </label>
            <label>
              {t("l", "b")}{" "}
              <input value={b} onChange={(e) => setB(e.target.value)} size={8} />
            </label>
            <label>
              <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} />{" "}
              {t("l", "deep")}
            </label>
            <label>
              {t("l", "eid")}{" "}
              <input value={eid} onChange={(e) => setEid(e.target.value)} size={6} />
            </label>
            <div className="muted" dangerouslySetInnerHTML={{ __html: t("eidScope") }} />
            <div>
              <button id="btnDiff" onClick={() => run("diff")}>
                {t("b", "diff")}
              </button>
              <button id="btnTrace" onClick={() => run("trace")}>
                {t("b", "trace")}
              </button>
            </div>
          </div>
        </div>

        <div className="card" style={{ flex: 2 }}>
          <h2>{t("h", "result")}</h2>
          <div id="result" data-testid="result">
            <ResultView result={result} t={t} />
          </div>
        </div>

        <div className="card" style={{ flex: 1 }}>
          <h2>{t("h", "evidence")}</h2>
          <div data-testid="evidence">
            {evidence.length === 0
              ? "—"
              : evidence.map((id) => (
                  <button key={id} className="chip" onClick={() => openResource(id)}>
                    {id}
                  </button>
                ))}
          </div>
          <h2 className="sub">{t("h", "prompt")}</h2>
          <textarea id="prompt" readOnly value={prompt} placeholder={t("res", "hint")} />
        </div>
      </main>
      <footer className="muted" data-testid="resyncs">
        resyncs: {resyncs}
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);