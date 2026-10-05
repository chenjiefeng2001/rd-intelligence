// The server-sent-events client.
//
// Two decisions carry the whole design.
//
// First, the stream carries CHANGES and /api/state carries STATE. A client that
// connects, or reconnects, always reads the snapshot and then applies events
// with a revision greater than the one it holds. Nothing here infers state from
// a stream alone, because a dropped connection and an idle one look identical
// on the wire.
//
// Second, a revision that has been evicted is reported, not papered over. The
// server answers `resync` in that case, and the client takes a fresh snapshot
// rather than assuming it is current. Silently resuming from a hole is how a
// debug tool ends up confidently showing stale data.

import { useEffect, useRef, useState, useCallback } from "react";

const RESYNC_BACKOFF_MS = [500, 1000, 2000, 4000, 8000];

export function useEventStream({ onState, onResync }) {
  const [connected, setConnected] = useState(false);
  const [lastRevision, setLastRevision] = useState(null);
  const retryRef = useRef(0);
  const sourceRef = useRef(null);

  // Held in refs so a re-render of the consumer does not tear down the stream.
  // A stream is a resource, not a value: reconnecting it whenever a callback
  // identity changed would drop and re-establish the connection on every render.
  const onStateRef = useRef(onState);
  const onResyncRef = useRef(onResync);
  onStateRef.current = onState;
  onResyncRef.current = onResync;

  const connect = useCallback(async () => {
    const snapshot = await fetch("/api/state", { cache: "no-store" });
    const state = snapshot.ok ? await snapshot.json() : null;
    if (state) {
      setLastRevision(state.revision);
      onStateRef.current?.(state);
    }

    // lastEventId goes in the query string as well as the header: EventSource
    // will not let a page set Last-Event-ID itself, and a hand-rolled
    // reconnect after a dropped connection needs a way to say where it left off.
    const from = state && state.revision != null ? "?lastEventId=" + state.revision : "";
    const source = new EventSource("/api/events" + from);
    sourceRef.current = source;

    source.onopen = () => {
      setConnected(true);
      retryRef.current = 0;
    };

    const apply = (raw) => {
      let event;
      try {
        event = JSON.parse(raw);
      } catch {
        // A frame that is not JSON is not applied and not guessed at. The
        // client stays where it is, which is visible, rather than moving to a
        // half-understood state, which is not.
        return;
      }
      if (typeof event.revision === "number") {
        // Out-of-order or replayed frames are ignored rather than applied: a
        // stream that reorders would otherwise move the UI backwards.
        setLastRevision((prev) =>
          prev == null || event.revision > prev ? event.revision : prev,
        );
      }
      if (event.state) onStateRef.current?.(event.state);
    };

    source.addEventListener("configured", (e) => apply(e.data));
    source.addEventListener("disposed", (e) => apply(e.data));
    source.addEventListener("hello", (e) => apply(e.data));
    source.addEventListener("resync", (e) => {
      apply(e.data);
      onResyncRef.current?.();
    });

    source.onerror = () => {
      setConnected(false);
      source.close();
      const wait = RESYNC_BACKOFF_MS[
        Math.min(retryRef.current, RESYNC_BACKOFF_MS.length - 1)
      ];
      retryRef.current += 1;
      setTimeout(connect, wait);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => sourceRef.current?.close();
  }, [connect]);

  return { connected, lastRevision };
}