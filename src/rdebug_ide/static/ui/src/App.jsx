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
import { HistoryPanel, scopeOf } from "./panels/HistoryPanel.jsx";
import { EvidenceChain } from "./panels/EvidenceChain.jsx";
import { EventLog } from "./panels/EventLog.jsx";
import "./theme.css";
import "./styles.css";

const MAX_DRAWS = 16; // explicit scope; truncation is surfaced, not hidden

// The stream log is capped. A session that runs for hours would otherwise grow
// it without limit, and the panel that exists to explain the tool must not be
// the thing that eventually makes the page unusable. The count of what fell off
// is kept so the log can say it is truncated rather than looking idle.
const LOG_LIMIT = 200;

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

  // History. Separate from `result` because it has its own failure modes: a
  // store that is not configured is not an error, and a history read that fails
  // must not touch the query result panel.
  const [history, setHistory] = useState({
    enabled: false,
    loading: false,
    rows: [],
    summary: null,
    store: null,
  });
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [scopePixel, setScopePixel] = useState(false);
  const [endpointFilter, setEndpointFilter] = useState("");

  // The server's own announcements, newest last in the store and rendered
  // newest first. `logDropped` counts entries evicted by the cap.
  const [logEvents, setLogEvents] = useState([]);
  const [logDropped, setLogDropped] = useState(0);
  const [logFilter, setLogFilter] = useState("all");
  const logSeq = useRef(0);

  const pushLogEvent = useCallback((event) => {
    logSeq.current += 1;
    const entry = {
      seq: logSeq.current,
      at: Date.now(),
      kind: event.kind,
      revision: event.revision,
      detail: event.detail,
    };
    setLogEvents((prev) => {
      if (prev.length < LOG_LIMIT) return prev.concat(entry);
      setLogDropped((n) => n + 1);
      return prev.slice(prev.length - LOG_LIMIT + 1).concat(entry);
    });
  }, []);

  const t = translator(lang);

  // The declared language has to follow the rendered language, or assistive
  // technology is told the page is Chinese while it reads English.
  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const loadHistoryRef = useRef(null);
  const { connected, lastRevision } = useEventStream({
    onState: setServerState,
    onResync: () => setResyncs((n) => n + 1),
    // A query happened -- possibly in another tab, or on the frozen page. The
    // panel observes the session rather than logging this tab's own clicks, so it
    // refreshes from the stream and not only after a local action.
    onQuery: () => loadHistoryRef.current?.(),
    onEvent: pushLogEvent,
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

  /**
   * Read the history.
   *
   * A failure here is recorded in the history panel's own state and nowhere
   * else. Feeding it to `fail()` would replace a query result the user is still
   * reading with a message about the panel they did not ask for -- two unrelated
   * surfaces sharing one error path is how a good result gets lost.
   */
  const loadHistory = useCallback(async () => {
    setHistory((h) => ({ ...h, loading: true }));
    const scope = scopePixel ? scopeOf(a, b) : { a: null, b: null };
    const params = new URLSearchParams({ limit: "50" });
    if (endpointFilter) params.set("endpoint", endpointFilter);
    if (failuresOnly) params.set("failures", "1");
    if (scope.a) {
      params.set("x", String(scope.a.x));
      params.set("y", String(scope.a.y));
    } else if (scope.b) {
      params.set("x", String(scope.b.x));
      params.set("y", String(scope.b.y));
    }
    const [rows, totals] = await Promise.all([
      api("/api/history?" + params.toString()),
      api("/api/history/summary"),
    ]);
    setHistory({
      enabled: rows.ok ? rows.data.enabled : false,
      loading: false,
      rows: rows.ok ? rows.data.observations || [] : [],
      summary: totals.ok ? totals.data.summary : null,
      store: totals.ok ? totals.data.store : null,
    });
  }, [a, b, failuresOnly, scopePixel, endpointFilter]);
  loadHistoryRef.current = loadHistory;

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

  // Loaded once on mount, then whenever the filters change. Reading history does
  // not record history, so there is no feedback loop here to guard against.
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const scope = scopeOf(a, b);
  const scopeAvailable = Boolean(scope.a || scope.b);

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

        {/* The chain sits directly under the result: it is the reasoning for
            what is above it, and separating them would make the reader hold
            two things in mind to connect one. */}
        <EvidenceChain result={result} t={t} onOpen={openResource} />

        <EvidencePanel
          t={t}
          evidence={evidence}
          prompt={prompt}
          canCopy={canCopy}
          copied={copied}
          onOpen={openResource}
          onCopy={copyPrompt}
        />

        <HistoryPanel
          t={t}
          enabled={history.enabled}
          loading={history.loading}
          rows={history.rows}
          summary={history.summary}
          store={history.store}
          failuresOnly={failuresOnly}
          scopePixel={scopePixel}
          endpointFilter={endpointFilter}
          scopeAvailable={scopeAvailable}
          scopePixelText={scope.a ? a : b}
          onRefresh={loadHistory}
          onToggleFailures={() => setFailuresOnly((v) => !v)}
          onToggleScope={() => setScopePixel((v) => !v)}
          onEndpoint={setEndpointFilter}
        />

        <EventLog
          events={logEvents}
          dropped={logDropped}
          filter={logFilter}
          onFilter={setLogFilter}
          onClear={() => {
            setLogEvents([]);
            setLogDropped(0);
          }}
          t={t}
        />
      </main>

      <StatusBar resyncs={resyncs} />
    </div>
  );
}