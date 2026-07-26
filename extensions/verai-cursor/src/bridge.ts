import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

type CommandOptions = {
  maxBuffer: number;
  timeout: number;
};

export type CommandRunner = (
  executable: string,
  args: string[],
  options: CommandOptions
) => Promise<{ stdout: string }>;

export type BridgeFailureKind =
  | "not-found"
  | "timeout"
  | "invalid-json"
  | "command-failed";

export class AiVerifyBridgeError extends Error {
  constructor(
    readonly kind: BridgeFailureKind,
    message: string
  ) {
    super(message);
    this.name = "AiVerifyBridgeError";
  }
}

export type DoctorPayload = {
  ok: boolean;
  checks: Array<{
    name: string;
    ok: boolean;
    detail: string;
    optional?: boolean;
    severity?: "error" | "warning" | "info";
  }>;
  warnings?: Array<{ name: string; detail: string; severity?: string }>;
  suggestion?: string;
};

export type TaskListPayload = {
  since: string;
  count: number;
  tasks: Array<{
    task_id: string;
    title?: string | null;
    mode: string;
    route_kind: string;
    request_count: number;
    code_unit_count: number;
    started_at?: string | null;
    model_request_shares: Record<string, number>;
  }>;
};

export type ModelMixV2Entry = {
  call_count: number;
  pct: number;
  confirmed_count: number;
  estimated_count: number;
};

export type ModelMixV2 = {
  total_calls: number;
  subagent_calls: number;
  confirmed_count: number;
  estimated_count: number;
  unknown_count: number;
  composition: "confirmed_only" | "includes_estimates" | "partial";
  models: Record<string, ModelMixV2Entry>;
};

export type TaskReportPayload = {
  task_id: string;
  title?: string | null;
  mode: string;
  route_kind: string;
  request_count: number;
  code_unit_count: number;
  coverage: number;
  pending_infer_count: number;
  factual_request_shares: Record<string, { pct: number; count: number }>;
  inferred_request_shares: Record<string, { pct: number; count: number }>;
  factual_output_shares: Record<string, { pct: number; count: number }>;
  output_shares: Record<string, { pct: number; count: number }>;
  /** Preferred product contract; extension falls back to dual-track shares if absent. */
  model_mix_v2?: ModelMixV2;
  disclaimer?: string;
  error?: string;
};

export class AiVerifyBridge {
  constructor(
    private readonly getCliPath: () => string,
    private readonly runCommand: CommandRunner = execFileAsync as CommandRunner
  ) {}

  async importRecent(since = "1d"): Promise<void> {
    await this.run(["cursor", "import", "--since", since]);
  }

  async doctor(): Promise<DoctorPayload> {
    return this.runJson<DoctorPayload>(["cursor", "doctor", "--json"]);
  }

  async tasks(limit = 15): Promise<TaskListPayload> {
    return this.runJson<TaskListPayload>([
      "cursor",
      "tasks",
      "--json",
      "--limit",
      String(limit),
      "--since",
      "30d",
    ]);
  }

  async task(taskId: string): Promise<TaskReportPayload> {
    return this.runJson<TaskReportPayload>(["cursor", "task", taskId, "--json"]);
  }

  async taskLatest(): Promise<TaskReportPayload> {
    return this.runJson<TaskReportPayload>(["cursor", "task", "--latest", "--json"]);
  }

  private async runJson<T>(args: string[]): Promise<T> {
    const stdout = await this.run(args);
    try {
      return JSON.parse(stdout) as T;
    } catch {
      throw new AiVerifyBridgeError(
        "invalid-json",
        `verkee-verify ${args.join(" ")} returned invalid JSON`
      );
    }
  }

  private async run(args: string[]): Promise<string> {
    const cli = this.getCliPath();
    try {
      const { stdout } = await this.runCommand(cli, args, {
        maxBuffer: 8 * 1024 * 1024,
        timeout: 60_000,
      });
      return stdout;
    } catch (err: unknown) {
      const e = err as {
        code?: string | number | null;
        killed?: boolean;
        signal?: string | null;
      };
      if (e.code === "ENOENT") {
        throw new AiVerifyBridgeError(
          "not-found",
          `verkee-verify CLI not found at "${cli}". Set setting verai.aiVerifyPath or install with pip install -e .`
        );
      }
      if (e.killed || e.signal === "SIGTERM" || e.code === "ETIMEDOUT") {
        throw new AiVerifyBridgeError(
          "timeout",
          `verkee-verify ${args.join(" ")} timed out after 60 seconds`
        );
      }
      const exitCode = typeof e.code === "number" ? ` (exit ${e.code})` : "";
      throw new AiVerifyBridgeError(
        "command-failed",
        `verkee-verify ${args.join(" ")} failed${exitCode}`
      );
    }
  }
}
