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
        ? `<p><button type="button" id="open-settings">Open VerAI Settings</button></p>`
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
    ? `<p class="fix">Run <code>ai-verify cursor doctor</code> in a terminal, then Refresh. If CLI is missing, set <code>verai.aiVerifyPath</code>.</p>
       <p><button type="button" id="open-settings">Open VerAI Settings</button></p>`
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
    el.tasks.innerHTML = `<p class="muted">No recent sessions found. VerAI already tried a background import; use <code>ai-verify cursor import --since 7d</code> to scan a wider window.</p>`;
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
            <span class="meta">${escapeHtml(t.route_kind)} · ${t.request_count} req · ${escapeHtml(shortId(t.task_id))}</span>
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

function renderReport(data) {
  if (!data || data.error) {
    el.report.innerHTML = `<p class="muted">${escapeHtml((data && data.error) || "No task selected")}</p>`;
    return;
  }
  const cov = ((data.coverage || 0) * 100).toFixed(0);
  const pending = data.pending_infer_count || 0;
  el.report.innerHTML = `
    <h2>${escapeHtml(data.title || shortId(data.task_id))}</h2>
    <p class="meta">${escapeHtml(data.mode)} · ${escapeHtml(data.route_kind)} · <code>${escapeHtml(data.task_id)}</code></p>
    <p class="trust">coverage <strong>${cov}%</strong> · pending-infer ${pending}</p>
    <p class="disclaimer">推断 ≠ 官方真名；仅 factual 为遥测事实。推断不写 resolved_model。</p>
    ${shareBlock("事实轨（请求）", data.factual_request_shares, { track: "factual" })}
    ${shareBlock("推断轨（请求）", data.inferred_request_shares, { track: "inferred" })}
    ${shareBlock("产出占比（事实）", data.factual_output_shares || data.output_shares, { track: "factual" })}
  `;
  el.status.textContent = `Loaded ${shortId(data.task_id)}`;
}

function shareBlock(label, shares, { track } = {}) {
  const entries = Object.entries(shares || {}).sort(
    (a, b) => (b[1].pct || 0) - (a[1].pct || 0)
  );
  if (!entries.length) {
    return `<div class="block"><h3>${escapeHtml(label)}</h3><p class="muted">—</p></div>`;
  }
  const stack = entries
    .map(([model, info], idx) => {
      const pct = Number(info.pct || 0);
      const pending = isPendingInfer(model);
      const cls = pending ? "seg pending" : `seg c${idx % 6}`;
      return `<i class="${cls}" style="width:${Math.min(100, pct)}%" title="${escapeAttr(model)} ${pct.toFixed(0)}%"></i>`;
    })
    .join("");
  const rows = entries
    .map(([model, info]) => {
      const pct = Number(info.pct || 0);
      const count = info.count != null ? info.count : "—";
      const pending = isPendingInfer(model);
      const name = pending
        ? `${escapeHtml(model)} <span class="badge">pending-infer</span>`
        : escapeHtml(model);
      const trackNote =
        track === "inferred" && !pending
          ? ` <span class="badge soft">inferred</span>`
          : "";
      return `<tr>
        <td class="model">${name}${trackNote}</td>
        <td class="pct">${pct.toFixed(1)}%</td>
        <td class="count">${escapeHtml(String(count))}</td>
      </tr>`;
    })
    .join("");
  return `<div class="block">
    <h3>${escapeHtml(label)}</h3>
    <div class="stack">${stack}</div>
    <table class="share-table">
      <thead><tr><th>model</th><th>%</th><th>count</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function isPendingInfer(model) {
  const m = String(model || "").toLowerCase();
  return m === "pending-infer" || m === "auto-opaque";
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
