const vscode = acquireVsCodeApi();

const el = {
  status: document.getElementById("status"),
  notice: document.getElementById("notice"),
  doctor: document.getElementById("doctor"),
  tasks: document.getElementById("tasks"),
  report: document.getElementById("report"),
  refresh: document.getElementById("refresh"),
};

let selectedTaskId = null;
let lastTasks = [];

const UNKNOWN_LABEL = "未识别";

el.refresh.addEventListener("click", () => {
  el.status.textContent = "Refreshing…";
  vscode.postMessage({ type: "refresh" });
});

window.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type === "notice") {
    el.notice.innerHTML = msg.message
      ? `<p class="notice">${escapeHtml(msg.message)}</p>`
      : "";
    return;
  }
  if (msg.type === "error") {
    el.status.textContent = msg.message || "Error";
    const action =
      msg.fixAction === "openSettings"
        ? `<p><button type="button" id="open-settings">Open Verkee Verify Settings</button></p>`
        : "";
    el.doctor.innerHTML = `
      ${msg.fix ? `<p class="fix">${escapeHtml(msg.fix)}</p>` : ""}
      ${action}
    `;
    const btn = document.getElementById("open-settings");
    if (btn) {
      btn.addEventListener("click", () => {
        vscode.postMessage({ type: "openSettings" });
      });
    }
    return;
  }
  if (msg.type === "doctor") {
    renderDoctor(msg.data);
  }
  if (msg.type === "tasks") {
    lastTasks = (msg.data && msg.data.tasks) || [];
    renderTasks(lastTasks);
  }
  if (msg.type === "task") {
    if (msg.data && msg.data.task_id) {
      selectedTaskId = msg.data.task_id;
      renderTasks(lastTasks);
    }
    renderReport(msg.data);
  }
});

function renderDoctor(data) {
  if (!data) return;
  const warnings =
    data.warnings ||
    (data.checks || []).filter((c) => c.optional && (!c.ok || c.severity === "warning"));
  const blocking = (data.checks || []).filter((c) => !c.ok && !c.optional);
  let pillClass = "ok";
  let pillLabel = "doctor green";
  if (!data.ok) {
    pillClass = "bad";
    pillLabel = "doctor needs fix";
  } else if (warnings.length) {
    pillClass = "warn";
    pillLabel = `doctor green · ${warnings.length} warning${warnings.length === 1 ? "" : "s"}`;
  }
  const failedNames = blocking.map((c) => c.name);
  const warningNames = warnings.map((c) => c.name);
  const fixHint = !data.ok
    ? `<p class="fix">Run <code>verkee-verify cursor doctor</code> in a terminal, then Refresh. If CLI is missing, set <code>verai.aiVerifyPath</code>.</p>
       <p><button type="button" id="open-settings">Open Verkee Verify Settings</button></p>`
    : "";
  el.doctor.innerHTML = `
    <div class="pill ${pillClass}">${escapeHtml(pillLabel)}</div>
    ${failedNames.length ? `<p class="muted">Failed: ${escapeHtml(failedNames.join(", "))}</p>` : ""}
    ${warningNames.length ? `<p class="muted">Optional warnings: ${escapeHtml(warningNames.join(", "))}</p>` : ""}
    ${data.suggestion ? `<p class="fix">${escapeHtml(data.suggestion)}</p>` : ""}
    ${fixHint}
  `;
  const btn = document.getElementById("open-settings");
  if (btn) {
    btn.addEventListener("click", () => {
      vscode.postMessage({ type: "openSettings" });
    });
  }
  if (!data.ok) {
    el.status.textContent = "Doctor needs fix — shares may still load from cache";
  } else if (warnings.length) {
    el.status.textContent = "Ready (optional sources degraded)";
  } else {
    el.status.textContent = "Ready";
  }
}

function renderTasks(tasks) {
  if (!tasks.length) {
    el.tasks.innerHTML = `<p class="muted">No recent sessions found. Verkee Verify already tried a background import; use <code>verkee-verify cursor import --since 7d</code> to scan a wider window.</p>`;
    return;
  }
  el.tasks.innerHTML = `
    <h2>Recent sessions</h2>
    <ul class="task-list">
      ${tasks
        .map((t) => {
          const selected = t.task_id === selectedTaskId ? " selected" : "";
          return `
        <li>
          <button type="button" class="task-btn${selected}" data-id="${escapeAttr(t.task_id)}">
            <span class="title">${escapeHtml(t.title || "(untitled)")}</span>
            <span class="meta">${t.request_count} 次模型调用</span>
          </button>
        </li>`;
        })
        .join("")}
    </ul>
  `;
  el.tasks.querySelectorAll("button[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      vscode.postMessage({ type: "selectTask", taskId: btn.getAttribute("data-id") });
    });
  });
}

