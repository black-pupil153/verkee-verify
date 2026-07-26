const assert = require("node:assert/strict");
const test = require("node:test");

const { AiVerifyBridge, AiVerifyBridgeError } = require("../out/bridge");

const doctorPayload = {
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
};

const tasksPayload = {
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
};

const taskPayload = {
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
};

function bridgeWithResponses(responses) {
  const calls = [];
  const runner = async (executable, args, options) => {
    calls.push({ executable, args, options });
    const key = args.join(" ");
    if (!(key in responses)) {
      throw new Error(`Unexpected command: ${key}`);
    }
    const response = responses[key];
    if (response instanceof Error || (response && response.reject)) {
      throw response.reject || response;
    }
    return { stdout: JSON.stringify(response) };
  };
  return { bridge: new AiVerifyBridge(() => "/custom/verkeep-verify", runner), calls };
}

test("doctor JSON contract and command", async () => {
  const { bridge, calls } = bridgeWithResponses({
    "cursor doctor --json": doctorPayload,
  });

  const result = await bridge.doctor();
  assert.equal(result.ok, true);
  assert.equal(result.checks[1].optional, true);
  assert.equal(result.warnings[0].name, "proxy supplement");
  assert.deepEqual(result.checks, doctorPayload.checks);
  assert.equal(calls[0].executable, "/custom/verkeep-verify");
  assert.deepEqual(calls[0].args, ["cursor", "doctor", "--json"]);
});

test("tasks JSON contract and limit", async () => {
  const { bridge, calls } = bridgeWithResponses({
    "cursor tasks --json --limit 7 --since 30d": tasksPayload,
  });

  const result = await bridge.tasks(7);
  assert.equal(result.count, 1);
  assert.equal(result.tasks[0].task_id, "task-1");
  assert.deepEqual(result.tasks[0].model_request_shares, { "claude-sonnet": 1 });
  assert.deepEqual(calls[0].args, [
    "cursor",
    "tasks",
    "--json",
    "--limit",
    "7",
    "--since",
    "30d",
  ]);
});

test("specified and latest task JSON contracts", async () => {
  const { bridge, calls } = bridgeWithResponses({
    "cursor task task-1 --json": taskPayload,
    "cursor task --latest --json": taskPayload,
  });

  const specified = await bridge.task("task-1");
  const latest = await bridge.taskLatest();
  assert.equal(specified.coverage, 0.75);
  assert.equal(specified.factual_request_shares["claude-sonnet"].count, 1);
  assert.equal(latest.pending_infer_count, 1);
  assert.deepEqual(calls.map((call) => call.args), [
    ["cursor", "task", "task-1", "--json"],
    ["cursor", "task", "--latest", "--json"],
  ]);
});

test("recent import uses configured executable without requiring Cursor data", async () => {
  const calls = [];
  const runner = async (executable, args, options) => {
    calls.push({ executable, args, options });
    return { stdout: "imported" };
  };
  const bridge = new AiVerifyBridge(() => "/configured/verkeep-verify", runner);

  await bridge.importRecent("1d");
  assert.equal(calls[0].executable, "/configured/verkeep-verify");
  assert.deepEqual(calls[0].args, ["cursor", "import", "--since", "1d"]);
  assert.equal(calls[0].options.timeout, 60_000);
});

test("invalid JSON is classified", async () => {
  const runner = async () => ({ stdout: "not-json" });
  const bridge = new AiVerifyBridge(() => "verkeep-verify", runner);

  await assert.rejects(
    bridge.doctor(),
    (error) => error instanceof AiVerifyBridgeError && error.kind === "invalid-json"
  );
});

test("timeout is classified without exposing child output", async () => {
  const runner = async () => {
    throw { killed: true, signal: "SIGTERM", stderr: "private conversation text" };
  };
  const bridge = new AiVerifyBridge(() => "verkeep-verify", runner);

  await assert.rejects(bridge.doctor(), (error) => {
    assert.equal(error.kind, "timeout");
    assert.doesNotMatch(error.message, /private conversation text/);
    return true;
  });
});

test("non-zero exit is classified without exposing stderr", async () => {
  const runner = async () => {
    throw { code: 2, stderr: "sk-secret and prompt body" };
  };
  const bridge = new AiVerifyBridge(() => "verkeep-verify", runner);

  await assert.rejects(bridge.tasks(), (error) => {
    assert.equal(error.kind, "command-failed");
    assert.match(error.message, /exit 2/);
    assert.doesNotMatch(error.message, /sk-secret|prompt body/);
    return true;
  });
});
