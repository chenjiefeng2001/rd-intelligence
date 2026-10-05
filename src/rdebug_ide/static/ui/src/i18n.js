// Interface strings. English is the default, matching the frozen page: every
// frozen control asserts English source literals, and having two pages disagree
// about the default language would be a difference with no defensible reason.

export const I18N = {
  en: {
    langLabel: "中文",
    h: {
      query: "Query",
      result: "Result",
      evidence: "Evidence",
      prompt: "AI Prompt (grounded)",
      stream: "Server stream",
    },
    l: {
      a: "A (x,y)",
      b: "B (x,y)",
      deep: "deep diff (shader debugger)",
      eid: "Event ID (optional)",
    },
    b: {
      diff: "Diff A vs B",
      trace: "Trace A",
      explain: "Generate AI Prompt",
      copy: "Copy prompt",
      copied: "Copied",
    },
    eidScope:
      "Applies to: <b>Trace</b>, <b>Resource</b>. Does not apply to: <b>Diff</b>, <b>Generate AI Prompt</b> (they use the default event).",
    res: {
      blank: "run a query…",
      hint: "[Generate AI Prompt] run a diff first",
      loading: "loading…",
    },
    diff: {
      comparison: "comparison",
      firstDivergence: "first divergence",
      good: "good",
      bad: "bad",
      layers: "Layers",
    },
    trace: {
      target: "target",
      modifications: "modifications",
      finalValue: "final value",
      reads: "Reads",
      truncatedShort: " (truncated)",
      truncated:
        "Trace truncated &mdash; showing {n} of a larger set of modifications. This result is incomplete.",
      writtenBy: "written by {id}",
    },
    ci: { baseline: "CI baseline: not loaded", pass: "CI PASS" },
    stream: {
      live: "live",
      down: "reconnecting…",
      rev: "revision",
    },
    failure: {
      transport_error: "Cannot reach the rdebug-ide service",
      malformed: "The service returned a response that is not JSON",
      api_error: "The service rejected the request",
    },
  },
  zh: {
    langLabel: "English",
    h: {
      query: "查询",
      result: "结果",
      evidence: "证据",
      prompt: "AI 提示词（有依据）",
      stream: "服务端事件流",
    },
    l: {
      a: "A (x,y)",
      b: "B (x,y)",
      deep: "深度 diff（着色器调试器）",
      eid: "事件 ID（可选）",
    },
    b: {
      diff: "对比 A 与 B",
      trace: "追踪 A",
      explain: "生成 AI 提示词",
      copy: "复制提示词",
      copied: "已复制",
    },
    eidScope:
      "生效于：<b>追踪</b>、<b>资源</b>。不生效于：<b>对比</b>、<b>生成 AI 提示词</b>（二者使用默认事件）。",
    res: {
      blank: "执行一次查询…",
      hint: "[生成 AI 提示词] 先运行一次 diff",
      loading: "加载中…",
    },
    diff: {
      comparison: "对比结论",
      firstDivergence: "首个分歧",
      good: "A 值",
      bad: "B 值",
      layers: "分层",
    },
    trace: {
      target: "目标",
      modifications: "修改次数",
      finalValue: "最终值",
      reads: "读取来源",
      truncatedShort: "（已截断）",
      truncated: "追踪已截断 —— 仅显示较大修改集合中的 {n} 项。本结果不完整。",
      writtenBy: "写入者 {id}",
    },
    ci: { baseline: "CI 基线：未加载", pass: "CI 通过" },
    stream: { live: "已连接", down: "重连中…", rev: "修订号" },
    failure: {
      transport_error: "无法连接 rdebug-ide 服务",
      malformed: "服务返回的不是 JSON",
      api_error: "服务拒绝了该请求",
    },
  },
};

export function translator(lang) {
  const table = I18N[lang] || I18N.en;
  const fallback = I18N.en;
  const t = (group, key, vars) => {
    let s = (table[group] || {})[key];
    if (s === undefined) s = (fallback[group] || {})[key];
    if (s === undefined) return "";
    if (vars) {
      for (const k of Object.keys(vars)) {
        s = s.split("{" + k + "}").join(String(vars[k]));
      }
    }
    return s;
  };
  t.html = (group, key) => t(group, key);
  return t;
}