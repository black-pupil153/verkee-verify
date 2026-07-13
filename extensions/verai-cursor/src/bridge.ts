import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export type DoctorPayload = {
  ok: boolean;
  checks: Array<{ name: string; ok: boolean; detail: string }>;
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
  disclaimer?: string;
  error?: string;
};

export class AiVerifyBridge {
  constructor(private readonly getCliPath: () => string) {}

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
    const cli = this.getCliPath();
    try {
      const { stdout } = await execFileAsync(cli, args, {
        maxBuffer: 8 * 1024 * 1024,
        timeout: 60_000,
      });
      return JSON.parse(stdout) as T;
    } catch (err: unknown) {
      const e = err as { code?: string; stderr?: string; message?: string };
      if (e.code === "ENOENT") {
        throw new Error(
          `ai-verify CLI not found at "${cli}". Set setting verai.aiVerifyPath or install with pip install -e .`
        );
      }
      const detail = (e.stderr || e.message || String(err)).trim();
      throw new Error(`ai-verify ${args.join(" ")} failed: ${detail}`);
    }
  }
}
