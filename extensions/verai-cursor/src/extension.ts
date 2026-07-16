import * as vscode from "vscode";
import {
  AiVerifyBridge,
  AiVerifyBridgeError,
  DoctorPayload,
  TaskListPayload,
  TaskReportPayload,
} from "./bridge";

export function activate(context: vscode.ExtensionContext): void {
  const bridge = new AiVerifyBridge(() =>
    vscode.workspace.getConfiguration("verai").get<string>("aiVerifyPath", "ai-verify")
  );

  const provider = new SessionUsageViewProvider(context.extensionUri, bridge);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("verai.sessionView", provider)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("verai.showSessionUsage", () => provider.refresh()),
    vscode.commands.registerCommand("verai.refresh", () => provider.refresh()),
    vscode.commands.registerCommand("verai.openLatest", () => provider.openLatest())
  );
}

export function deactivate(): void {}

class SessionUsageViewProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;

  constructor(
    private readonly _extensionUri: vscode.Uri,
    private readonly _bridge: AiVerifyBridge
  ) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this._extensionUri, "media")],
    };
    webviewView.webview.html = this._html(webviewView.webview);

    webviewView.webview.onDidReceiveMessage(async (msg) => {
      if (msg?.type === "ready" || msg?.type === "refresh") {
        await this.refresh();
      } else if (msg?.type === "selectTask" && typeof msg.taskId === "string") {
        await this.loadTask(msg.taskId);
      } else if (msg?.type === "openLatest") {
        await this.openLatest();
      } else if (msg?.type === "openSettings") {
        await vscode.commands.executeCommand(
          "workbench.action.openSettings",
          "verai.aiVerifyPath"
        );
      }
    });
  }

  async refresh(): Promise<void> {
    const limit = vscode.workspace
      .getConfiguration("verai")
      .get<number>("tasksLimit", 15);

    this._post({ type: "notice", message: null });
    try {
      await this._bridge.importRecent("1d");
    } catch {
      this._post({
        type: "notice",
        message:
          "Could not import recent Cursor data. Showing cached data; run `ai-verify cursor import --since 1d` in a terminal for details.",
      });
    }

    try {
      const doctor = await this._bridge.doctor();
      const tasks = await this._bridge.tasks(limit);
      this._post({ type: "doctor", data: doctor });
      this._post({ type: "tasks", data: tasks });
      if (tasks.tasks?.length) {
        await this.loadTask(tasks.tasks[0].task_id);
      } else {
        this._post({ type: "task", data: null });
      }
    } catch (err) {
      this._postError(err);
    }
  }

  async openLatest(): Promise<void> {
    try {
      const report = await this._bridge.taskLatest();
      this._post({ type: "task", data: report });
    } catch (err) {
      this._postError(err);
    }
  }

  private async loadTask(taskId: string): Promise<void> {
    try {
      const report = await this._bridge.task(taskId);
      this._post({ type: "task", data: report });
    } catch (err) {
      this._postError(err);
    }
  }

  private _postError(err: unknown): void {
    if (err instanceof AiVerifyBridgeError) {
      const fixes: Record<AiVerifyBridgeError["kind"], string> = {
        "not-found":
          "Install the CLI, ensure `ai-verify` is on PATH, or set `verai.aiVerifyPath` to its absolute path.",
        timeout:
          "Try Refresh again. If it still times out, run `ai-verify cursor doctor` in a terminal.",
        "invalid-json":
          "Update the ai-verify CLI so its JSON contract matches this extension, then try Refresh again.",
        "command-failed":
          "Run `ai-verify cursor doctor` in a terminal for safe diagnostic details.",
      };
      this._post({
        type: "error",
        message: err.message,
        fix: fixes[err.kind],
        fixAction: err.kind === "not-found" ? "openSettings" : undefined,
      });
      return;
    }

    this._post({
      type: "error",
      message: "VerAI could not load session data.",
      fix: "Run `ai-verify cursor doctor` in a terminal, then try Refresh again.",
    });
  }

  private _post(payload: Record<string, unknown>): void {
    void this._view?.webview.postMessage(payload);
  }

  private _html(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "media", "main.js")
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "media", "main.css")
    );
    const nonce = String(Date.now());
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <link href="${styleUri}" rel="stylesheet" />
  <title>VerAI</title>
</head>
<body>
  <header>
    <h1>VerAI</h1>
    <p class="tagline">这个会话里各模型实际占比（事实 vs 推断）· 本地计算</p>
    <button id="refresh" type="button">Refresh</button>
  </header>
  <section id="status" class="muted">Loading…</section>
  <section id="notice"></section>
  <section id="doctor"></section>
  <section id="tasks"></section>
  <section id="report"></section>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}

export type { DoctorPayload, TaskListPayload, TaskReportPayload };
