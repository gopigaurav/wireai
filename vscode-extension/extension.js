const vscode = require("vscode");
const path = require("path");
const fs = require("fs");

/** @type {vscode.WebviewView | undefined} */
let chatView;

function syncEditorBridge() {
  const editor = vscode.window.activeTextEditor;
  const folder = vscode.workspace.workspaceFolders?.[0];
  const workspaceFolder = folder?.uri.fsPath ?? "";
  if (!workspaceFolder || !editor) return;
  const activeFile = editor.document.uri.fsPath;
  if (editor.document.uri.scheme !== "file") return;
  const sel = editor.selection;
  const selection = sel.isEmpty ? "" : editor.document.getText(sel);
  const payload = {
    activeFile,
    workspaceFolder,
    selection,
    updatedAt: Date.now() / 1000,
  };
  const dir = path.join(workspaceFolder, ".voxprime");
  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, "editor_context.json"),
      JSON.stringify(payload, null, 2),
      "utf8"
    );
  } catch {
    /* ignore */
  }
}

function getIdeContext() {
  const editor = vscode.window.activeTextEditor;
  const folder = vscode.workspace.workspaceFolders?.[0];
  const ctx = {
    workspaceFolder: folder?.uri.fsPath ?? "",
  };
  if (editor) {
    ctx.activeFile = editor.document.uri.fsPath;
    const sel = editor.selection;
    if (!sel.isEmpty) {
      ctx.selection = editor.document.getText(sel);
    }
  }
  return ctx;
}

const chatQueue = [];
let chatDraining = false;

async function streamChat(webview, message) {
  const config = vscode.workspace.getConfiguration("voxprime");
  const base = (config.get("serverUrl") || "http://127.0.0.1:8765").replace(/\/$/, "");
  const url = `${base}/api/chat`;
  const ide_context = getIdeContext();

  webview.postMessage({ type: "streamStart" });

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, ide_context }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || res.statusText);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        webview.postMessage({ type: "streamEvent", event: ev });
      }
    }
  } catch (e) {
    webview.postMessage({
      type: "streamEvent",
      event: { type: "error", message: String(e.message || e) },
    });
  } finally {
    webview.postMessage({ type: "streamEnd" });
  }
}

async function drainChatQueue(webview) {
  if (chatDraining) return;
  chatDraining = true;
  while (chatQueue.length) {
    const { message } = chatQueue.shift();
    webview.postMessage({ type: "queueSize", size: chatQueue.length });
    await streamChat(webview, message);
  }
  chatDraining = false;
  webview.postMessage({ type: "queueSize", size: 0 });
}

function enqueueChat(webview, message) {
  chatQueue.push({ message });
  webview.postMessage({ type: "queueSize", size: chatQueue.length });
  drainChatQueue(webview);
}

function getWebviewHtml(webview, extensionUri) {
  const scriptUri = webview.asWebviewUri(
    vscode.Uri.joinPath(extensionUri, "media", "chat.js")
  );
  const styleUri = webview.asWebviewUri(
    vscode.Uri.joinPath(extensionUri, "media", "chat.css")
  );
  const nonce = String(Date.now());
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';" />
  <link rel="stylesheet" href="${styleUri}" />
</head>
<body>
  <div id="context" class="context"></div>
  <div id="messages"></div>
  <div id="status" class="status"></div>
  <footer>
    <textarea id="input" rows="2" placeholder="Ask VoxPrime…"></textarea>
    <button id="send" type="button">Send</button>
  </footer>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
}

function refreshContextBanner(webview) {
  const ctx = getIdeContext();
  const file = ctx.activeFile ? path.basename(ctx.activeFile) : "(no file)";
  const sel = ctx.selection ? " · selection attached" : "";
  webview.postMessage({
    type: "context",
    text: `${file}${sel}`,
  });
}

function activate(context) {
  syncEditorBridge();
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(() => {
      syncEditorBridge();
      if (chatView?.webview) refreshContextBanner(chatView.webview);
    }),
    vscode.window.onDidChangeTextEditorSelection(() => {
      syncEditorBridge();
    })
  );

  const provider = {
    resolveWebviewView(webviewView) {
      chatView = webviewView;
      const { webview, extensionUri } = webviewView;
      webview.options = { enableScripts: true, localResourceRoots: [extensionUri] };
      webview.html = getWebviewHtml(webview, extensionUri);

      webview.onDidReceiveMessage(async (msg) => {
        if (msg.type === "chat" && msg.text?.trim()) {
          enqueueChat(webview, msg.text.trim());
        }
        if (msg.type === "ready") {
          refreshContextBanner(webview);
        }
      });

      vscode.window.onDidChangeActiveTextEditor(() => {
        syncEditorBridge();
        refreshContextBanner(webview);
      });
      vscode.window.onDidChangeTextEditorSelection(() => {
        syncEditorBridge();
        refreshContextBanner(webview);
      });
    },
  };

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("voxprime.chatView", provider),
    vscode.commands.registerCommand("voxprime.focusChat", async () => {
      await vscode.commands.executeCommand("voxprime.chatView.focus");
    }),
    vscode.commands.registerCommand("voxprime.insertSelection", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.selection.isEmpty) {
        vscode.window.showWarningMessage("Select code first.");
        return;
      }
      await vscode.commands.executeCommand("voxprime.chatView.focus");
      const text = editor.document.getText(editor.selection);
      chatView?.webview.postMessage({
        type: "prefill",
        text: `Explain this selection:\n\n\`\`\`\n${text}\n\`\`\``,
      });
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
