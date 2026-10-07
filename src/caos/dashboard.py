from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .orchestrator import CAOS


HTML = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>C.A.O.S · Mesa Local</title>
<style>
body{margin:0;background:#0b0e13;color:#e8edf5;font:14px system-ui,Segoe UI,sans-serif}header{padding:18px 24px;border-bottom:1px solid #252b36;display:flex;justify-content:space-between}main{padding:24px;max-width:1200px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:#141923;border:1px solid #2a3140;border-radius:12px;padding:16px}.tag{font-size:11px;color:#97a4b7;letter-spacing:.12em}.big{font-size:24px;font-weight:700;margin-top:6px}.ok{color:#79dfa2}.warn{color:#ffcc66}pre{white-space:pre-wrap;word-break:break-word;background:#0d1118;border-radius:10px;padding:16px}
</style></head>
<body><header><b>C.A.O.S · PREGÃO LOCAL</b><span>127.0.0.1 · local-first</span></header><main>
<div class="grid">
<div class="card"><div class="tag">QUANT</div><div class="big">Pesquisa</div><p>mineração · backtest · robustez</p></div>
<div class="card"><div class="tag">MACRO</div><div class="big">Regime</div><p>tendência · volatilidade</p></div>
<div class="card"><div class="tag">NOTÍCIAS</div><div class="big">Contexto</div><p>entrada controlada para o LLM local</p></div>
<div class="card"><div class="tag">RISCO</div><div class="big" id="risk">—</div><p>limites determinísticos</p></div>
<div class="card"><div class="tag">COMPLIANCE</div><div class="big" id="live">—</div><p>live exige ação humana</p></div>
</div><h2>Estado</h2><pre id="state">carregando…</pre>
<script>
async function tick(){
  let r=await fetch('/api/status');
  let s=await r.json();
  state.textContent=JSON.stringify(s,null,2);
  risk.textContent=s.kill_switch?'KILL':'OK';
  risk.className='big '+(s.kill_switch?'warn':'ok');
  live.textContent=s.live_armed?'ARMADO':'BLOQUEADO';
  live.className='big '+(s.live_armed?'warn':'ok');
}
tick();setInterval(tick,1500)
</script>
</main></body></html>'''


def serve(
    caos: CAOS,
    host: str = "127.0.0.1",
    port: int = 5190,
    open_browser: bool = True,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/status":
                body = json.dumps(caos.status()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/" or self.path.startswith("/?"):
                body = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    if open_browser:
        threading.Timer(
            0.3,
            lambda: webbrowser.open(f"http://{host}:{port}"),
        ).start()
    return server
