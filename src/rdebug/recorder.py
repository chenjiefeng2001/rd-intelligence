"""Durable query history for long debugging sessions.

A JSONL log answers "what happened"; it cannot answer "what happened to this
pixel over four hours", because reading it back means parsing every line and
then aggregating in Python. That is the gap this closes: a session that
outlives one terminal window becomes queryable rather than merely recorded.

Three constraints shape everything here, and two of them are inherited:

  * **Rule 2.8: best-effort, and never changes a query.** Recording is not on
    the path of an answer. If the store is unwritable, locked, corrupt or full,
    the query still returns the same bytes it would have returned with no store
    configured at all. Every failure is counted, never raised.

  * **Rule 2.2: not importable from the semantic layers.** This module records
    *observations of* queries; it is not part of answering one. `analysis`,
    `adapter` and `query` must not import it, and `audit_boundaries.py` fails
    the build if they do. A store that analysis code can consult could change a
    result, which is exactly what 2.8 forbids.

  * **sqlite3 is in the standard library.** A debugging tool that people
    `pip install` should not acquire a storage dependency to keep a log.

Nothing here writes to a capture, and nothing here reaches into the query layer.
It is a write-only observer with a read API over its own file.
"""

import json
import os
import sqlite3
import threading
import time

#: Environment variable naming the database file. Unset means no store at all,
#: which is the default: a tool that silently accumulates state on someone's
#: disk is a tool people stop running.
ENV_PATH = "RDEBUG_STORE"

#: Store payloads as well as envelopes. Off by default because a trace payload
#: is large and a long session writes thousands of them; the envelope alone is
#: what answers "what did I ask and what happened".
ENV_PAYLOADS = "RDEBUG_STORE_PAYLOADS"

