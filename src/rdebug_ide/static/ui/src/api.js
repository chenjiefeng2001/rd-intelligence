// The client result envelope.
//
// This is the property the front end must not get wrong, and it was the reason
// the old page was written the way it was. The server distinguishes outcomes
// with a real status code AND an always-present JSON body, but an unclassified
// worker error comes back as HTTP 200 with an error body. So `r.ok` alone is
// not an answer, and neither is `body.error` alone:
//
//   {ok:true}                        a valid payload, including a valid empty one
//   {ok:false, kind:"api_error"}     the server answered, and it was an error
//   {ok:false, kind:"transport_error"}  fetch itself rejected
//   {ok:false, kind:"malformed"}     the body was not JSON
//
// `kind` chooses wording only. Deciding how the page organises outcomes is a
// separate concern and is not decided here.

export const FAILURE_TEXT = {
  transport_error: "Cannot reach the rdebug-ide service",
  malformed: "The service returned a response that is not JSON",
  api_error: "The service rejected the request",
};

export const FAILURE_TEXT_ZH = {
  transport_error: "无法连接 rdebug-ide 服务",
  malformed: "服务返回的不是 JSON",
  api_error: "服务拒绝了该请求",
};

export async function api(path, { signal } = {}) {
  let r;
  try {
    r = await fetch(path, { signal });
  } catch (e) {
    // An abort is the caller withdrawing, not a failure of the service. It is
    // reported as such so a cancelled request never renders as an error banner.
    if (e && (e.name === "AbortError" || e.name === "CanceledError")) {
      return { ok: false, kind: "cancelled", message: "" };
    }
    return { ok: false, kind: "transport_error", message: String(e) };
  }
  let body;
  try {
    body = await r.json();
  } catch {
    return {
      ok: false,
      kind: "malformed",
      status: r.status,
      message: "response body was not JSON",
    };
  }
  if (!r.ok) {
    return {
      ok: false,
      kind: "api_error",
      status: r.status,
      message: (body && body.error) || "HTTP " + r.status,
    };
  }
  if (body && typeof body === "object" && body.error) {
    // 200 with an error body. This is the documented trap, and it is why the
    // body is inspected even after the status has been accepted.
    return { ok: false, kind: "api_error", status: r.status, message: body.error };
  }
  return { ok: true, data: body };
}

// Request identity.
//
// Claimed when the user acts, not when a response arrives, so network timing
// cannot redefine which request counts as current. One global domain covers
// every render target rather than a counter per region: two regions with
// separate counters could each believe they were the latest. A late response is
// discarded rather than allowed to overwrite whatever is on screen -- the same
// failure class as the stale-response defect, along the time axis instead of the
// input axis.

let currentSeq = 0;
export function claim() {
  return ++currentSeq;
}
export function isStale(seq) {
  return seq < currentSeq;
}

export function parseCoord(text) {
  const raw = (text || "").trim();
  const m = /^(-?\d+)\s*,\s*(-?\d+)$/.exec(raw);
  if (!m) {
    return {
      ok: false,
      kind: "api_error",
      message: "coordinates must be written as x,y integers; got: " + raw,
    };
  }
  return { ok: true, data: { x: parseInt(m[1], 10), y: parseInt(m[2], 10) } };
}

// The id arrives from the evidence chips the server already rendered in
// canonical form. It is either already canonical and preserved byte for byte,
// or refused; it is never rewritten, because rewriting round-trips only for the
// one shape that happens to survive it.
export function canonicalResourceId(id) {
  const raw = (id || "").trim();
  if (!/^ResourceId::\d+$/.test(raw)) {
    return {
      ok: false,
      kind: "api_error",
      message: "not a canonical resource identifier: " + raw,
    };
  }
  return { ok: true, data: { id: raw } };
}

// Event context. The value is transported as typed; whether the event exists in
// this capture is decided by the action tree in the query layer, which already
// classifies an unknown event as bad_request. Nothing here infers a range from
// the number, because the legal set is membership rather than an interval -- the
// message that says "events 1..12" is not the set of events that exist.
export function eidParam(raw) {
  const value = (raw || "").trim();
  return value ? "&eid=" + encodeURIComponent(value) : "";
}