function resolveMix(data) {
  if (data.model_mix_v2 && data.model_mix_v2.models) {
    return data.model_mix_v2;
  }
  // v1 fallback: merge factual + inferred request shares into call counts
  const counts = {};
  const add = (shares, estimated) => {
    Object.entries(shares || {}).forEach(([model, info]) => {
      const n = Number(info.count || 0);
      if (!n) return;
      const label = isUnknownLabel(model) ? UNKNOWN_LABEL : model;
      if (!counts[label]) {
        counts[label] = { call_count: 0, confirmed_count: 0, estimated_count: 0 };
      }
      counts[label].call_count += n;
      if (estimated) counts[label].estimated_count += n;
      else counts[label].confirmed_count += n;
    });
  };
  add(data.factual_request_shares, false);
  add(data.inferred_request_shares, true);
  const pending = Number(data.pending_infer_count || 0);
  if (pending > 0) {
    if (!counts[UNKNOWN_LABEL]) {
      counts[UNKNOWN_LABEL] = { call_count: 0, confirmed_count: 0, estimated_count: 0 };
    }
    counts[UNKNOWN_LABEL].call_count += pending;
  }
  const total = Object.values(counts).reduce((s, m) => s + m.call_count, 0) || 0;
  const models = {};
  Object.entries(counts)
    .sort((a, b) => b[1].call_count - a[1].call_count)
    .forEach(([model, info]) => {
      models[model] = {
        ...info,
        pct: total ? (info.call_count / total) * 100 : 0,
      };
    });
  const estimated = Object.values(counts).reduce((s, m) => s + m.estimated_count, 0);
  const unknown = counts[UNKNOWN_LABEL] ? counts[UNKNOWN_LABEL].call_count : 0;
  let composition = "confirmed_only";
  if (unknown > 0) composition = "partial";
  else if (estimated > 0) composition = "includes_estimates";
  return {
    total_calls: total,
    subagent_calls: 0,
    confirmed_count: total - estimated - unknown,
    estimated_count: estimated,
    unknown_count: unknown,
    composition,
    models,
  };
}

function renderReport(data) {
  if (!data || data.error) {
    el.report.innerHTML = `<p class="muted">${escapeHtml((data && data.error) || "No task selected")}</p>`;
    return;
  }
  const mix = resolveMix(data);
  const entries = Object.entries(mix.models || {}).sort(
    (a, b) => (b[1].pct || 0) - (a[1].pct || 0)
  );
  const hintParts = [];
  if (mix.estimated_count > 0) {
    hintParts.push("部分结果为估算，非 Cursor 官方逐次真名");
  }
  if (mix.unknown_count > 0) {
    hintParts.push(`${mix.unknown_count} 次未识别`);
  }
  const hint =
    hintParts.length > 0
      ? `<p class="hint">${escapeHtml(hintParts.join(" · "))}</p>`
      : "";

  const allUnknown =
    mix.total_calls > 0 && mix.unknown_count === mix.total_calls
      ? `<p class="hint">全部未识别。尝试 Refresh，或检查 Cursor hooks 是否已安装。</p>`
      : "";

  el.report.innerHTML = `
    <h2>${escapeHtml(data.title || shortId(data.task_id))}</h2>
    <p class="meta">${mix.total_calls || data.request_count || 0} 次模型调用${
      mix.subagent_calls ? ` · 含副代理 ${mix.subagent_calls}` : ""
    }</p>
    <div class="block">
      <h3>本会话模型构成</h3>
      ${mixStack(entries)}
      ${mixTable(entries)}
      ${hint}
      ${allUnknown}
      ${evidenceDetails(entries, mix)}
    </div>
  `;
  el.status.textContent = `Loaded ${shortId(data.task_id)}`;
}

function mixStack(entries) {
  if (!entries.length) {
    return `<p class="muted">—</p>`;
  }
  const stack = entries
    .map(([model, info], idx) => {
      const pct = Number(info.pct || 0);
      const unknown = isUnknownLabel(model);
      const cls = unknown ? "seg unknown" : `seg c${idx % 6}`;
      return `<i class="${cls}" style="width:${Math.min(100, pct)}%" title="${escapeAttr(model)} ${pct.toFixed(0)}%"></i>`;
    })
    .join("");
  return `<div class="stack">${stack}</div>`;
}

function mixTable(entries) {
  if (!entries.length) return "";
  const rows = entries
    .map(([model, info]) => {
      const pct = Number(info.pct || 0);
      const count = info.call_count != null ? info.call_count : info.count;
      return `<tr>
        <td class="model">${escapeHtml(model)}</td>
        <td class="pct">${pct.toFixed(0)}%</td>
        <td class="count">${escapeHtml(String(count))} 次</td>
      </tr>`;
    })
    .join("");
  return `<table class="share-table">
    <thead><tr><th>模型</th><th>%</th><th>调用</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function evidenceDetails(entries, mix) {
  const rows = entries
    .filter(([model, info]) => {
      if (isUnknownLabel(model)) return false;
      return (info.confirmed_count || 0) > 0 || (info.estimated_count || 0) > 0;
    })
    .map(([model, info]) => {
      const c = info.confirmed_count || 0;
      const e = info.estimated_count || 0;
      return `<li><strong>${escapeHtml(model)}</strong>：${c} 次确认 + ${e} 次估算</li>`;
    })
    .join("");
  let body;
  if (rows) {
    body = `<ul class="evidence-list">${rows}</ul>`;
  } else if (mix.composition === "confirmed_only") {
    body = `<p class="muted">全部来自 Cursor 遥测确认，无估算。</p>`;
  } else {
    body = `<p class="muted">暂无来源拆分。</p>`;
  }
  return `<details class="evidence">
    <summary>这是怎么判断的？</summary>
    ${body}
    <p class="disclaimer">本地计算，不读取/上传对话正文。估算 ≠ Cursor 官方逐次真名；确认来自本地遥测事实。</p>
  </details>`;
}

function isUnknownLabel(model) {
  const m = String(model || "").toLowerCase();
  return (
    model === UNKNOWN_LABEL ||
    m === "pending-infer" ||
    m === "auto-opaque" ||
    m === "unknown"
  );
}

function shortId(id) {
  return String(id || "").slice(0, 8);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}

vscode.postMessage({ type: "ready" });
