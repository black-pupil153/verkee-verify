const vscode = acquireVsCodeApi();

const el = {
  status: document.getElementById("status"),
  notice: document.getElementById("notice"),
  doctor: document.getElementById("doctor"),
  tasks: document.getElementById("tasks"),
  report: document.getElementById("report"),
  refresh: document.getElementById("refresh"),
};

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
    el.doctor.innerHTML = msg.fix
      ? `<p class="fix">${escapeHtml(msg.fix)}</p>`
      : "";
    return;
  }
  if (msg.type === "doctor") {
    renderDoctor(msg.data);
  }
  if (msg.type === "tasks") {
    renderTasks(msg.data);
  }
  if (msg.type === "task") {
    renderReport(msg.data);
  }
});

function renderDoctor(data) {
  if (!data) return;
  const warnings = data.warnings || (data.checks || []).filter(
    (c) => c.optional && (!c.ok || c.severity === "warning")
  );
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
  el.doctor.innerHTML = `
    <div class="pill ${pillClass}">${escapeHtml(pillLabel)}</div>
    ${failedNames.length ? `<p class="muted">Failed: ${escapeHtml(failedNames.join(", "))}</p>` : ""}
    ${warningNames.length ? `<p class="muted">Optional warnings: ${escapeHtml(warningNames.join(", "))}</p>` : ""}
    ${data.suggestion ? `<p class="fix">${escapeHtml(data.suggestion)}</p>` : ""}
  `;
  if (!data.ok) {
    el.status.textContent = "Fix required doctor issues to load shares";
  } else if (warnings.length) {
    el.status.textContent = "Ready (optional sources degraded)";
  } else {
    el.status.textContent = "Ready";
  }
}

function renderTasks(data) {
  const tasks = (data && data.tasks) || [];
  if (!tasks.length) {
    el.tasks.innerHTML = `<p class="muted">No recent sessions found. VerAI already tried a background import; use <code>ai-verify cursor import --since 7d</code> to scan a wider window.</p>`;
    return;
  }
  el.tasks.innerHTML = `
    <h2>Recent sessions</h2>
    <ul class="task-list">
      ${tasks
        .map(
          (t) => `
        <li>
          <button type="button" data-id="${escapeAttr(t.task_id)}">
            <span class="title">${escapeHtml(t.title || "(untitled)")}</span>
            <span class="meta">${escapeHtml(t.route_kind)} · ${t.request_count} req</span>
          </button>
        </li>`
        )
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
  el.report.innerHTML = `
    <h2>${escapeHtml(data.title || data.task_id.slice(0, 8))}</h2>
    <p class="meta">${escapeHtml(data.mode)} · ${escapeHtml(data.route_kind)} · coverage ${cov}% · pending-infer ${data.pending_infer_count || 0}</p>
    <p class="disclaimer">推断 ≠ 官方真名；仅 factual 为遥测事实。</p>
    ${shareBlock("事实轨（请求）", data.factual_request_shares)}
    ${shareBlock("推断轨（请求）", data.inferred_request_shares)}
    ${shareBlock("产出占比", data.factual_output_shares || data.output_shares)}
  `;
  el.status.textContent = `Loaded ${data.task_id.slice(0, 8)}`;
}

function shareBlock(label, shares) {
  const entries = Object.entries(shares || {}).sort((a, b) => (b[1].pct || 0) - (a[1].pct || 0));
  if (!entries.length) {
    return `<div class="block"><h3>${escapeHtml(label)}</h3><p class="muted">—</p></div>`;
  }
  const bars = entries
    .map(([model, info]) => {
      const pct = Number(info.pct || 0);
      return `<div class="row"><span class="model">${escapeHtml(model)}</span>
        <div class="bar"><i style="width:${Math.min(100, pct)}%"></i></div>
        <span class="pct">${pct.toFixed(0)}%</span></div>`;
    })
    .join("");
  return `<div class="block"><h3>${escapeHtml(label)}</h3>${bars}</div>`;
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
