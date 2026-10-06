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

export function useEventStream({ onState, onResync, onQuery, onEvent }) {
  const [connected, setConnected] = useState(false);
  const [lastRevision, setLastRevision] = useState(null);
  const retryRef = useRef(0);
  const sourceRef = useRef(null);

  // Held in refs so a re-render of the consumer does not tear down the stream.
  // A stream is a resource, not a value: reconnecting it whenever a callback
  // identity changed would drop and re-establish the connection on every render.
  const onStateRef = useRef(onState);
  const onResyncRef = useRef(onResync);
  const onQueryRef = useRef(onQuery);
  const onEventRef = useRef(onEvent);
  onStateRef.current = onState;
  onResyncRef.current = onResync;
  onQueryRef.current = onQuery;
  onEventRef.current = onEvent;

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

    // Every frame is parsed exactly once, and a frame that is not JSON is
    // neither applied nor logged: the client stays where it is, which is
    // visible, rather than moving to a half-understood state, which is not.
    // A log that silently omitted the frames it could not read would be worse
    // than no log, because it would look complete.
    const read = (raw) => {
      try {
        return JSON.parse(raw);
      } catch {
        return null;
      }
    };

    const apply = (event) => {
      if (!event) return;
      if (typeof event.revision === "number") {
        // Out-of-order or replayed frames are ignored rather than applied: a
        // stream that reorders would otherwise move the UI backwards.
        setLastRevision((prev) =>
          prev == null || event.revision > prev ? event.revision : prev,
        );
      }
      if (event.state) onStateRef.current?.(event.state);
    };

    // The log records what arrived, in arrival order, including frames the
    // client then declined to apply. A debugging tool whose own stream cannot
    // be inspected is missing the most basic instrument.
    const handle = (raw) => {
      const event = read(raw);
      if (!event) return null;
      apply(event);
      onEventRef.current?.(event);
      return event;
    };

    source.addEventListener("configured", (e) => handle(e.data));
    source.addEventListener("disposed", (e) => handle(e.data));
    source.addEventListener("hello", (e) => handle(e.data));

    // Queries are coalesced rather than acted on one by one. A diff issues a
    // second request for the prompt, and a script can issue dozens; refreshing
    // once per event would turn the observer into load. The window is short
    // enough that a single manual query still feels immediate.
    //
    // The log entry is not coalesced. Dropping records to save a refresh would
    // make the log a summary of what the panel happened to act on, which is
    // precisely the opposite of what a log is for.
    let pending = null;
    source.addEventListener("query", (e) => {
      const event = handle(e.data);
      if (pending) clearTimeout(pending);
      pending = setTimeout(() => {
        pending = null;
        onQueryRef.current?.(event ? event.detail : null);
      }, 250);
    });

    source.addEventListener("resync", (e) => {
      handle(e.data);
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