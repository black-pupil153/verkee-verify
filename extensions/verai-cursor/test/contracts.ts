import type {
  DoctorPayload,
  TaskListPayload,
  TaskReportPayload,
} from "../src/bridge";

export const doctorContract = {
  ok: true,
  checks: [
    {
      name: "workspaceStorage",
      ok: true,
      detail: "found",
      optional: false,
      severity: "error",
    },
    {
      name: "proxy supplement",
      ok: false,
      detail: "0 cursor-related api_calls (optional)",
      optional: true,
      severity: "warning",
    },
  ],
  warnings: [
    {
      name: "proxy supplement",
      detail: "0 cursor-related api_calls (optional)",
      severity: "warning",
    },
  ],
  suggestion: "ready",
} satisfies DoctorPayload;

export const taskListContract = {
  since: "30d",
  count: 1,
  tasks: [
    {
      task_id: "task-1",
      title: "Contract test",
      mode: "agent",
      route_kind: "auto",
      request_count: 3,
      code_unit_count: 2,
      started_at: "2026-07-14T00:00:00Z",
      model_request_shares: { "claude-sonnet": 1 },
    },
  ],
} satisfies TaskListPayload;

export const taskReportContract = {
  task_id: "task-1",
  title: "Contract test",
  mode: "agent",
  route_kind: "auto",
  request_count: 3,
  code_unit_count: 2,
  coverage: 0.75,
  pending_infer_count: 1,
  factual_request_shares: { "claude-sonnet": { pct: 50, count: 1 } },
  inferred_request_shares: { composer: { pct: 50, count: 1 } },
  factual_output_shares: { "claude-sonnet": { pct: 60, count: 120 } },
  output_shares: { "claude-sonnet": { pct: 60, count: 120 } },
  disclaimer: "Inference is not provider truth.",
} satisfies TaskReportPayload;
