#!/usr/bin/env python3
"""
Harness X — 简易 Web 聊天界面

用法:
    python web_chat.py                # 启动服务器 (默认 http://127.0.0.1:8080)
    python web_chat.py --port 3000    # 指定端口

需要先配置 API Key:
    export HARNESS_API_KEY=sk-...
    或在 ~/.harness_x/.env 中设置
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Agent singleton (lazy init)
# ---------------------------------------------------------------------------
_agent = None
_agent_lock = threading.Lock()
_sessions: dict[str, list] = {}


def _get_agent():
    global _agent
    if _agent is not None:
        return _agent
    from run_agent import AIAgent
    from harness_cli.config import load_config

    config = load_config()
    _agent = AIAgent(
        base_url=config.get("base_url", ""),
        model=config.get("model", "gpt-4o"),
        api_key=config.get("api_key", ""),
        quiet_mode=True,
    )
    return _agent


# ---------------------------------------------------------------------------
# HTML page (embedded)
# ---------------------------------------------------------------------------
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness X Chat</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
  header { background: #16213e; padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #0f3460; }
  header h1 { font-size: 16px; font-weight: 600; color: #e94560; }
  header span { font-size: 12px; color: #888; }
  #new-chat { background: #0f3460; color: #e0e0e0; border: 1px solid #1a3a6e; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  #new-chat:hover { background: #1a3a6e; }
  #messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 80%; padding: 10px 14px; border-radius: 12px; line-height: 1.5; font-size: 14px; white-space: pre-wrap; word-break: break-word; }
  .msg.user { align-self: flex-end; background: #0f3460; color: #e0e0e0; }
  .msg.agent { align-self: flex-start; background: #16213e; color: #d0d0d0; border: 1px solid #1a3a6e; }
  .msg.error { align-self: center; background: #4a1020; color: #ff6b6b; font-size: 13px; }
  .msg.system { align-self: center; color: #888; font-size: 12px; padding: 4px 0; background: none; }
  #input-area { padding: 12px 20px; background: #16213e; border-top: 1px solid #0f3460; display: flex; gap: 10px; }
  #input { flex: 1; background: #1a1a2e; border: 1px solid #0f3460; color: #e0e0e0; padding: 10px 14px; border-radius: 8px; font-size: 14px; resize: none; outline: none; }
  #input:focus { border-color: #e94560; }
  #send { background: #e94560; color: #fff; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; }
  #send:hover { background: #c73650; }
  #send:disabled { background: #555; cursor: not-allowed; }
</style>
</head>
<body>
<header>
  <h1>⚡ Harness X</h1>
  <span id="model-info"></span>
  <button id="new-chat">新对话</button>
</header>
<div id="messages"></div>
<div id="input-area">
  <textarea id="input" rows="1" placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"></textarea>
  <button id="send">发送</button>
</div>
<script>
let sessionId = null;
const msgs = document.getElementById('messages');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');

function addMsg(text, cls) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.textContent = text;
  msgs.appendChild(d);
  msgs.scrollTop = msgs.scrollHeight;
  return d;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMsg(text, 'user');
  sendBtn.disabled = true;
  const loading = addMsg('思考中...', 'system');

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId })
    });
    const data = await res.json();
    loading.remove();
    if (data.error) {
      addMsg(data.error, 'error');
    } else {
      sessionId = data.session_id;
      addMsg(data.response, 'agent');
    }
  } catch (e) {
    loading.remove();
    addMsg('请求失败: ' + e.message, 'error');
  }
  sendBtn.disabled = false;
  input.focus();
}

document.getElementById('new-chat').onclick = async () => {
  if (sessionId) {
    await fetch('/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
  }
  sessionId = null;
  msgs.innerHTML = '';
  addMsg('新对话已开始', 'system');
};

sendBtn.onclick = send;
input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
input.focus();

// Load model info
fetch('/info').then(r => r.json()).then(d => {
  document.getElementById('model-info').textContent = d.model ? 'Model: ' + d.model : '';
}).catch(() => {});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class ChatHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/info":
            try:
                agent = _get_agent()
                self._send_json({"model": getattr(agent, "model", "unknown")})
            except Exception:
                self._send_json({"model": "unknown"})
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            data = json.loads(raw) if raw else {}
        except Exception:
            self._send_json({"error": "Invalid JSON body"}, 400)
            return

        if self.path == "/chat":
            self._handle_chat(data)
        elif self.path == "/reset":
            self._handle_reset(data)
        else:
            self.send_error(404)

    def _handle_chat(self, data: dict):
        message = data.get("message", "").strip()
        if not message:
            self._send_json({"error": "Empty message"}, 400)
            return

        session_id = data.get("session_id")
        history = _sessions.get(session_id, []) if session_id else []

        with _agent_lock:
            try:
                agent = _get_agent()
                result = agent.run_conversation(
                    message,
                    conversation_history=history if history else None,
                )
            except Exception as exc:
                print(f"[ERROR] Agent failed: {exc}", file=sys.stderr)
                self._send_json({"error": str(exc)}, 500)
                return

        response_text = result.get("final_response", str(result))
        new_history = result.get("messages", [])

        if not session_id:
            session_id = str(uuid.uuid4())[:8]

        _sessions[session_id] = new_history
        self._send_json({"response": response_text, "session_id": session_id})

    def _handle_reset(self, data: dict):
        session_id = data.get("session_id")
        if session_id and session_id in _sessions:
            del _sessions[session_id]
        self._send_json({"ok": True})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Harness X Web Chat")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()

    print("Initializing agent...")
    try:
        agent = _get_agent()
        print(f"  Model: {getattr(agent, 'model', 'unknown')}")
    except Exception as exc:
        print(f"  Warning: agent init deferred — {exc}", file=sys.stderr)

    server = HTTPServer((args.host, args.port), ChatHandler)
    print(f"\n  ⚡ Harness X Web Chat")
    print(f"  http://{args.host}:{args.port}\n")
    print("  Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")
        server.server_close()


if __name__ == "__main__":
    main()