#: Retention. A four-hour session at two queries a minute is a few hundred rows;
#: an impatient script can be far worse. Both bounds are enforced, and a store
#: that keeps only the newest is still a store that answers "recently".
DEFAULT_MAX_ROWS = 50_000
DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          REAL    NOT NULL,
  transport   TEXT    NOT NULL,
  endpoint    TEXT    NOT NULL,
  kind        TEXT    NOT NULL DEFAULT '',
  ok          INTEGER NOT NULL,
  status      INTEGER,
  error       TEXT,
  latency_ms  REAL,
  query       TEXT    NOT NULL DEFAULT '{}',
  summary     TEXT    NOT NULL DEFAULT '{}',
  payload     TEXT
);
CREATE INDEX IF NOT EXISTS obs_ts       ON observations(ts);
CREATE INDEX IF NOT EXISTS obs_endpoint ON observations(endpoint);
CREATE INDEX IF NOT EXISTS obs_pixel    ON observations(query);
CREATE TABLE IF NOT EXISTS recorder_stats (
  id       INTEGER PRIMARY KEY CHECK (id = 1),
  recorded INTEGER NOT NULL DEFAULT 0,
  dropped  INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO recorder_stats (id, recorded, dropped) VALUES (1, 0, 0);
"""

# Re-entrant, and that is load-bearing rather than stylistic. connection() holds
# the lock while it opens the database, and its failure path calls _note_drop(),
# which takes the lock again. With a plain Lock that is a self-deadlock: an
# unwritable RDEBUG_STORE hangs the calling thread forever instead of being
# reported. Since the whole promise of this module is that a broken store
# degrades instead of blocking, a plain Lock would break that promise in the
# exact case it exists for.
_LOCK = threading.RLock()
_CONN = None
_CONN_PATH = None
#: Failures are counted, not raised, but a silent counter nobody reads is the
#: same as no counter. This is read by the CLI and the IDE.
_DROPPED = 0


def enabled() -> bool:
    return bool(os.environ.get(ENV_PATH))


def payload_enabled() -> bool:
    return bool(os.environ.get(ENV_PAYLOADS))


def dropped() -> int:
    """How many observations were lost to a store failure."""
    with _LOCK:
        return _DROPPED


def _note_drop():
    global _DROPPED
    with _LOCK:
        _DROPPED += 1


def connection():
    """The open store, or None when recording is off.

    Reopened if RDEBUG_STORE changed underneath it, which is what a test that
    points at a temporary file needs; a long-lived process would just keep the
    handle it opened.
    """
    global _CONN, _CONN_PATH
    path = os.environ.get(ENV_PATH)
    if not path:
        return None
    with _LOCK:
        if _CONN is not None and _CONN_PATH == path:
            return _CONN
        try:
            if _CONN is not None:
                _CONN.close()
            conn = sqlite3.connect(path, check_same_thread=False,
                                   timeout=2.0)
            conn.row_factory = sqlite3.Row
            # WAL so a reader (the history panel) never blocks the writer (a
            # query in flight). Without it a long read freezes recording, which
            # is the wrong way round for a tool whose queries are the point.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA)
            conn.commit()
        except Exception:
            _note_drop()
            return None
        _CONN, _CONN_PATH = conn, path
        return _CONN


def close():
    """Release the handle. Tests use it; a process would rely on the OS."""
    global _CONN, _CONN_PATH
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
        _CONN, _CONN_PATH = None, None


def _json(value):
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except Exception:
        return "{}"


def _trim(conn):
    """Apply both retention bounds.

    Called on write rather than on read or on a timer. A store nobody queries
    still has to stay bounded, and a background thread inside a query library is
    a much worse trade than a delete that runs when a row arrives. The
    consequence is deliberate and worth knowing: rows that age past the bound
    while the session is idle survive until the next write. For a debugging
    session, where writes are frequent, that is the right end of the trade.
    """
    max_rows = int(os.environ.get("RDEBUG_STORE_MAX_ROWS", DEFAULT_MAX_ROWS))
    max_age = int(os.environ.get("RDEBUG_STORE_MAX_AGE",
                                 DEFAULT_MAX_AGE_SECONDS))
    try:
        if max_rows > 0:
            total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            if total > max_rows:
                conn.execute(
                    "DELETE FROM observations WHERE id IN ("
                    "  SELECT id FROM observations ORDER BY id LIMIT ?)",
                    (total - max_rows,))
        if max_age > 0:
            conn.execute("DELETE FROM observations WHERE ts < ?",
                         (time.time() - max_age,))
    except Exception:
        _note_drop()


def _flatten_query(query):
    """Reduce parse_qs output to scalars.

    urllib hands back {"a": ["320,240"], "deep": ["0"]}. Storing that verbatim
    is not a cosmetic problem: the pixel filter parses these values, and
    str(["320,240"]).split(",") yields "['320" and "240']", which are not
    integers. Every HTTP-recorded row would silently fail every pixel filter
    while the direct unit tests -- which store scalars -- kept passing.

    A parameter given more than once keeps its list, because collapsing it would
    lose information; that case simply does not match a pixel filter.
    """
    if not isinstance(query, dict):
        return {}
    out = {}
    for key, value in query.items():
        if isinstance(value, (list, tuple)):
            out[key] = value[0] if len(value) == 1 else list(value)
        else:
            out[key] = value
    return out


def record(transport, endpoint, *, ok, kind="", status=None, error=None,
           latency_ms=None, query=None, summary=None, payload=None):
    """Record one observed query.

    Returns True when it was stored. Every failure returns False instead of
    propagating: this function is called from the request path, and a query that
    raises because its own audit log is locked is not a query anyone wants.
    """
    conn = connection()
    if conn is None:
        return False
    try:
        with _LOCK:
            conn.execute(
                "INSERT INTO observations"
                " (ts, transport, endpoint, kind, ok, status, error,"
                "  latency_ms, query, summary, payload)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), transport, endpoint, kind, 1 if ok else 0,
                 status, error, latency_ms,
                 _json(_flatten_query(query)), _json(summary or {}),
                 _json(payload) if (payload is not None
                                    and payload_enabled()) else None))
            conn.execute("UPDATE recorder_stats SET recorded = recorded + 1"
                         " WHERE id = 1")
            _trim(conn)
            conn.commit()
        return True
    except Exception:
        _note_drop()
        return False


def stats():
    conn = connection()
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT recorded, dropped FROM recorder_stats"
                           " WHERE id = 1").fetchone()
        total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        return {"recorded": row["recorded"], "dropped": row["dropped"],
                "rows": total, "path": _CONN_PATH,
                "payloads": payload_enabled()}
    except Exception:
        return None


# ------------------------------------------------------------------ reading --

def _rows(sql, params=()):
    conn = connection()
    if conn is None:
        return []
    try:
        with _LOCK:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []


def _as_int(value):
    """Coerce a stored query value to an int, or None.

    A stored request holds strings because that is what the URL carried. The
    filter arrives with ints because that is what a caller typed. Comparing them
    directly makes every trace fail every pixel filter -- and the unit tests do
    not catch it, because they store ints directly. Only the HTTP path stores
    what a URL actually contains.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _match_pixel(query_text, x, y):
    """Does a stored request ask about this pixel?

    Parsed rather than string-matched: `320,240` is a substring of `1320,2401`,
    and a history filter that quietly returns the wrong rows is worse than one
    that returns none.
    """
    if x is None and y is None:
        return True
    try:
        q = json.loads(query_text or "{}")
    except Exception:
        return False
    if not isinstance(q, dict):
        return False

    def coord(raw):
        if raw is None:
            return None
        parts = str(raw).split(",")
        if len(parts) != 2:
            return None
        first, second = _as_int(parts[0]), _as_int(parts[1])
        return (first, second) if first is not None and second is not None \
            else None

    wanted = (x, y)
    if (x is not None or y is not None):
        for side in ("a", "b"):
            if coord(q.get(side)) == wanted:
                return True
    if _as_int(q.get("x")) == x and _as_int(q.get("y")) == y:
        return True
    return False


def recent(limit=50, endpoint=None, x=None, y=None, since=None, until=None,
           failures_only=False, with_payload=False):
    """The newest observations first, filtered.

    `x`/`y` filter on either coordinate of a request, and are applied after the
    SQL limit is generous enough to be useful but bounded enough to stay cheap.
    """
    # None means "the caller did not say"; 0 is a number the caller did say.
    # `limit or DEFAULT` would collapse the two and hand back a default page for
    # an explicit zero, which is how a UI asking for nothing gets fifty rows.
    if limit is None:
        limit = 50
    limit = max(1, min(int(limit), 1000))
    clauses, params = [], []
    if endpoint:
        clauses.append("endpoint = ?")
        params.append(endpoint)
    if since is not None:
        clauses.append("ts >= ?")
        params.append(float(since))
    if until is not None:
        clauses.append("ts <= ?")
        params.append(float(until))
    if failures_only:
        clauses.append("ok = 0")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = ("SELECT * FROM observations" + where +
           " ORDER BY id DESC LIMIT ?")
    params.append(limit * 4 if (x is not None or y is not None) else limit)
    rows = _rows(sql, tuple(params))
    if x is not None or y is not None:
        rows = [r for r in rows if _match_pixel(r.get("query"), x, y)]
        rows = rows[:limit]
    for r in rows:
        r["query"] = _decode(r.get("query"))
        r["summary"] = _decode(r.get("summary"))
        r["payload"] = _decode(r.get("payload")) if with_payload else None
        r["ok"] = bool(r.get("ok"))
    return rows


def _decode(text):
    try:
        return json.loads(text) if text else {}
    except Exception:
        return {}


def aggregate(endpoint=None, since=None, until=None):
    """Counts and timings. The question a JSONL log cannot answer cheaply."""
    clauses, params = [], []
    if endpoint:
        clauses.append("endpoint = ?")
        params.append(endpoint)
    if since is not None:
        clauses.append("ts >= ?")
        params.append(float(since))
    if until is not None:
        clauses.append("ts <= ?")
        params.append(float(until))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    total = _rows("SELECT COUNT(*) AS n, SUM(ok) AS ok FROM observations"
                  + where, tuple(params))
    n = (total[0]["n"] if total else 0) or 0
    ok = (total[0]["ok"] if total else 0) or 0
    latency = _rows("SELECT AVG(latency_ms) AS avg, MAX(latency_ms) AS max"
                    " FROM observations" + where, tuple(params))
    by_endpoint = _rows(
        "SELECT endpoint, COUNT(*) AS n, SUM(ok) AS ok FROM observations"
        + where + " GROUP BY endpoint ORDER BY n DESC", tuple(params))
    top_errors = _rows(
        "SELECT error, COUNT(*) AS n FROM observations" +
        (where + " AND " if where else " WHERE ") + "ok = 0 AND error IS NOT NULL"
        + " GROUP BY error ORDER BY n DESC LIMIT 10", tuple(params))
    return {
        "requests": n,
        "failures": max(0, n - ok),
        "latencyMs": {
            "avg": round(latency[0]["avg"], 2) if latency and
            latency[0]["avg"] is not None else None,
            "max": round(latency[0]["max"], 2) if latency and
            latency[0]["max"] is not None else None,
        },
        "byEndpoint": [
            {"endpoint": r["endpoint"], "count": r["n"], "failures":
             max(0, r["n"] - (r["ok"] or 0))} for r in by_endpoint],
        "topErrors": [{"error": r["error"], "count": r["n"]}
                      for r in top_errors],
        "dropped": dropped(),
        "path": _CONN_PATH,
        "payloads": payload_enabled(),
    }
