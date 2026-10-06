import React from "react";

/** A titled surface. `tone` lifts one panel above the others. */
export function Panel({ title, actions, tone, className = "", children, ...rest }) {
  return (
    <section
      className={
        "panel" + (tone ? " panel--" + tone : "") + (className ? " " + className : "")
      }
      {...rest}
    >
      <div className="panel__head">
        <h2 className="panel__title">{title}</h2>
        <div className="topbar__spacer" />
        {actions}
      </div>
      <div className="panel__body">{children}</div>
    </section>
  );
}

export function Section({ title, children }) {
  return (
    <div className="panel__section">
      {title ? <p className="panel__subtitle">{title}</p> : null}
      {children}
    </div>
  );
}

/**
 * One button, three visual weights.
 *
 * `primary` is filled, `ghost` is borderless. There is deliberately no fourth:
 * every extra weight is one more thing a reader has to rank, and two is enough
 * to separate "what this page is for" from "everything else".
 */
export function Button({ primary, ghost, busy, children, className = "", ...rest }) {
  const kind = primary ? " btn--primary" : ghost ? " btn--ghost" : "";
  return (
    <button
      type="button"
      className={"btn" + kind + (className ? " " + className : "")}
      aria-busy={busy ? "true" : undefined}
      {...rest}
    >
      {busy ? <span className="btn__spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

export function Field({ id, label, children }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}

export function Checkbox({ id, label, checked, onChange }) {
  return (
    <div className="field checkbox">
      <input
        type="checkbox"
        id={id}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <label htmlFor={id}>{label}</label>
    </div>
  );
}

/**
 * Status pill. `live` gets a pulsing dot, so connection state is legible
 * peripherally rather than only by reading the word beside it.
 *
 * Rest props are forwarded deliberately: a component that silently drops
 * `data-testid` makes its own controls untestable, which is worse than not
 * having the component.
 */
export function Badge({ tone, dot, title, children, ...rest }) {
  return (
    <span className={"badge badge--" + tone} title={title} {...rest}>
      {dot ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

export function Alert({ tone = "warn", icon = "!", title, children, ...rest }) {
  return (
    <div className={"alert alert--" + tone} role="alert" {...rest}>
      <span className="alert__icon" aria-hidden="true">
        {icon}
      </span>
      <div className="alert__body">
        {title ? <b>{title}</b> : null}
        {children}
      </div>
    </div>
  );
}

/**
 * The empty state. A blank panel and "there is no result" look identical, so
 * the panel always says which of the two it is.
 */
export function EmptyState({ children, hint }) {
  return (
    <div className="empty" data-testid="empty-state">
      <span>{children}</span>
      {hint ? <span className="empty__hint">{hint}</span> : null}
    </div>
  );
}

/**
 * Loading skeleton. Approximates the shape of the answer instead of spinning in
 * the corner of an otherwise empty panel.
 */
export function Skeleton({ rows = 3, testId = "loading" }) {
  const widths = ["skeleton__row--mid", "skeleton__row", "skeleton__row--short"];
  return (
    <div className="skeleton" data-testid={testId} aria-live="polite">
      <span className="muted">loading…</span>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className={"skeleton__row " + widths[i % widths.length]} />
      ))}
    </div>
  );
}

/** Term/value pairs as a description list, so the pairing is announced. */
export function KeyValues({ rows }) {
  return (
    <dl className="kv">
      {rows.map(([term, value]) => (
        <React.Fragment key={term}>
          <dt>{term}</dt>
          {/* A value that is neither a string nor a node is rendered as JSON
              rather than handed to React as a child. React throws on an object
              child, an uncaught render error unmounts the tree, and the whole
              page goes blank -- so one unexpected field in one payload took the
              app down. A stringified object is dull and cannot do that. */}
          <dd className={isScalar(value) ? "mono" : undefined}>
            {isScalar(value) ? value : JSON.stringify(value)}
          </dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function isScalar(value) {
  return (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value == null ||
    React.isValidElement(value)
  );
}