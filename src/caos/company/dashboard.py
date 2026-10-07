from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .control import CompanyControlPort


HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trade Company · Operations</title>
<style>
:root{
  color-scheme:dark;
  --bg:#090c11;--panel:#111722;--panel2:#151d2a;--line:#273142;
  --text:#e9eef7;--muted:#94a3b8;--green:#63d297;--amber:#f2c96d;
  --red:#ff7373;--blue:#75a7ff;
}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:14px system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:5;display:flex;justify-content:space-between;
align-items:center;padding:16px 22px;border-bottom:1px solid var(--line);
background:rgba(9,12,17,.94);backdrop-filter:blur(8px)}
.brand{font-weight:800;letter-spacing:.08em}.sub{color:var(--muted);font-size:12px}
main{max-width:1440px;margin:auto;padding:20px}
nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
nav button,.btn{border:1px solid var(--line);background:var(--panel);color:var(--text);
padding:9px 12px;border-radius:9px;cursor:pointer}
nav button.active,.btn:hover{border-color:#475569;background:var(--panel2)}
.btn.danger{border-color:#6f2d35;color:#ffb1b1}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:15px}
.tag{text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-size:10px}
.big{font-size:25px;font-weight:800;margin-top:5px}.ok{color:var(--green)}
.warn{color:var(--amber)}.bad{color:var(--red)}.blue{color:var(--blue)}
.section{display:none}.section.active{display:block}
h2{font-size:17px;margin:20px 0 10px}table{width:100%;border-collapse:collapse;
background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
tr:last-child td{border-bottom:none}.pill{display:inline-block;padding:3px 7px;
border:1px solid var(--line);border-radius:99px;font-size:11px}
.row-actions{display:flex;gap:6px;flex-wrap:wrap}
pre{white-space:pre-wrap;word-break:break-word;background:#0b1018;border:1px solid var(--line);
padding:12px;border-radius:10px;max-height:420px;overflow:auto}
.two{display:grid;grid-template-columns:1.35fr 1fr;gap:12px}
.alert{padding:10px;border:1px solid var(--line);border-radius:9px;margin-bottom:8px}
.small{font-size:12px;color:var(--muted)}input{background:#0c121b;border:1px solid var(--line);
color:var(--text);border-radius:8px;padding:8px;width:90px}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.two{grid-template-columns:1fr}}
@media(max-width:540px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div><div class="brand">TRADE COMPANY</div><div class="sub">standalone cell · C.A.O.S engine</div></div>
  <div id="health" class="pill">carregando</div>
</header>
<main>
<nav>
<button data-tab="overview" class="active">Overview</button>
<button data-tab="traders">Traders</button>
<button data-tab="treasury">Treasury</button>
<button data-tab="markets">Markets</button>
<button data-tab="supervisor">Supervisor</button>
<button data-tab="caos">C.A.O.S</button>
</nav>

<section id="overview" class="section active">
<div class="grid">
  <div class="card"><div class="tag">Company Equity</div><div id="equity" class="big">—</div></div>
  <div class="card"><div class="tag">Treasury Reserve</div><div id="reserve" class="big">—</div><div id="spawnCap" class="small"></div></div>
  <div class="card"><div class="tag">Traders</div><div id="traderCount" class="big">—</div><div id="traderLimit" class="small"></div></div>
  <div class="card"><div class="tag">Gross Exposure</div><div id="gross" class="big">—</div><div id="drawdown" class="small"></div></div>
</div>
<div class="two">
 <div><h2>Traders ativos</h2><div id="overviewTraders"></div></div>
 <div><h2>Alertas</h2><div id="overviewAlerts"></div></div>
</div>
</section>

<section id="traders" class="section">
<h2>Trader Registry</h2><div id="tradersTable"></div>
</section>

<section id="treasury" class="section">
<div class="grid">
 <div class="card"><div class="tag">Reserve</div><div id="treasuryReserve" class="big">—</div></div>
 <div class="card"><div class="tag">Realized Company Equity</div><div id="realizedEquity" class="big">—</div></div>
 <div class="card"><div class="tag">Spawn Capacity</div><div id="treasurySpawn" class="big">—</div></div>
 <div class="card"><div class="tag">Initial Bucket</div><div id="initialBucket" class="big">—</div></div>
</div>
<h2>Capital Ledger</h2><div id="ledgerTable"></div>
</section>

<section id="markets" class="section">
<h2>Opportunity Registry</h2><div id="opportunitiesTable"></div>
<h2>Exposure por mercado</h2><div id="symbolExposure"></div>
</section>

<section id="supervisor" class="section">
<div class="grid">
 <div class="card"><div class="tag">Audit</div><div id="auditStatus" class="big">—</div></div>
 <div class="card"><div class="tag">Kill Switch</div><div id="killState" class="big">—</div></div>
 <div class="card"><div class="tag">Reconciliation</div><div id="reconciliation" class="big">—</div></div>
 <div class="card"><div class="tag">Effective Limit</div><div id="effectiveLimit" class="big">—</div></div>
</div>
<h2>Alertas do Supervisor</h2><div id="alerts"></div>
<h2>Controles seguros</h2>
<div class="card">
 <label>Limite operacional efetivo <input id="limitInput" type="number" min="1"></label>
 <button class="btn" onclick="setLimit()">Aplicar</button>
 <button class="btn danger" onclick="emergencyStop()">EMERGENCY STOP</button>
 <div class="small" style="margin-top:8px">A interface não expõe reset de kill switch, credenciais ou raw orders.</div>
</div>
</section>

<section id="caos" class="section">
<h2>C.A.O.S health</h2><pre id="caosState">—</pre>
<h2>Company state</h2><pre id="rawState">—</pre>
</section>
</main>

<script>
let current=null;
const money=v=>'$'+Number(v||0).toFixed(4);
const pct=v=>Number(v||0).toFixed(2)+'%';
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function table(headers,rows){
 if(!rows.length)return '<div class="card small">Sem dados.</div>';
 return '<table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+
 '</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+
 '</tr>').join('')+'</tbody></table>';
}
function traderRows(s,compact=false){
 const traders=Object.values(s.traders?.traders||{});
 const exposure=s.exposure?.by_trader||{};
 return traders.map(t=>{
   const bal=s.treasury?.balances?.['TRADER:'+t.id]||0;
   const maxN=Number((s.paper?.accounts?.[t.id]?.paper?.cash ?? bal))*Number(t.max_trade_exposure_pct||0)/100;
   const actions=t.status==='active'
    ? '<button class="btn" onclick="pauseTrader(\''+esc(t.id)+'\')">Pause</button>'
    : (t.status==='paused'
       ? '<button class="btn" onclick="resumeTrader(\''+esc(t.id)+'\')">Resume</button>':'');
   if(compact) return [
     '<b>'+esc(t.id)+'</b>',
     '<span class="pill">'+esc(t.status)+'</span>',
     esc(t.market||'—'),
     money(bal),
     money(exposure[t.id]||0)
   ];
   return [
     '<b>'+esc(t.id)+'</b>',
     '<span class="pill">'+esc(t.status)+'</span>',
     esc(t.mode),
     esc(t.market||'—')+' '+esc(t.direction||''),
     esc(t.strategy_id||'—'),
     money(bal),
     pct(t.trade_exposure_pct ?? t.max_trade_exposure_pct),
     pct(t.max_trade_exposure_pct),
     money(exposure[t.id]||0),
     '<div class="row-actions">'+actions+'</div>'
   ];
 });
}
function render(s){
 current=s;
 const audit=s.audit||{};
 const alerts=audit.alerts||[];
 const slots=s.traders?.slot_count||0;
 const eff=s.effective_trader_limit||0;
 health.textContent=(audit.status||'unknown').toUpperCase();
 health.className='pill '+(audit.status==='healthy'?'ok':audit.status==='critical'?'bad':'warn');
 equity.textContent=money(s.marked_company_equity);
 reserve.textContent=money(s.treasury?.reserve);
 spawnCap.textContent='capacidade financeira: '+(s.treasury_spawn_capacity||0)+' novo(s) Trader(s)';
 traderCount.textContent=slots+' / '+eff;
 traderLimit.textContent='cap configurado: '+(s.policy?.operational_trader_cap||0);
 gross.textContent=money(s.exposure?.gross_notional);
 drawdown.textContent='drawdown '+pct(s.risk?.drawdown_pct);

 overviewTraders.innerHTML=table(['ID','Status','Market','Capital','Exposure'],traderRows(s,true));
 overviewAlerts.innerHTML=alerts.length?alerts.map(a=>'<div class="alert"><b>'+esc(a.kind)+'</b><div class="small">'+esc(a.severity)+'</div></div>').join(''):'<div class="card ok">Sem alertas.</div>';

 tradersTable.innerHTML=table(['Trader','Status','Mode','Market','Strategy','Capital','Size','Max','Exposure','Ações'],traderRows(s,false));

 treasuryReserve.textContent=money(s.treasury?.reserve);
 realizedEquity.textContent=money(s.treasury?.company_equity);
 treasurySpawn.textContent=String(s.treasury_spawn_capacity||0);
 initialBucket.textContent=money(s.policy?.trader_initial_bucket);
 const led=s.treasury?.ledger||[];
 ledgerTable.innerHTML=table(['Tipo','Valor','De','Para','Trader','Nota'],led.slice().reverse().map(e=>[
   esc(e.kind),money(e.amount),esc(e.from_account||'—'),esc(e.to_account||'—'),esc(e.trader_id||'—'),esc(e.note||'')
 ]));

 const opp=Object.values(s.opportunities||{});
 opportunitiesTable.innerHTML=table(['Symbol','Dir','Score','Regime','Status','Owner','Strategies'],opp.map(o=>[
   '<b>'+esc(o.symbol)+'</b>',esc(o.direction),Number(o.score||0).toFixed(1),esc(o.regime),esc(o.status),esc(o.reserved_by||'—'),esc((o.strategy_candidates||[]).join(', '))
 ]));
 const bySym=s.exposure?.by_symbol||{};
 symbolExposure.innerHTML=table(['Symbol','Notional'],Object.entries(bySym).map(([k,v])=>[esc(k),money(v)]));

 auditStatus.textContent=(audit.status||'unknown').toUpperCase();
 auditStatus.className='big '+(audit.status==='healthy'?'ok':audit.status==='critical'?'bad':'warn');
 killState.textContent=s.risk?.kill_switch?'ACTIVE':'OFF';
 killState.className='big '+(s.risk?.kill_switch?'bad':'ok');
 reconciliation.textContent=(s.reconciliation_mismatches||[]).length?'MISMATCH':'OK';
 reconciliation.className='big '+((s.reconciliation_mismatches||[]).length?'bad':'ok');
 effectiveLimit.textContent=String(eff);
 limitInput.value=eff;
 limitInput.max=s.policy?.operational_trader_cap||eff;
 alerts.innerHTML=alerts.length?alerts.map(a=>'<div class="alert"><b>'+esc(a.kind)+'</b><pre>'+esc(JSON.stringify(a,null,2))+'</pre></div>').join(''):'<div class="card ok">Supervisor healthy.</div>';
 caosState.textContent=JSON.stringify(s.caos||{},null,2);
 rawState.textContent=JSON.stringify(s,null,2);
}
async function api(path,opts){
 const r=await fetch(path,opts);
 const j=await r.json();
 if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
 return j;
}
async function tick(){try{render(await api('/api/company/status'));}catch(e){health.textContent='OFFLINE';health.className='pill bad';}}
async function pauseTrader(id){try{await api('/api/company/traders/'+encodeURIComponent(id)+'/pause',{method:'POST'});await tick();}catch(e){alert(e.message)}}
async function resumeTrader(id){try{await api('/api/company/traders/'+encodeURIComponent(id)+'/resume',{method:'POST'});await tick();}catch(e){alert(e.message)}}
async function setLimit(){try{await api('/api/company/limit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:Number(limitInput.value)})});await tick();}catch(e){alert(e.message)}}
async function emergencyStop(){
 if(!confirm('Ativar EMERGENCY STOP? Esta tela não permite resetar o kill switch.'))return;
 try{await api('/api/company/emergency-stop',{method:'POST'});await tick();}catch(e){alert(e.message)}
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));
 document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));
 b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active');
});
tick();setInterval(tick,2000);
</script>
</body></html>'''


def serve_company(
    control: CompanyControlPort,
    *,
    host: str = "127.0.0.1",
    port: int = 5191,
    open_browser: bool = True,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/company/status":
                self._json(200, control.get_company_status())
                return
            if path == "/api/company/treasury":
                self._json(200, control.get_treasury())
                return
            if path == "/api/company/traders":
                self._json(200, control.list_traders())
                return
            if path == "/api/company/opportunities":
                self._json(200, control.list_opportunities())
                return
            if path in {"/", "/index.html"}:
                body = HTML.encode()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8",
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/company/limit":
                    payload = self._read_json()
                    self._json(
                        200,
                        control.set_operational_trader_limit(
                            int(payload["limit"])
                        ),
                    )
                    return
                if path == "/api/company/emergency-stop":
                    self._json(200, control.emergency_stop())
                    return
                parts = [
                    part
                    for part in path.split("/")
                    if part
                ]
                if (
                    len(parts) == 5
                    and parts[:3] == ["api", "company", "traders"]
                ):
                    trader_id = parts[3]
                    action = parts[4]
                    if action == "pause":
                        self._json(
                            200,
                            control.pause_trader(trader_id),
                        )
                        return
                    if action == "resume":
                        self._json(
                            200,
                            control.resume_trader(trader_id),
                        )
                        return
                self.send_error(404)
            except Exception as exc:
                self._json(
                    400,
                    {
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    if open_browser:
        threading.Timer(
            0.3,
            lambda: webbrowser.open(
                f"http://{host}:{port}"
            ),
        ).start()
    return server
