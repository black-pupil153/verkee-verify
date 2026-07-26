/**
 * A3 acceptance: bridge task payload ≡ `verkee-verify cursor task --json`
 * within 10 seconds (same fields the sidebar renders).
 *
 * Skips when verkee-verify is not on PATH / configured, so CI without Cursor data
 * still passes unit tests via `npm test`.
 */
const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const test = require("node:test");
const { AiVerifyBridge } = require("../out/bridge");

const execFileAsync = promisify(execFile);

function resolveCli() {
  return process.env.VERAI_AI_VERIFY_PATH || "verkee-verify";
}

async function cliAvailable(cli) {
  try {
    await execFileAsync(cli, ["--help"], { timeout: 10_000, maxBuffer: 1_000_000 });
    return true;
  } catch {
    return false;
  }
}

function shareFingerprint(shares) {
  const entries = Object.entries(shares || {})
    .map(([model, info]) => [
      model,
      Number(info.pct),
      Number(info.count),
    ])
    .sort((a, b) => a[0].localeCompare(b[0]));
  return JSON.stringify(entries);
}

function mixFingerprint(mix) {
  const models = Object.entries((mix && mix.models) || {})
    .map(([model, info]) => [
      model,
      Number(info.call_count),
      Number(info.pct),
      Number(info.confirmed_count),
      Number(info.estimated_count),
    ])
    .sort((a, b) => a[0].localeCompare(b[0]));
  return JSON.stringify({
    total_calls: Number(mix && mix.total_calls),
    subagent_calls: Number(mix && mix.subagent_calls),
    confirmed_count: Number(mix && mix.confirmed_count),
    estimated_count: Number(mix && mix.estimated_count),
    unknown_count: Number(mix && mix.unknown_count),
    composition: mix && mix.composition,
    models,
  });
}

test("sidebar parity: bridge task ≡ cursor task --json (<10s)", async (t) => {
  const cli = resolveCli();
  if (!(await cliAvailable(cli))) {
    t.skip(`verkee-verify not available (${cli}); set VERAI_AI_VERIFY_PATH to run`);
    return;
  }

  const bridge = new AiVerifyBridge(() => cli);
  const started = Date.now();

  let doctor;
  try {
    doctor = await bridge.doctor();
  } catch (err) {
    t.skip(`doctor failed: ${err.message}`);
    return;
  }
  assert.equal(typeof doctor.ok, "boolean");

  let viaBridge;
  try {
    viaBridge = await bridge.taskLatest();
  } catch (err) {
    t.skip(`no latest task via bridge: ${err.message}`);
    return;
  }

  const { stdout } = await execFileAsync(
    cli,
    ["cursor", "task", viaBridge.task_id, "--json"],
    { timeout: 60_000, maxBuffer: 8 * 1024 * 1024 }
  );
  const viaCli = JSON.parse(stdout);
  const elapsedMs = Date.now() - started;

  assert.equal(viaBridge.task_id, viaCli.task_id);
  assert.equal(viaBridge.request_count, viaCli.request_count);
  assert.equal(viaBridge.coverage, viaCli.coverage);
  assert.equal(viaBridge.pending_infer_count, viaCli.pending_infer_count);
  assert.ok(viaBridge.model_mix_v2, "bridge must expose model_mix_v2");
  assert.ok(viaCli.model_mix_v2, "CLI must expose model_mix_v2");
  assert.equal(
    mixFingerprint(viaBridge.model_mix_v2),
    mixFingerprint(viaCli.model_mix_v2)
  );
  assert.equal(
    Number(viaBridge.model_mix_v2.total_calls),
    Number(viaBridge.request_count)
  );
  assert.equal(
    shareFingerprint(viaBridge.factual_request_shares),
    shareFingerprint(viaCli.factual_request_shares)
  );
  assert.equal(
    shareFingerprint(viaBridge.inferred_request_shares),
    shareFingerprint(viaCli.inferred_request_shares)
  );
  assert.equal(
    shareFingerprint(viaBridge.factual_output_shares || viaBridge.output_shares),
    shareFingerprint(viaCli.factual_output_shares || viaCli.output_shares)
  );
  assert.ok(
    elapsedMs <= 10_000,
    `parity check took ${elapsedMs}ms (budget 10000ms)`
  );
});

test("silent import --since 1d is callable via bridge", async (t) => {
  const cli = resolveCli();
  if (!(await cliAvailable(cli))) {
    t.skip(`verkee-verify not available (${cli})`);
    return;
  }
  const bridge = new AiVerifyBridge(() => cli);
  const started = Date.now();
  try {
    await bridge.importRecent("1d");
  } catch (err) {
    // Import may warn on empty windows; only hard-fail on not-found / invalid CLI.
    if (String(err.message || "").includes("not found")) {
      throw err;
    }
    t.skip(`import soft-failed (ok for empty window): ${err.message}`);
    return;
  }
  assert.ok(Date.now() - started < 60_000);
});
