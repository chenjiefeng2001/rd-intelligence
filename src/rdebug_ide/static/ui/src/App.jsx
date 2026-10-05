import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  isStale,
  eidParam,
  parseCoord,
  canonicalResourceId,
} from "./api.js";
import { useEventStream } from "./useEventStream.js";
import { I18N, translator } from "./i18n.js";
import { TopBar, QueryPanel, StatusBar } from "./panels/QueryPanel.jsx";
import { ResultPanel } from "./views/ResultPanel.jsx";
import { EvidencePanel } from "./panels/EvidencePanel.jsx";
import "./theme.css";
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

export function App() {
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
  const [serverState, setServerState] = useState(null);

  const t = translator(lang);

  // The declared language has to follow the rendered language, or assistive
  // technology is told the page is Chinese while it reads English.
  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const { connected, lastRevision } = useEventStream({
    onState: setServerState,
    onResync: () => setResyncs((n) => n + 1),
  });

  // One claim per user action, shared by every render target. A response that is
  // no longer current writes nothing at all.
  const seqRef = useRef(0);
  // A request the user has moved past is not merely ignored when it lands, it is
  // cancelled: otherwise the server keeps doing replay work nobody will read.
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

  const canCopy = prompt.length > 0;

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
      // Clipboard access can be refused. Saying so beats a button that appears
      // to work and copies nothing.
      setCopied(false);
      fail("api_error", "clipboard write was refused by the browser");
    }
  }

  // Enter runs the primary action from either coordinate field. A debug tool is
  // typed into; making the user reach for the mouse between naming a pixel and
  // asking about it is friction nobody notices until it is gone.
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
    return () => abortRef.current?.abort();
  }, []);

  return (
    <div className="app">
      <TopBar
        t={t}
        lang={lang}
        capture={serverState?.capture}
        connected={connected}
        revision={lastRevision}
        ci={ci}
        onToggleLang={() => setLang(lang === "zh" ? "en" : "zh")}
      />

      <main className="workspace">
        <QueryPanel
          t={t}
          lang={lang}
          a={a}
          b={b}
          deep={deep}
          eid={eid}
          busy={busy}
          onA={setA}
          onB={setB}
          onDeep={setDeep}
          onEid={setEid}
          onDiff={() => run("diff")}
          onTrace={() => run("trace")}
          onExplain={() => run("explain")}
          onCoordKey={onCoordKey}
        />

        <ResultPanel result={result} t={t} />

        <EvidencePanel
          t={t}
          evidence={evidence}
          prompt={prompt}
          canCopy={canCopy}
          copied={copied}
          onOpen={openResource}
          onCopy={copyPrompt}
        />
      </main>

      <StatusBar resyncs={resyncs} />
    </div>
  );
}