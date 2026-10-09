from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .cell import TradeCompanyCell
from .city import CityPresentationMapper
from .control import CompanyControlPort


HTML = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trade Company · Arcane Trading City</title>
<style>
:root{
  color-scheme:dark;
  --ink:#f5ecd4;
  --muted:#c7b995;
  --gold:#e9bd63;
  --gold2:#ffdda0;
  --green:#6be2a1;
  --amber:#ffc866;
  --red:#ff7878;
  --blue:#79c7ff;
  --violet:#b99cff;
  --panel:rgba(18,15,29,.94);
  --panel2:rgba(30,24,43,.94);
  --line:rgba(231,197,126,.28);
  --shadow:rgba(0,0,0,.52);
}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:#07131f;color:var(--ink);
font:14px Georgia,"Times New Roman",serif}
body{overflow-x:hidden}
button,input{font:inherit}
button{color:inherit}
.app{min-height:100vh;background:
 radial-gradient(circle at 50% -10%,rgba(123,92,197,.35),transparent 32%),
 linear-gradient(#081727 0,#132d3c 44%,#15372d 100%)}
.topbar{height:72px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;
padding:0 22px;border-bottom:1px solid var(--line);background:rgba(7,12,22,.88);
backdrop-filter:blur(12px);position:relative;z-index:40;box-shadow:0 8px 28px rgba(0,0,0,.28)}
.brand{font-weight:800;letter-spacing:.11em;color:var(--gold2);font-size:16px}
.subtitle{font-size:11px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;margin-top:3px}
.realm{text-align:center;color:var(--muted);font-size:12px}
.statusbar{justify-self:end;display:flex;gap:9px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.rune{border:1px solid var(--line);background:rgba(18,15,29,.75);border-radius:999px;padding:6px 10px;
font-family:system-ui,sans-serif;font-size:11px}
.rune.ok{color:var(--green);border-color:rgba(107,226,161,.42)}
.rune.warn{color:var(--amber);border-color:rgba(255,200,102,.45)}
.rune.bad{color:var(--red);border-color:rgba(255,120,120,.5)}
.rune.mode{cursor:pointer}.rune.mode:hover{background:rgba(233,189,99,.12)}
.execution-warning{border:1px solid rgba(255,120,120,.42);background:rgba(255,90,90,.07);border-radius:10px;padding:10px;margin:8px 0;color:#ffd0d0;font:11px system-ui,sans-serif;line-height:1.45}
.execution-proposal{border:1px solid rgba(233,189,99,.24);background:rgba(8,12,18,.52);border-radius:10px;padding:10px;margin:7px 0;font:11px system-ui,sans-serif}
.execution-proposal.awaiting{border-color:rgba(255,200,102,.55);box-shadow:0 0 14px rgba(255,200,102,.08)}
.execution-proposal .proposal-title{font-weight:800;color:#f5dda7;margin-bottom:5px}
.execution-proposal .proposal-meta{color:var(--muted);line-height:1.45}
.settings-btn{border:1px solid var(--line);background:rgba(45,34,64,.82);color:var(--gold2);border-radius:999px;padding:6px 11px;cursor:pointer;font:11px system-ui,sans-serif}
.settings-btn:hover{background:#3a2d50}
.chat-btn{border:1px solid rgba(121,199,255,.4);background:rgba(22,39,58,.9);color:#cbe9ff;border-radius:999px;padding:6px 11px;cursor:pointer;font:11px system-ui,sans-serif}
.chat-btn:hover{background:#213d58}
.chat-panel{position:fixed;right:0;top:0;bottom:0;width:min(420px,96vw);z-index:70;background:linear-gradient(165deg,#0c1723,#151126);border-left:1px solid rgba(121,199,255,.28);box-shadow:-22px 0 70px rgba(0,0,0,.5);transform:translateX(104%);transition:transform .24s ease;display:flex;flex-direction:column}
.chat-panel.open{transform:translateX(0)}
.chat-head{padding:15px 16px;border-bottom:1px solid var(--line);background:rgba(10,17,27,.95);position:relative}
.chat-head b{display:block;color:#d8edff;font:800 17px system-ui,sans-serif}.chat-head small{color:var(--muted);font:10px system-ui,sans-serif}
.chat-close{position:absolute;right:12px;top:12px;border:1px solid var(--line);background:#1a2635;border-radius:7px;padding:6px 9px;cursor:pointer}
.chat-messages{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:9px}
.chat-msg{max-width:92%;padding:9px 11px;border-radius:11px;font:12px/1.45 system-ui,sans-serif;white-space:pre-wrap;word-break:break-word}
.chat-msg.user{align-self:flex-end;background:#263b52;color:#eef8ff}.chat-msg.assistant{align-self:flex-start;background:#241d34;border:1px solid rgba(233,189,99,.2);color:#f2e7cf}
.chat-empty{margin:auto;color:var(--muted);font:12px system-ui,sans-serif;text-align:center;max-width:270px}
.chat-compose{border-top:1px solid var(--line);padding:10px;background:rgba(9,15,24,.96)}
.chat-compose textarea{width:100%;min-height:76px;max-height:180px;resize:vertical;background:#0b1420;border:1px solid rgba(121,199,255,.3);border-radius:9px;color:#fff;padding:9px;font:12px system-ui,sans-serif}
.chat-actions{display:flex;justify-content:space-between;align-items:center;margin-top:7px}.chat-actions small{color:var(--muted);font:9px system-ui,sans-serif}
.op-btn{border:1px solid var(--line);border-radius:999px;padding:6px 11px;cursor:pointer;font:700 11px system-ui,sans-serif;background:#192431}
.op-btn.start{color:var(--green);border-color:rgba(107,226,161,.45)}
.op-btn.stop{color:var(--amber);border-color:rgba(255,200,102,.45)}
.op-btn.emergency{color:#ffd0d0;border-color:rgba(255,120,120,.55);background:#3a1d25}
.op-btn:disabled{opacity:.38;cursor:not-allowed}
.city-shell{position:relative;max-width:1550px;margin:auto;padding:14px 18px 28px}
.hud{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;position:relative;z-index:8;margin-bottom:10px}
.hud-item{background:linear-gradient(135deg,rgba(32,24,47,.88),rgba(17,23,36,.88));
border:1px solid var(--line);border-radius:12px;padding:9px 12px;box-shadow:0 7px 20px rgba(0,0,0,.2)}
.hud-label{text-transform:uppercase;letter-spacing:.11em;color:var(--muted);font:10px system-ui,sans-serif}
.hud-value{font:700 18px system-ui,sans-serif;color:var(--gold2);margin-top:3px}
.city-world{position:relative;height:min(780px,calc(100vh - 130px));min-height:650px;overflow:hidden;
border:1px solid rgba(233,189,99,.22);border-radius:24px;box-shadow:0 24px 70px rgba(0,0,0,.38);
background:
 radial-gradient(ellipse at 50% 68%,rgba(114,187,111,.25) 0 35%,transparent 36%),
 linear-gradient(to bottom,#102943 0 26%,#315268 27% 37%,#304d35 38% 100%)}
.sky-stars{position:absolute;inset:0 0 60% 0;opacity:.75;background-image:
 radial-gradient(circle,#fff 0 1px,transparent 1.4px),
 radial-gradient(circle,#b9d9ff 0 1px,transparent 1.4px);
background-size:97px 83px,137px 119px;background-position:23px 17px,70px 39px}
.moon{position:absolute;right:10%;top:7%;width:72px;height:72px;border-radius:50%;
background:radial-gradient(circle at 35% 35%,#fff8cf,#d6d0ff 58%,#8c83c1);
box-shadow:0 0 35px rgba(215,213,255,.65)}
.mountain{position:absolute;bottom:54%;width:0;height:0;border-left:170px solid transparent;
border-right:170px solid transparent;border-bottom:200px solid #1a3344;filter:drop-shadow(0 12px 13px rgba(0,0,0,.18))}
.m1{left:-70px}.m2{left:18%;transform:scale(.76)}.m3{right:7%;transform:scale(.88)}.m4{right:-130px;transform:scale(.62)}
.wall{position:absolute;left:4%;right:4%;bottom:6%;height:47%;border:2px solid rgba(227,198,140,.24);
border-radius:50% 50% 12% 12%/20% 20% 8% 8%;background:rgba(56,72,57,.14);pointer-events:none}
.road{position:absolute;left:49%;top:34%;bottom:-8%;width:17%;transform:skewX(-10deg);
background:linear-gradient(90deg,transparent,rgba(224,195,140,.16) 18% 82%,transparent);filter:blur(.3px)}
.river{position:absolute;right:1%;top:44%;width:25%;height:58%;border-radius:50% 0 0 0;
background:linear-gradient(100deg,transparent 0 18%,rgba(75,173,199,.32) 19% 54%,rgba(121,214,235,.22) 55% 70%,transparent 71%);
transform:rotate(-8deg)}
.ley{position:absolute;height:2px;transform-origin:left center;
background:linear-gradient(90deg,transparent,rgba(145,119,255,.7),transparent);
box-shadow:0 0 12px rgba(155,130,255,.6);opacity:.38;pointer-events:none}
.ley1{left:28%;top:44%;width:34%;transform:rotate(17deg)}
.ley2{left:37%;top:67%;width:35%;transform:rotate(-13deg)}
.ley3{left:50%;top:38%;width:25%;transform:rotate(89deg)}
.place{position:absolute;width:145px;min-height:105px;border:0;background:transparent;cursor:pointer;
transform:translate(-50%,-50%);z-index:10;filter:drop-shadow(0 10px 10px rgba(0,0,0,.28));
transition:transform .2s ease,filter .2s ease}
.place:hover,.place:focus-visible{transform:translate(-50%,-54%) scale(1.055);filter:drop-shadow(0 15px 16px rgba(0,0,0,.38));outline:none}
.building{position:relative;margin:auto;width:92px;height:65px;border:2px solid rgba(253,224,164,.42);
border-radius:9px 9px 15px 15px;background:linear-gradient(145deg,#665842,#2f3a37 72%);
box-shadow:inset 0 0 18px rgba(255,211,129,.12),0 0 0 3px rgba(20,20,25,.18)}
.building:before{content:"";position:absolute;left:8px;right:8px;top:-26px;height:34px;
clip-path:polygon(50% 0,100% 100%,0 100%);background:linear-gradient(#4d3b5f,#27263d);
border-bottom:2px solid rgba(248,220,166,.45)}
.building:after{content:"";position:absolute;width:20px;height:28px;left:35px;bottom:0;border-radius:10px 10px 2px 2px;
background:#1f2025;box-shadow:inset 0 0 12px rgba(255,198,99,.4)}
.place-icon{position:absolute;z-index:2;left:50%;top:8px;transform:translateX(-50%);font-size:30px;
filter:drop-shadow(0 2px 2px #000);animation:bob 3.2s ease-in-out infinite}
.place-label{margin-top:6px;background:rgba(11,12,18,.82);border:1px solid rgba(236,205,142,.28);border-radius:8px;
padding:5px 7px;line-height:1.15;box-shadow:0 5px 13px rgba(0,0,0,.25)}
.place-title{font-weight:700;color:#ffe4a7;font-size:12px}
.place-character{color:#d2c6a9;font-size:10px;font-family:system-ui,sans-serif;margin-top:2px}
.place-activity{color:#9eced0;font-size:9px;font-family:system-ui,sans-serif;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.place.quiet .place-icon{opacity:.62;filter:grayscale(.18) drop-shadow(0 2px 2px #000)}
.place.active .place-icon{animation:bob 1.8s ease-in-out infinite}
.state-dot{position:absolute;right:15px;top:-20px;width:12px;height:12px;border-radius:50%;background:var(--green);
box-shadow:0 0 0 4px rgba(107,226,161,.12),0 0 12px var(--green);z-index:5}
.place.attention .state-dot{background:var(--amber);box-shadow:0 0 0 5px rgba(255,200,102,.13),0 0 16px var(--amber);animation:pulse 1.4s infinite}
.place.critical .state-dot,.place.emergency .state-dot{background:var(--red);box-shadow:0 0 0 5px rgba(255,120,120,.14),0 0 18px var(--red);animation:pulse .9s infinite}
.place.quiet .state-dot{background:#8997a8;box-shadow:none}
.place.active .state-dot{background:var(--blue);box-shadow:0 0 12px var(--blue)}
.citadel{left:50%;top:17%}.citadel .building{width:118px;height:78px;background:linear-gradient(145deg,#78674d,#3a4050)}
.risk{left:22%;top:28%}.risk .building{height:78px;width:72px;background:linear-gradient(#43385e,#293448)}
.observatory{left:78%;top:27%}.observatory .building{border-radius:45% 45% 14px 14px;background:linear-gradient(#3c5f66,#28394d)}
.treasury{left:15%;top:55%}.treasury .building{background:linear-gradient(#6b5937,#3a352d)}
.guild{left:47%;top:52%}.guild .building{width:126px;height:82px;background:linear-gradient(#704c3b,#3d3434)}
.tavern{left:82%;top:55%}.tavern .building{background:linear-gradient(#784735,#42312d)}
.quests{left:58%;top:65%}.quests .building{width:68px;height:50px;background:linear-gradient(#65482f,#312c26)}
.scout{left:10%;top:80%}.scout .building{background:linear-gradient(#46613d,#293a2e)}
.arena{left:32%;top:82%}.arena .building{width:118px;height:58px;border-radius:50% 50% 12px 12px;background:linear-gradient(#705844,#42362e)}
.nexus{left:52%;top:82%}.nexus .building{width:78px;height:70px;border-color:rgba(182,153,255,.7);
background:radial-gradient(circle,#785be1,#312d59 64%,#242438);box-shadow:0 0 26px rgba(151,116,255,.48)}
.workshop{left:70%;top:82%}.workshop .building{background:linear-gradient(#59416e,#303247)}
.chronicle{left:90%;top:82%}.chronicle .building{background:linear-gradient(#4f536f,#303344)}
.city-notice{position:absolute;left:50%;top:35%;transform:translateX(-50%);z-index:6;width:min(420px,44%);
text-align:center;color:#ead9af;text-shadow:0 2px 8px #000;pointer-events:none}
.city-notice b{display:block;font-size:16px;color:#fff0bc}.city-notice span{font-size:11px;font-family:system-ui,sans-serif}
.alert-beacon{position:absolute;left:18px;bottom:18px;z-index:20;background:rgba(24,17,31,.9);
border:1px solid var(--line);border-radius:12px;padding:9px 11px;max-width:340px;box-shadow:0 8px 28px rgba(0,0,0,.35);
font-family:system-ui,sans-serif;font-size:11px}
.alert-beacon strong{color:var(--amber)}
.emergency-ward{display:none;position:absolute;inset:0;z-index:15;pointer-events:none;border:5px solid rgba(255,94,105,.62);
box-shadow:inset 0 0 90px rgba(255,59,76,.23),0 0 55px rgba(255,59,76,.25);border-radius:24px}
.city-world.emergency .emergency-ward{display:block;animation:wardPulse 1.4s infinite}
.drawer-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.38);z-index:49}
.drawer{position:fixed;right:0;top:0;bottom:0;width:min(520px,94vw);background:linear-gradient(160deg,#171224,#0c1520);
border-left:1px solid var(--line);z-index:50;transform:translateX(103%);transition:transform .25s ease;
box-shadow:-24px 0 70px rgba(0,0,0,.45);overflow:auto}
.drawer.open{transform:translateX(0)}.drawer-backdrop.open{display:block}
.drawer-head{position:sticky;top:0;padding:18px 18px 13px;background:rgba(15,13,24,.96);backdrop-filter:blur(10px);
border-bottom:1px solid var(--line);z-index:2}
.drawer-title{font-size:22px;color:var(--gold2);font-weight:800}.drawer-tech{font:11px system-ui,sans-serif;color:var(--muted);margin-top:2px}
.drawer-close{position:absolute;right:14px;top:14px;border:1px solid var(--line);background:#231b32;border-radius:8px;padding:7px 10px;cursor:pointer}
.drawer-body{padding:16px}.story{color:#eadfca;line-height:1.5;margin-bottom:14px}
.detail-section{background:rgba(255,255,255,.035);border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0}
.detail-section h3{margin:0 0 9px;color:#f1d796;font-size:13px}
.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.metric{background:rgba(8,13,22,.52);border-radius:8px;padding:8px}
.metric small{display:block;color:var(--muted);font:10px system-ui,sans-serif;text-transform:uppercase;letter-spacing:.07em}
.metric b{display:block;margin-top:3px;font:700 14px system-ui,sans-serif;color:#f5ead1}
.list{display:grid;gap:7px}.list-item{border:1px solid rgba(233,189,99,.16);background:rgba(8,12,18,.4);border-radius:9px;padding:9px}
.list-title{font-weight:700;color:#f4dda4}.list-sub{font:11px system-ui,sans-serif;color:var(--muted);margin-top:3px;line-height:1.35}
.btn{border:1px solid var(--line);background:#2c2340;color:#f7e7c3;border-radius:8px;padding:8px 10px;cursor:pointer;margin:3px}
.btn:hover{background:#3a2d50}.btn.danger{border-color:rgba(255,120,120,.45);background:#40202a;color:#ffd1d1}
.control-row{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.control-row input{width:86px;background:#0e1520;
border:1px solid var(--line);border-radius:7px;padding:7px;color:#fff}
.settings-grid{display:grid;grid-template-columns:145px 1fr;gap:8px 10px;align-items:center}
.settings-grid label{color:var(--muted);font:11px system-ui,sans-serif}
.settings-grid input,.settings-grid select{width:100%;background:#0e1520;border:1px solid var(--line);border-radius:7px;padding:8px;color:#fff}
.settings-note{font:11px system-ui,sans-serif;color:var(--muted);line-height:1.4;margin:6px 0}
.settings-status{font:11px system-ui,sans-serif;color:var(--blue);margin-top:7px}
.broker-card{border:1px solid var(--line);background:rgba(8,12,18,.45);border-radius:10px;padding:10px;margin:8px 0}
.broker-card.active{border-color:rgba(107,226,161,.55);box-shadow:0 0 14px rgba(107,226,161,.08)}
.guild-adventurers{position:absolute;left:35%;top:61%;width:25%;display:flex;gap:6px;justify-content:center;flex-wrap:wrap;z-index:14;pointer-events:none}
.mini-trader{pointer-events:auto;border:1px solid rgba(239,207,143,.4);background:rgba(15,13,24,.88);border-radius:999px;
padding:5px 8px;display:flex;align-items:center;gap:5px;cursor:pointer;box-shadow:0 5px 14px rgba(0,0,0,.3);
font:10px system-ui,sans-serif;color:#ffe7ad;transition:transform .18s ease}
.mini-trader:hover{transform:translateY(-3px) scale(1.04)}
.mini-trader.active{border-color:rgba(121,199,255,.6);box-shadow:0 0 12px rgba(121,199,255,.22)}
.mini-trader.waiting_assignment{border-color:rgba(255,200,102,.55)}
.mini-trader.paused,.mini-trader.halted{opacity:.66}
.trader-strip{display:flex;gap:8px;overflow-x:auto;padding:6px 0 2px}.trader-chip{min-width:130px;border:1px solid var(--line);
background:rgba(28,24,40,.75);border-radius:10px;padding:9px;cursor:pointer}.trader-chip:hover{border-color:#d9b66f}
.trader-avatar{font-size:24px}.trader-id{font-weight:800;color:#ffe5a6}.trader-meta{font:10px system-ui,sans-serif;color:var(--muted);margin-top:3px}
.empty{color:var(--muted);font-style:italic;padding:6px 0}
.tech-json{white-space:pre-wrap;word-break:break-word;background:#09101a;border:1px solid rgba(255,255,255,.08);
border-radius:9px;padding:9px;max-height:260px;overflow:auto;font:11px ui-monospace,Consolas,monospace;color:#c9d5e5}
.trader-chart-shell{border:1px solid rgba(233,189,99,.22);border-radius:12px;overflow:hidden;background:#090f18}
.trader-chart-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 11px;border-bottom:1px solid rgba(255,255,255,.07);font:11px system-ui,sans-serif}
.trader-chart-title{font-weight:800;color:#ffe2a0}.trader-chart-meta{color:var(--muted);text-align:right}
.trader-phase{display:inline-flex;align-items:center;border-radius:999px;padding:4px 8px;border:1px solid rgba(255,255,255,.16);font-weight:800;letter-spacing:.05em}
.trader-phase.waiting_entry,.trader-phase.waiting_assignment{color:var(--amber);border-color:rgba(255,200,102,.45)}
.trader-phase.pending_entry,.trader-phase.pending_exit{color:#ffae42;border-color:rgba(255,174,66,.65);box-shadow:0 0 10px rgba(255,174,66,.12)}
.trader-phase.in_position{color:var(--green);border-color:rgba(107,226,161,.45)}
.trader-phase.paused,.trader-phase.halted,.trader-phase.retired{color:#b8c0ca}
.trader-chart{display:block;width:100%;height:auto;min-height:260px;background:linear-gradient(180deg,#0a111b,#080d14)}
.chart-grid{stroke:rgba(180,195,215,.12);stroke-width:1}
.chart-axis{fill:#9aa7b6;font:10px system-ui,sans-serif}
.chart-wick.up,.chart-body.up{stroke:#36d399;fill:#36d399}.chart-wick.down,.chart-body.down{stroke:#ff5c72;fill:#ff5c72}
.chart-ma7{fill:none;stroke:#e4a84d;stroke-width:1.6}.chart-ma25{fill:none;stroke:#a86ee6;stroke-width:1.6}.chart-ma99{fill:none;stroke:#61c8d4;stroke-width:1.6}
.chart-average{stroke:#79c7ff;stroke-width:1.4;stroke-dasharray:8 5}.chart-current{stroke:#f2d17c;stroke-width:1;stroke-dasharray:3 5;opacity:.65}
.chart-pending{stroke:#ff9f2f;stroke-width:2;stroke-dasharray:10 6;filter:drop-shadow(0 0 3px rgba(255,159,47,.45))}
.chart-pending-label{fill:#ffb45c;font:800 10px system-ui,sans-serif;text-anchor:end}
.chart-buy{fill:#19c979;stroke:#d9ffec;stroke-width:1.5}.chart-sell{fill:#f05168;stroke:#ffe1e5;stroke-width:1.5}
.chart-marker-text{fill:#fff;font:800 10px system-ui,sans-serif;text-anchor:middle;dominant-baseline:middle}
.chart-avg-label{fill:#9fd5ff;font:10px system-ui,sans-serif}
.pending-order-card{margin:9px 10px;padding:9px 10px;border:1px solid rgba(255,159,47,.46);border-radius:9px;background:rgba(255,159,47,.07);font:11px system-ui,sans-serif;color:#d8c7a8}
.pending-order-card strong{display:block;color:#ffb45c;margin-bottom:4px;letter-spacing:.04em}.pending-order-card code{color:#f5dfb4}
.order-history{display:grid;gap:5px;padding:0 10px 10px}.order-history-row{border-left:2px solid rgba(255,159,47,.45);padding:4px 7px;background:rgba(255,255,255,.025);font:10px system-ui,sans-serif;color:var(--muted)}
.order-history-row b{color:#e8d6af}
.chart-legend{display:flex;gap:12px;flex-wrap:wrap;padding:7px 10px;border-top:1px solid rgba(255,255,255,.06);font:10px system-ui,sans-serif;color:var(--muted)}
.chart-legend b{color:#f6e5b8}.chart-events{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:6px;padding:0 10px 10px}
.chart-event{background:rgba(255,255,255,.035);border-radius:7px;padding:6px 8px;font:10px system-ui,sans-serif;color:var(--muted)}
.chart-event strong{display:block;color:#f4dda4;margin-bottom:2px}
@keyframes bob{0%,100%{transform:translate(-50%,0)}50%{transform:translate(-50%,-5px)}}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.6;transform:scale(1.35)}}
@keyframes wardPulse{0%,100%{opacity:.65}50%{opacity:1}}
@media(max-width:900px){
 .topbar{grid-template-columns:1fr auto;height:auto;min-height:70px;padding:10px 14px}.realm{display:none}
 .hud{grid-template-columns:repeat(2,1fr)}.city-world{min-height:720px}
 .place{transform:translate(-50%,-50%) scale(.88)}.place:hover{transform:translate(-50%,-53%) scale(.93)}
}
@media(max-width:620px){
 .statusbar{display:none}.city-shell{padding:8px}.hud{grid-template-columns:1fr 1fr}
 .city-world{height:760px;min-height:760px}.place{width:115px}
 .place-label{padding:4px}.place-character{display:none}.citadel{top:14%}.risk{left:19%;top:29%}
 .observatory{left:81%;top:29%}.treasury{left:15%;top:52%}.guild{left:48%;top:49%}.tavern{left:83%;top:52%}
 .quests{left:58%;top:62%}.scout{left:10%;top:77%}.arena{left:30%;top:81%}.nexus{left:51%;top:81%}
 .workshop{left:72%;top:81%}.chronicle{left:91%;top:78%}.city-notice{width:62%;top:34%}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<div class="app">
<header class="topbar">
  <div><div class="brand">TRADE COMPANY</div><div class="subtitle">Arcane Trading City · Standalone Company Cell</div></div>
  <div class="realm">High-Magic Operations View</div>
  <div class="statusbar">
    <span id="healthRune" class="rune">CITY —</span>
    <span id="modeRune" class="rune mode" title="Click to choose PAPER / TESTNET / REAL">PAPER</span>
    <span id="operationRune" class="rune warn">STOPPED</span>
    <span id="alertRune" class="rune">0 alerts</span>
    <button id="startOpsBtn" class="op-btn start" type="button">▶ Start</button>
    <button id="stopOpsBtn" class="op-btn stop" type="button">■ Stop</button>
    <button id="emergencyOpsBtn" class="op-btn emergency" type="button">⚠ Emergency</button>
    <button id="chatBtn" class="chat-btn" type="button">💬 Chat</button>
    <button id="settingsBtn" class="settings-btn" type="button">⚙ Settings</button>
  </div>
</header>
<main class="city-shell">
  <div class="hud">
    <div class="hud-item"><div class="hud-label">Company Equity</div><div id="hudEquity" class="hud-value">—</div></div>
    <div class="hud-item"><div class="hud-label">Royal Treasury</div><div id="hudReserve" class="hud-value">—</div></div>
    <div class="hud-item"><div class="hud-label">Adventurers</div><div id="hudTraders" class="hud-value">—</div></div>
    <div class="hud-item"><div class="hud-label">City Wards</div><div id="hudRisk" class="hud-value">—</div></div>
  </div>

  <section id="cityWorld" class="city-world">
    <div class="sky-stars"></div><div class="moon"></div>
    <div class="mountain m1"></div><div class="mountain m2"></div><div class="mountain m3"></div><div class="mountain m4"></div>
    <div class="wall"></div><div class="road"></div><div class="river"></div>
    <div class="ley ley1"></div><div class="ley ley2"></div><div class="ley ley3"></div>
    <div class="emergency-ward"></div>
    <div class="city-notice"><b id="cityMoodTitle">A cidade desperta...</b><span id="cityMoodText">Carregando o estado da Company.</span></div>

    <button class="place citadel" data-location="citadel"><span class="state-dot"></span><div class="building"><span class="place-icon">🏰</span></div><div class="place-label"><div class="place-title">Citadel of Oversight</div><div class="place-character">Royal Steward · Supervisor</div><div class="place-activity" data-activity="citadel">auditing the city</div></div></button>
    <button class="place risk" data-location="risk"><span class="state-dot"></span><div class="building"><span class="place-icon">🧙</span></div><div class="place-label"><div class="place-title">Tower of Wards</div><div class="place-character">Archmage · Risk</div><div class="place-activity" data-activity="risk">reading the wards</div></div></button>
    <button class="place observatory" data-location="observatory"><span class="state-dot"></span><div class="building"><span class="place-icon">🔭</span></div><div class="place-label"><div class="place-title">Arcane Observatory</div><div class="place-character">Market Seer · Quant</div><div class="place-activity" data-activity="observatory">studying the sky</div></div></button>
    <button class="place treasury" data-location="treasury"><span class="state-dot"></span><div class="building"><span class="place-icon">🪙</span></div><div class="place-label"><div class="place-title">Grand Vault</div><div class="place-character">Royal Treasurer</div><div class="place-activity" data-activity="treasury">counting the vault</div></div></button>
    <button class="place guild" data-location="guild"><span class="state-dot"></span><div class="building"><span class="place-icon">⚔️</span></div><div class="place-label"><div class="place-title">Grand Trading Guild</div><div class="place-character">Traders · Questmaster</div><div class="place-activity" data-activity="guild">organizing adventurers</div></div></button>
    <button class="place tavern" data-location="tavern"><span class="state-dot"></span><div class="building"><span class="place-icon">🎻</span></div><div class="place-label"><div class="place-title">Whispering Tankard</div><div class="place-character">Bard · News</div><div class="place-activity" data-activity="tavern">listening for news</div></div></button>
    <button class="place quests" data-location="quests"><span class="state-dot"></span><div class="building"><span class="place-icon">📜</span></div><div class="place-label"><div class="place-title">Quest Board</div><div class="place-character">Opportunities</div><div class="place-activity" data-activity="quests">posting quests</div></div></button>
    <button class="place scout" data-location="scout"><span class="state-dot"></span><div class="building"><span class="place-icon">🧭</span></div><div class="place-label"><div class="place-title">Scout Lodge</div><div class="place-character">Royal Pathfinder</div><div class="place-activity" data-activity="scout">scouting markets</div></div></button>
    <button class="place arena" data-location="arena"><span class="state-dot"></span><div class="building"><span class="place-icon">🏟️</span></div><div class="place-label"><div class="place-title">Tournament Arena</div><div class="place-character">Training Arena</div><div class="place-activity" data-activity="arena">training challengers</div></div></button>
    <button class="place nexus" data-location="nexus"><span class="state-dot"></span><div class="building"><span class="place-icon">🔮</span></div><div class="place-label"><div class="place-title">Arcane Nexus</div><div class="place-character">C.A.O.S</div><div class="place-activity" data-activity="nexus">feeding the ley lines</div></div></button>
    <button class="place workshop" data-location="workshop"><span class="state-dot"></span><div class="building"><span class="place-icon">⚗️</span></div><div class="place-label"><div class="place-title">Arcane Workshop</div><div class="place-character">Royal Arcanist · Research Factory</div><div class="place-activity" data-activity="workshop">researching challengers</div></div></button>
    <button class="place chronicle" data-location="chronicle"><span class="state-dot"></span><div class="building"><span class="place-icon">📚</span></div><div class="place-label"><div class="place-title">Chronicle Vault</div><div class="place-character">Memory & Recovery</div><div class="place-activity" data-activity="chronicle">recording history</div></div></button>

    <div id="guildAdventurers" class="guild-adventurers" aria-label="Visible Trader adventurers"></div>
    <div id="alertBeacon" class="alert-beacon"><strong>City Watch</strong><div id="alertText">No alerts.</div></div>
  </section>
</main>
</div>

<div id="drawerBackdrop" class="drawer-backdrop"></div>
<aside id="drawer" class="drawer" aria-hidden="true">
  <div class="drawer-head">
    <button id="drawerClose" class="drawer-close">✕</button>
    <div id="drawerTitle" class="drawer-title">—</div>
    <div id="drawerTech" class="drawer-tech">—</div>
  </div>
  <div id="drawerBody" class="drawer-body"></div>
</aside>

<aside id="chatPanel" class="chat-panel" aria-hidden="true">
  <div class="chat-head">
    <button id="chatClose" class="chat-close">✕</button>
    <b>🔮 Arcane Nexus Chat</b>
    <small>Read-only natural language · uses the configured LLM</small>
  </div>
  <div id="chatMessages" class="chat-messages"><div class="chat-empty">Ask about the Company, Traders, risk, strategies, news context or what the agents are doing.</div></div>
  <div class="chat-compose">
    <textarea id="chatInput" placeholder="Fale com o LLM em linguagem natural…"></textarea>
    <div class="chat-actions"><small>Enter sends · Shift+Enter creates a new line</small><div><button id="chatClear" class="btn">Clear</button><button id="chatSend" class="btn">Send</button></div></div>
  </div>
</aside>

<script>
let currentStatus=null;
let currentCity=null;
let activeLocation=null;
let activeTraderId=null;
let settingsCache=null;
let currentExecution=null;
let editingBrokerId=null;
let selectedLocalModelPath='';
const byId=function(id){return document.getElementById(id)};
const hudEquity=byId('hudEquity'),hudReserve=byId('hudReserve'),hudTraders=byId('hudTraders'),hudRisk=byId('hudRisk');
const healthRune=byId('healthRune'),modeRune=byId('modeRune'),operationRune=byId('operationRune'),alertRune=byId('alertRune'),cityWorld=byId('cityWorld');
const cityMoodTitle=byId('cityMoodTitle'),cityMoodText=byId('cityMoodText'),alertText=byId('alertText'),guildAdventurers=byId('guildAdventurers');
const drawer=byId('drawer'),drawerBackdrop=byId('drawerBackdrop'),drawerTitle=byId('drawerTitle'),drawerTech=byId('drawerTech'),drawerBody=byId('drawerBody'),drawerClose=byId('drawerClose'),settingsBtn=byId('settingsBtn');
const chatBtn=byId('chatBtn'),chatPanel=byId('chatPanel'),chatClose=byId('chatClose'),chatMessages=byId('chatMessages'),chatInput=byId('chatInput'),chatSend=byId('chatSend'),chatClear=byId('chatClear');
const startOpsBtn=byId('startOpsBtn'),stopOpsBtn=byId('stopOpsBtn'),emergencyOpsBtn=byId('emergencyOpsBtn');

const money=function(v){return '$'+Number(v||0).toFixed(4)};
const pct=function(v){return Number(v||0).toFixed(2)+'%'};
const esc=function(s){return String(s===undefined||s===null?'':s).replace(/[&<>"']/g,function(m){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]})};
const json=function(v){return '<pre class="tech-json">'+esc(JSON.stringify(v,null,2))+'</pre>'};
const metric=function(label,value){return '<div class="metric"><small>'+esc(label)+'</small><b>'+esc(value)+'</b></div>'};
const section=function(title,body){return '<div class="detail-section"><h3>'+esc(title)+'</h3>'+body+'</div>'};
const listItem=function(title,sub,onClick){return '<div class="list-item"'+(onClick?' onclick="'+onClick+'" style="cursor:pointer"':'')+'><div class="list-title">'+esc(title)+'</div><div class="list-sub">'+esc(sub)+'</div></div>'};

async function api(path,opts){
 const r=await fetch(path,opts);
 let j={};
 try{j=await r.json()}catch(e){}
 if(!r.ok)throw new Error(j.error||('HTTP '+r.status));
 return j;
}


function settingsField(label,id,value,type){
 return '<label for="'+esc(id)+'">'+esc(label)+'</label><input id="'+esc(id)+'" type="'+esc(type||'text')+'" value="'+esc(value||'')+'">';
}
function settingsSelect(label,id,value,options){
 return '<label for="'+esc(id)+'">'+esc(label)+'</label><select id="'+esc(id)+'">'+options.map(function(o){const v=(typeof o==='string'?o:o.value),t=(typeof o==='string'?o:o.label);return '<option value="'+esc(v)+'"'+(String(v)===String(value)?' selected':'')+'>'+esc(t)+'</option>'}).join('')+'</select>';
}
function renderSettings(){
 const st=settingsCache||{},companyCfg=st.company||{},llm=st.llm||{},managed=st.ollama_runtime||{},brokers=st.brokers||{},profiles=brokers.profiles||[],supported=brokers.supported||{},news=st.news||{},newsSources=news.sources||[];
 const providerOpts=['static','ollama','openai-compatible'];
 let html='<div class="story">Settings remain available after the Founding Charter. Saving the LLM swaps only the runtime provider; Treasury, Traders, PAPER state and research remain intact.</div>';
 html+=section('🏰 Company Charter · Runtime Policy',
   '<div class="settings-grid">'+
   settingsField('Initial Trader bucket','companyInitialBucket',companyCfg.trader_initial_bucket||10,'number')+
   settingsField('Trader stop floor','companyStopFloor',companyCfg.trader_stop_floor||3,'number')+
   settingsField('Default max exposure %','companyDefaultExposure',companyCfg.default_trader_max_exposure_pct||20,'number')+
   settingsField('Company max drawdown %','companyMaxDrawdown',companyCfg.company_max_drawdown_pct||30,'number')+
   '</div>'+
   '<div class="settings-note">'+esc(companyCfg.note||'')+' Changes require the Company to be STOPPED. Existing Trader balances are not resized when the initial bucket changes; existing Trader exposure limits remain individually configurable in each Trader drawer.</div>'+
   '<div class="control-row"><button class="btn" onclick="saveCompanyPolicySettings()">Save Company Policy</button></div>'+
   '<div id="companyPolicyStatus" class="settings-status">Operational state: '+esc(companyCfg.operational_state||'unknown')+'</div>'
 );
 html+=section('🔮 Arcane Nexus · LLM Configuration',
   '<div class="settings-grid">'+
   settingsSelect('Provider','settingsProvider',llm.provider||'static',providerOpts)+
   '<label for="settingsModel">Model</label><div><input id="settingsModel" list="settingsModelList" value="'+esc(llm.model||'')+'"><datalist id="settingsModelList"></datalist></div>'+
   settingsField('Base URL','settingsBaseUrl',llm.base_url||'')+
   settingsField('API key (optional)','settingsLlmKey','','password')+
   '</div>'+
   '<div class="settings-note">Stored LLM API keys use Windows Credential Manager. Leaving the API-key field blank keeps the existing key. Ollama usually does not need one.</div>'+
   '<div class="control-row"><button class="btn" onclick="discoverModels()">Refresh Models</button><button class="btn" onclick="testLLMSettings()">Test Connection</button><button class="btn" onclick="saveLLMSettings()">Save LLM</button></div>'+
   '<div id="settingsLlmStatus" class="settings-status">'+(llm.api_key_configured?'API key configured in credential vault.':'No LLM API key stored.')+'</div>'
 );
 html+=section('🜂 Arcane Nexus · Managed Ollama',
   '<div class="settings-note">This is the Ollama runtime carried by Trade Company itself. It uses its own localhost port and model store, so it does not depend on a separate Ollama installation. Choose a local GGUF file, apply it once, then start or stop Ollama here whenever needed.</div>'+
   '<div class="settings-grid">'+
   '<label>Runtime</label><div><b>'+(managed.running?'RUNNING':(managed.installed?'STOPPED':'NOT INSTALLED'))+'</b>'+(managed.version?' · v'+esc(managed.version):'')+'</div>'+
   '<label>Internal endpoint</label><div>'+esc(managed.base_url||'http://127.0.0.1:11435')+'</div>'+
   '<label>Internal model store</label><div>'+esc(managed.models_dir||'')+'</div>'+
   settingsField('Local GGUF file','ollamaModelPath',selectedLocalModelPath)+
   settingsField('Imported model name','ollamaImportedName','')+
   '</div>'+
   '<div class="settings-note">Importing creates an Ollama model inside the Trade Company model store. The original GGUF is not used as a live server endpoint. Applying selects the model without resetting Company state; if Ollama was stopped before the import, it returns to stopped so you can start it explicitly.</div>'+
   '<div class="control-row"><button class="btn" onclick="pickLocalOllamaModel()">Choose GGUF</button><button class="btn" onclick="applyLocalOllamaModel()">Apply Local Model</button><button class="btn" onclick="startManagedOllama()">Start Ollama</button><button class="btn" onclick="stopManagedOllama()">Stop Ollama</button><button class="btn" onclick="refreshManagedOllama()">Refresh Runtime</button></div>'+
   '<div id="ollamaRuntimeStatus" class="settings-status">'+(managed.running?'Managed Ollama is ready.':(managed.installed?'Managed Ollama is installed but stopped.':'Managed Ollama runtime files are missing from this installation.'))+'</div>'
 );
 const newsCards=newsSources.length?newsSources.map(function(src,i){
   return '<div class="broker-card"><div class="list-title"><label><input id="newsEnabled_'+i+'" type="checkbox" '+(src.enabled!==false?'checked':'')+'> '+esc(src.name||src.url)+'</label>'+(src.built_in?' · BUILT-IN':' · CUSTOM')+'</div><div class="list-sub">'+esc(src.category||'custom')+' · '+esc(src.kind||'custom')+' · '+esc(src.url)+'</div><div class="control-row"><button class="btn" onclick="testNewsSource('+i+')">Test</button><button class="btn danger" onclick="removeNewsSource('+i+')">Remove</button></div></div>';
 }).join(''):'<div class="empty">No news sources configured.</div>';
 html+=section('🍺 Whispering Tankard · News Sources',
   '<div class="settings-note">Trusted defaults are installed automatically. You can paste either a direct RSS/Atom feed or a normal HTTPS news-site URL; Discover & Add will try to locate its feed. News is context/risk evidence only and never creates an order by itself.</div>'+
   newsCards+
   '<h3>Add news source</h3>'+
   '<div class="settings-grid">'+
   settingsField('Name','newsName','')+
   settingsField('Category','newsCategory','custom')+
   settingsField('Site or RSS URL','newsUrl','')+
   '</div>'+
   '<div class="control-row"><button class="btn" onclick="discoverAndAddNewsSource()">Discover & Add</button><button class="btn" onclick="testNewsUrl()">Test URL</button><button class="btn" onclick="saveNewsSources()">Save Sources</button><button class="btn" onclick="restoreNewsDefaults()">Restore Defaults</button><button class="btn" onclick="previewNews()">Preview Latest</button></div>'+
   '<div id="newsStatus" class="settings-status">'+esc((news.enabled_count||0)+' enabled source(s).')+'</div>'
 );
 const cards=profiles.length?profiles.map(function(p){
   const active=brokers.active_profile_id===p.id;
   const support=supported[p.provider]||{};
   return '<div class="broker-card '+(active?'active':'')+'"><div class="list-title">'+esc(p.label||p.id)+(active?' · ACTIVE':'')+'</div><div class="list-sub">'+esc(p.provider)+' · '+esc(p.environment)+' · key '+(p.api_key_configured?'configured':'missing')+' · secret '+(p.api_secret_configured?'configured':'missing')+(support.activatable?'':' · adapter pending')+'</div><div class="control-row"><button class="btn" onclick="editBrokerProfile(\''+esc(p.id)+'\')">Edit</button><button class="btn" onclick="testBrokerProfile(\''+esc(p.id)+'\')">Test</button>'+(support.activatable&&!active?'<button class="btn" onclick="activateBrokerProfile(\''+esc(p.id)+'\')">Set Active</button>':'')+(!active?'<button class="btn danger" onclick="deleteBrokerProfile(\''+esc(p.id)+'\')">Delete</button>':'')+'</div></div>';
 }).join(''):'<div class="empty">No broker profiles configured.</div>';
 html+=section('⚓ Broker Embassy',
   '<div class="settings-note">Broker credentials are stored in Windows Credential Manager, never in launcher.json or the Company database. Binance Japan / Spot is the supported broker. Use spot-testnet for autonomous test execution, production-readonly for observation only, or production-manual for REAL proposals that still require your confirmation on every order.</div>'+
   cards+
   '<h3 id="brokerFormTitle">'+(editingBrokerId?'Edit broker profile':'Add broker profile')+'</h3>'+
   '<div class="settings-grid">'+
   settingsField('Label','brokerLabel','')+
   settingsSelect('Broker','brokerProvider','binance',Object.keys(supported).map(function(k){return {value:k,label:(supported[k]&&supported[k].label)||k}}))+
   settingsSelect('Environment','brokerEnvironment','spot-testnet',[{value:'spot-testnet',label:'Spot Testnet (autonomous after mode selection)'},{value:'production-readonly',label:'Binance Japan Production (read-only)'},{value:'production-manual',label:'Binance Japan Production (manual confirmation per order)'}])+
   settingsField('API key','brokerApiKey','','password')+
   settingsField('API secret','brokerApiSecret','','password')+
   '</div>'+
   '<div class="settings-note">When editing, blank credential fields keep the existing secret. Switching the active broker is blocked while unresolved external execution intents exist. REAL mode is runtime-only and returns to PAPER whenever Trade Company restarts.</div>'+
   '<div class="control-row"><button class="btn" onclick="saveBrokerProfile()">Save Profile</button><button class="btn" onclick="newBrokerProfile()">New Profile</button></div>'+
   '<div id="brokerStatus" class="settings-status"></div>'
 );
 drawerTitle.textContent='City Settings';
 drawerTech.textContent='Arcane Nexus · Broker Embassy · persistent runtime configuration';
 drawerBody.innerHTML=html;
 if(editingBrokerId){
   const p=profiles.find(function(x){return x.id===editingBrokerId});
   if(p){byId('brokerLabel').value=p.label||'';byId('brokerProvider').value=p.provider||'binance';byId('brokerEnvironment').value=p.environment||'spot-testnet'}
 }
 drawer.classList.add('open');drawerBackdrop.classList.add('open');drawer.setAttribute('aria-hidden','false');
}
async function openSettings(){
 try{
  settingsCache=await api('/api/settings');
  if(!settingsCache.enabled)throw new Error(settingsCache.reason||'Runtime settings unavailable');
  activeLocation=null;activeTraderId=null;editingBrokerId=null;renderSettings();
 }catch(e){alert(e.message)}
}
async function discoverModels(){
 try{
  const payload={provider:byId('settingsProvider').value,base_url:byId('settingsBaseUrl').value,api_key:byId('settingsLlmKey').value||null};
  const r=await api('/api/settings/llm/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const models=r.models||[];
  const list=byId('settingsModelList');
  if(list)list.innerHTML=models.map(function(m){return '<option value="'+esc(m)+'"></option>'}).join('');
  if(models.length){const current=byId('settingsModel').value;if(models.indexOf(current)<0)byId('settingsModel').value=models[0]}
  byId('settingsLlmStatus').textContent=models.length?'Discovered '+models.length+' model(s). Choose one from the Model field.':'Connection succeeded; provider returned no model list.';
 }catch(e){byId('settingsLlmStatus').textContent='Error: '+e.message}
}
async function testLLMSettings(){
 try{
  const payload={provider:byId('settingsProvider').value,model:byId('settingsModel').value,base_url:byId('settingsBaseUrl').value,api_key:byId('settingsLlmKey').value||null};
  const r=await api('/api/settings/llm/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(r.ok&&r.matched_model&&byId('settingsModel'))byId('settingsModel').value=r.matched_model;
  byId('settingsLlmStatus').textContent=(r.ok?'✓ ':'⚠ ')+(r.message||'Test complete')+(r.matched_model&&r.matched_model!==payload.model?' · matched '+r.matched_model:'')+(r.models&&r.models.length?' · '+r.models.length+' model(s) discovered':'');
 }catch(e){byId('settingsLlmStatus').textContent='Error: '+e.message}
}
async function saveLLMSettings(){
 try{
  const payload={provider:byId('settingsProvider').value,model:byId('settingsModel').value,base_url:byId('settingsBaseUrl').value,api_key:byId('settingsLlmKey').value||null};
  await api('/api/settings/llm/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  settingsCache=await api('/api/settings');renderSettings();
 }catch(e){alert(e.message)}
}
async function refreshManagedOllama(){
 try{
  settingsCache=await api('/api/settings');
  renderSettings();
 }catch(e){const el=byId('ollamaRuntimeStatus');if(el)el.textContent='Error: '+e.message}
}
async function startManagedOllama(){
 const el=byId('ollamaRuntimeStatus');if(el)el.textContent='Starting managed Ollama...';
 try{
  const r=await api('/api/settings/ollama/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  settingsCache=await api('/api/settings');renderSettings();
  const status=byId('ollamaRuntimeStatus');if(status)status.textContent='Managed Ollama started at '+(r.base_url||'the internal endpoint')+'.';
 }catch(e){const status=byId('ollamaRuntimeStatus');if(status)status.textContent='Error: '+e.message}
}
async function stopManagedOllama(){
 const el=byId('ollamaRuntimeStatus');if(el)el.textContent='Stopping managed Ollama...';
 try{
  await api('/api/settings/ollama/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  settingsCache=await api('/api/settings');renderSettings();
 }catch(e){const status=byId('ollamaRuntimeStatus');if(status)status.textContent='Error: '+e.message}
}
async function pickLocalOllamaModel(){
 const el=byId('ollamaRuntimeStatus');if(el)el.textContent='Opening Windows model picker...';
 try{
  const r=await api('/api/settings/ollama/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!r.selected){if(el)el.textContent='No model selected.';return}
  selectedLocalModelPath=r.path||'';
  const pathEl=byId('ollamaModelPath');if(pathEl)pathEl.value=selectedLocalModelPath;
  const nameEl=byId('ollamaImportedName');if(nameEl&&!nameEl.value)nameEl.value=r.suggested_name||'';
  if(el)el.textContent='Selected '+selectedLocalModelPath;
 }catch(e){if(el)el.textContent='Error: '+e.message}
}
async function applyLocalOllamaModel(){
 const pathEl=byId('ollamaModelPath'),nameEl=byId('ollamaImportedName'),status=byId('ollamaRuntimeStatus');
 const source=(pathEl&&pathEl.value||'').trim();
 if(!source){if(status)status.textContent='Choose a GGUF file first.';return}
 selectedLocalModelPath=source;
 if(status)status.textContent='Importing the GGUF into managed Ollama. Large models can take a while...';
 try{
  const r=await api('/api/settings/ollama/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_path:source,model_name:(nameEl&&nameEl.value||'').trim()})});
  settingsCache=await api('/api/settings');renderSettings();
  const el=byId('ollamaRuntimeStatus');
  if(el){
   const running=!!(r.ollama_runtime&&r.ollama_runtime.running);
   el.textContent='✓ '+((r.imported&&r.imported.model)||'Model')+(running?' imported, selected, and running.':' imported and selected. Click Start Ollama when you want to use it.');
  }
 }catch(e){if(status)status.textContent='Error: '+e.message}
}
function collectNewsSources(){
 const rows=(settingsCache&&settingsCache.news&&settingsCache.news.sources)||[];
 return rows.map(function(src,i){
   const box=byId('newsEnabled_'+i);
   return Object.assign({},src,{enabled:box?box.checked:(src.enabled!==false)});
 });
}
function removeNewsSource(index){
 const rows=collectNewsSources();
 rows.splice(index,1);
 settingsCache.news=settingsCache.news||{};
 settingsCache.news.sources=rows;
 renderSettings();
}
async function saveNewsSources(){
 try{
  const r=await api('/api/settings/news/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sources:collectNewsSources()})});
  settingsCache=await api('/api/settings');renderSettings();
 }catch(e){const el=byId('newsStatus');if(el)el.textContent='Error: '+e.message}
}
async function discoverAndAddNewsSource(){
 const url=byId('newsUrl').value.trim();
 if(!url)return;
 try{
  const d=await api('/api/settings/news/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})});
  if(!d.ok)throw new Error(d.error||'RSS/Atom feed not found');
  const rows=collectNewsSources();
  if(rows.some(function(x){return x.url===d.feed_url}))throw new Error('Feed already configured');
  rows.push({id:'custom-'+Date.now(),name:byId('newsName').value.trim()||new URL(d.site_url).hostname,category:byId('newsCategory').value.trim()||'custom',url:d.feed_url,kind:'custom',enabled:true,built_in:false});
  settingsCache.news=settingsCache.news||{};settingsCache.news.sources=rows;
  renderSettings();
  const el=byId('newsStatus');if(el)el.textContent='Discovered '+d.feed_url+'. Click Save Sources to persist.';
 }catch(e){const el=byId('newsStatus');if(el)el.textContent='Error: '+e.message}
}
async function testNewsUrl(){
 const url=byId('newsUrl').value.trim();
 if(!url)return;
 try{
  const r=await api('/api/settings/news/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})});
  byId('newsStatus').textContent=(r.ok?'✓ ':'⚠ ')+(r.ok?('Feed works · '+r.count+' item(s)'):(r.error||'Feed failed'));
 }catch(e){byId('newsStatus').textContent='Error: '+e.message}
}
async function testNewsSource(index){
 const src=collectNewsSources()[index];if(!src)return;
 try{
  const r=await api('/api/settings/news/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:src.url})});
  alert((r.ok?'News source OK: ':'News source failed: ')+(r.ok?(r.count+' item(s)'):(r.error||src.url)));
 }catch(e){alert(e.message)}
}
async function restoreNewsDefaults(){
 if(!confirm('Restore the built-in news source list? Custom sources will be replaced.'))return;
 try{await api('/api/settings/news/defaults',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});settingsCache=await api('/api/settings');renderSettings()}catch(e){alert(e.message)}
}
async function previewNews(){
 try{
  await saveNewsSources();
  const r=await api('/api/settings/news/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:10})});
  const lines=(r.items||[]).slice(0,10).map(function(x){return '• '+x.title}).join('\n');
  const el=byId('newsStatus');if(el)el.textContent=(r.count||0)+' latest item(s)\n'+lines+(r.errors&&r.errors.length?'\nErrors: '+r.errors.length:'');
 }catch(e){const el=byId('newsStatus');if(el)el.textContent='Error: '+e.message}
}
function newBrokerProfile(){editingBrokerId=null;renderSettings()}
function editBrokerProfile(id){editingBrokerId=id;renderSettings()}
async function saveBrokerProfile(){
 try{
  const payload={profile_id:editingBrokerId,label:byId('brokerLabel').value,provider:byId('brokerProvider').value,environment:byId('brokerEnvironment').value,api_key:byId('brokerApiKey').value||null,api_secret:byId('brokerApiSecret').value||null};
  const saved=await api('/api/settings/brokers/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  editingBrokerId=saved.id;settingsCache=await api('/api/settings');renderSettings();
 }catch(e){byId('brokerStatus').textContent='Error: '+e.message}
}
async function testBrokerProfile(id){
 try{const r=await api('/api/settings/brokers/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:id})});alert('Broker connection OK: '+(r.message||'authenticated'))}catch(e){alert(e.message)}
}
async function activateBrokerProfile(id){
 try{await api('/api/settings/brokers/active',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:id})});settingsCache=await api('/api/settings');renderSettings()}catch(e){alert(e.message)}
}
async function deleteBrokerProfile(id){
 if(!confirm('Delete this broker profile and its stored credentials?'))return;
 try{await api('/api/settings/brokers/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:id})});editingBrokerId=null;settingsCache=await api('/api/settings');renderSettings()}catch(e){alert(e.message)}
}

function stateClass(state,attention){
 state=String(state||'').toLowerCase();
 if(attention && state!=='critical' && state!=='emergency')return 'attention';
 if(['critical','emergency','attention','active','quiet'].indexOf(state)>=0)return state;
 if(state==='healthy')return 'healthy';
 return 'quiet';
}

function applyPlaceStates(){
 if(!currentCity)return;
 document.querySelectorAll('.place').forEach(function(el){
   const id=el.dataset.location;
   const loc=currentCity.locations[id];
   el.classList.remove('healthy','attention','critical','emergency','active','quiet');
   if(loc)el.classList.add(stateClass(loc.state,loc.attention));
   if(loc)el.title=loc.title+' — '+loc.summary;
   const activity=document.querySelector('[data-activity="'+id+'"]');
   if(activity&&loc)activity.textContent=loc.summary;
 });
}

function executionModeLabel(mode){
 const labels={paper:'PAPER',testnet:'TESTNET','real-manual':'REAL · MANUAL'};
 return labels[mode]||String(mode||'PAPER').toUpperCase();
}
function proposalCard(row){
 const meta=row.meta||{},payload=row.payload||{},plan=meta.plan||{};
 const awaiting=row.status==='prepared'&&row.environment==='production-manual';
 const side=String(payload.side||plan.side||'').toUpperCase();
 const symbol=payload.symbol||plan.symbol||row.symbol||'—';
 const qty=payload.qty||'—';
 const ref=plan.reference_price===undefined?'—':price(plan.reference_price);
 const notional=plan.order_notional===undefined?'—':money(plan.order_notional);
 const source=meta.source||'agent_proposal';
 let controls='';
 if(awaiting){
  controls='<div class="control-row"><button class="btn" onclick="confirmExecutionProposal(\''+esc(row.intent_id)+'\')">Confirm Order</button><button class="btn danger" onclick="rejectExecutionProposal(\''+esc(row.intent_id)+'\')">Reject</button></div>';
 }
 return '<div class="execution-proposal '+(awaiting?'awaiting':'')+'"><div class="proposal-title">'+esc(row.status.toUpperCase())+' · '+esc(side)+' '+esc(symbol)+'</div><div class="proposal-meta">Trader '+esc(meta.trader_id||'—')+' · qty '+esc(qty)+' · planned notional '+esc(notional)+' · reference '+esc(ref)+'<br>Environment '+esc(row.environment)+' · '+esc(source)+'<br>Intent '+esc(row.intent_id)+'</div>'+controls+'</div>';
}
async function openExecution(){
 activeLocation=null;activeTraderId=null;
 try{
  const pair=await Promise.all([api('/api/execution/status'),api('/api/execution/proposals')]);
  currentExecution=pair[0];
  const proposals=pair[1]||[];
  const mode=currentExecution.mode||'paper';
  const broker=currentExecution.active_broker_profile||{};
  drawerTitle.textContent='Execution Gate';
  drawerTech.textContent='Human-only runtime mode · '+executionModeLabel(mode);
  let modeButtons='<div class="control-row"><button class="btn" onclick="setExecutionMode(\'paper\')">PAPER</button><button class="btn" onclick="setExecutionMode(\'testnet\')">BINANCE TESTNET</button><button class="btn danger" onclick="setExecutionMode(\'real-manual\')">BINANCE REAL</button></div>';
  let body='<div class="story">Only this local UI can change the execution mode. The LLM and Company Cell do not receive a mode-switch or order-confirmation command.</div>';
  body+=section('Execution Mode','<div class="metric-grid">'+metric('Current mode',executionModeLabel(mode))+metric('Resets on restart',currentExecution.resets_to_paper_on_restart?'PAPER':'—')+metric('Pending confirmations',currentExecution.pending_confirmations||0)+metric('Unresolved intents',currentExecution.unresolved||0)+'</div>'+modeButtons+'<div class="list-sub">PAPER/TESTNET changes require STOPPED + flat. REAL may be re-armed from STOPPING only when every open position is a previously confirmed REAL position.</div>');
  if(currentExecution.resume_blocked_reason)body+='<div class="execution-warning"><b>START BLOCKED</b><br>'+esc(currentExecution.resume_blocked_reason)+'<br>Re-arm REAL · MANUAL to manage the persisted production exposure.</div>';
  body+=section('Active Broker','<div class="metric-grid">'+metric('Profile',broker.label||'none')+metric('Environment',broker.environment||'—')+'</div>');
  if(mode==='real-manual')body+='<div class="execution-warning"><b>REAL MONEY MODE</b><br>Agents may create proposals, but no production order is submitted until you click Confirm Order for that exact intent. Restarting Trade Company returns the runtime to PAPER.</div>';
  const realRows=proposals.filter(function(x){return x.environment==='production-manual'}).slice(0,30);
  body+=section('REAL Order Approval Queue',realRows.length?realRows.map(proposalCard).join(''):'<div class="empty">No REAL order proposals are waiting or recorded.</div>');
  const testRows=proposals.filter(function(x){return x.environment==='spot-testnet'}).slice(0,12);
  body+=section('Recent TESTNET Intents',testRows.length?testRows.map(proposalCard).join(''):'<div class="empty">No TESTNET execution intents yet.</div>');
  drawerBody.innerHTML=body;
  drawer.classList.add('open');drawerBackdrop.classList.add('open');drawer.setAttribute('aria-hidden','false');
 }catch(e){alert(e.message)}
}
async function setExecutionMode(mode){
 let confirmation='';
 if(mode==='real-manual'){
  confirmation=prompt('REAL MONEY MODE\n\nTrade Company will generate real Binance order proposals, but every order still requires your individual confirmation.\n\nType ENABLE REAL to arm this runtime session:')||'';
  if(confirmation!=='ENABLE REAL')return;
 }
 try{
  await api('/api/execution/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode,confirmation:confirmation})});
  await tick();await openExecution();
 }catch(e){alert(e.message)}
}
async function confirmExecutionProposal(intentId){
 if(!confirm('Submit this exact REAL Binance order?\n\nIntent: '+intentId+'\n\nThis confirmation applies only to this one order.'))return;
 try{
  await api('/api/execution/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent_id:intentId,confirmation:'CONFIRM '+intentId})});
  await tick();await openExecution();
 }catch(e){alert(e.message)}
}
async function rejectExecutionProposal(intentId){
 if(!confirm('Reject this REAL order proposal?\n\n'+intentId))return;
 try{
  await api('/api/execution/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent_id:intentId})});
  await tick();await openExecution();
 }catch(e){alert(e.message)}
}

function renderVisibleTraders(){
 if(!currentCity)return;
 const traders=(currentCity.traders||[]).slice(0,8);
 guildAdventurers.innerHTML=traders.map(function(t){
   const activity=t.status==='active'?(t.market||'on expedition'):t.status.replaceAll('_',' ');
   return '<button class="mini-trader '+esc(t.status)+'" onclick="openTrader(\''+esc(t.id)+'\')" title="Trader '+esc(t.id)+' — '+esc(activity)+'"><span>'+traderAvatar(t.status)+'</span><b>'+esc(t.id)+'</b><span>'+esc(activity)+'</span></button>';
 }).join('');
}

function updateHud(){
 if(!currentStatus||!currentCity)return;
 const c=currentCity.city;
 hudEquity.textContent=money(c.company_equity);
 hudReserve.textContent=money(c.treasury_reserve);
 hudTraders.textContent=String(c.trader_slots)+' / '+String(c.effective_trader_limit);
 hudRisk.textContent=currentStatus.risk&&currentStatus.risk.kill_switch?'WARD LOCK':pct(currentStatus.risk&&currentStatus.risk.drawdown_pct);
 healthRune.textContent='CITY '+String(c.health||'unknown').toUpperCase();
 healthRune.className='rune '+(c.mood==='healthy'?'ok':(c.mood==='attention'||c.mood==='paused')?'warn':'bad');
 const execMode=(currentExecution&&currentExecution.mode)||'paper';
 modeRune.textContent=executionModeLabel(execMode);
 modeRune.className='rune mode '+(execMode==='paper'?'ok':(execMode==='testnet'?'warn':'bad'));
 alertRune.textContent=String(c.alerts)+' alert'+(c.alerts===1?'':'s');
 alertRune.className='rune '+(c.alerts?'warn':'ok');
 cityWorld.classList.toggle('emergency',!!c.emergency);
 const opState=String(currentStatus.operational_state||c.operational_state||(currentStatus.operations_paused?'stopped':'running'));
 operationRune.textContent=opState.replaceAll('_',' ').toUpperCase();
 operationRune.className='rune '+(opState==='running'?'ok':(opState==='stopping'||opState==='stopped'?'warn':'bad'));
 startOpsBtn.disabled=(opState==='running'||opState==='emergency_stopped'||!!(currentExecution&&currentExecution.resume_blocked_reason));
 stopOpsBtn.disabled=(opState==='stopping'||opState==='stopped'||opState==='emergency_stopped');
 emergencyOpsBtn.disabled=(opState==='emergency_stopped');
 const messages={
  healthy:['The Arcane Trading City prospers.','Wards stable. Guilds and institutions are operating normally.'],
  attention:['The city watch requests attention.','One or more institutions have raised an operational warning.'],
  critical:['Critical runes burn over the city.','A serious operational condition requires inspection.'],
  emergency:['The city gates are sealed.','Emergency Stop is active. Pending orders were cancelled and PAPER positions are being flattened where possible.'],
  stopping:['The closing bell has sounded.','No new entries are allowed. Existing positions may complete their risk-reducing path before the Company becomes STOPPED.'],
  paused:['The city is stopped.','Market observation continues, but no new risk may be opened until you press Start.']
 };
 const m=messages[c.mood]||messages.attention;
 cityMoodTitle.textContent=m[0];cityMoodText.textContent=m[1];
 const alerts=currentCity.alerts||[];
 alertText.textContent=alerts.length?alerts.slice(0,3).map(function(a){return a.kind}).join(' · '):'No alerts. The city watch is calm.';
 applyPlaceStates();
 renderVisibleTraders();
}

function traderAvatar(status){
 const map={active:'🗡️',waiting_assignment:'🧭',paused:'🛡️',evaluating:'🗺️',halted:'✨',retired:'🏅',candidate:'📜'};
 return map[status]||'⚔️';
}

function traderList(){
 const traders=(currentCity&&currentCity.traders)||[];
 if(!traders.length)return '<div class="empty">No adventurers are registered.</div>';
 return '<div class="trader-strip">'+traders.map(function(t){
   return '<div class="trader-chip" onclick="openTrader(\''+esc(t.id)+'\')"><div class="trader-avatar">'+traderAvatar(t.status)+'</div><div class="trader-id">Trader '+esc(t.id)+'</div><div class="trader-meta">'+esc(t.status)+' · '+esc(t.market||'no quest')+'</div></div>';
 }).join('')+'</div>';
}

function locationDetails(id){
 const s=currentStatus||{}, c=currentCity||{}, loc=(c.locations||{})[id]||{};
 const traders=(s.traders&&s.traders.traders)||{};
 const alerts=(c.alerts||[]).filter(function(a){
   const map={operational_trader_cap_violated:'citadel',trader_stop_floor:'risk',funded_trader_unassigned:'guild',direction_concentration:'risk',strategy_family_concentration:'risk',paper_treasury_reconciliation_mismatch:'treasury',company_kill_switch:'risk',caos_kill_switch:'nexus'};
   return (map[a.kind]||'citadel')===id;
 });
 let body='<div class="story">'+esc(loc.summary||'')+'</div>';

 if(id==='citadel'){
   body+=section('City State','<div class="metric-grid">'+metric('Audit',s.audit&&s.audit.status)+metric('Alerts',(s.audit&&s.audit.alerts||[]).length)+metric('Effective guild limit',s.effective_trader_limit)+metric('Configured cap',s.policy&&s.policy.operational_trader_cap)+'</div>');
   body+=section('Royal Charter','<div class="metric-grid">'+metric('Initial bucket',money(s.policy&&s.policy.trader_initial_bucket))+metric('Stop floor',money(s.policy&&s.policy.trader_stop_floor))+metric('Default max exposure',pct(s.policy&&s.policy.default_trader_max_exposure_pct))+metric('Company max drawdown',pct(s.policy&&s.policy.company_max_drawdown_pct))+'</div>');
   body+=section('Safe command seal','<div class="control-row"><label>Effective Trader limit <input id="limitInput" type="number" min="1" max="'+esc(s.policy&&s.policy.operational_trader_cap)+'" value="'+esc(s.effective_trader_limit)+'"></label><button class="btn" onclick="setLimit()">Apply</button><button class="btn danger" onclick="emergencyStop()">Emergency Stop</button></div><div class="list-sub">No raw order, broker credential, LIVE arm or kill-switch reset is exposed here.</div>');
 }
 if(id==='treasury'){
   const tr=s.treasury||{};
   body+=section('Royal Vault','<div class="metric-grid">'+metric('Reserve',money(tr.reserve))+metric('Realized company equity',money(tr.company_equity))+metric('Financial spawn capacity',s.treasury_spawn_capacity||0)+metric('Initial Trader bucket',money(s.policy&&s.policy.trader_initial_bucket))+'</div>');
   const balances=tr.balances||{};
   body+=section('Allocated purses','<div class="list">'+Object.keys(balances).filter(function(k){return k.indexOf('TRADER:')===0}).map(function(k){return listItem(k.replace('TRADER:','Trader '),money(balances[k]),'openTrader(\''+esc(k.replace('TRADER:',''))+'\')')}).join('')+'</div>');
   const led=(tr.ledger||[]).slice(-10).reverse();
   body+=section('Great Ledger',led.length?'<div class="list">'+led.map(function(e){return listItem(e.kind,money(e.amount)+' · '+(e.note||''))}).join('')+'</div>':'<div class="empty">The ledger is quiet.</div>');
 }
 if(id==='risk'){
   const r=s.risk||{}, ex=s.exposure||{}, div=s.diversity||{};
   body+=section('Protective Wards','<div class="metric-grid">'+metric('Company drawdown',pct(r.drawdown_pct))+metric('Gross exposure',money(ex.gross_notional))+metric('Kill switch',r.kill_switch?'ACTIVE':'OFF')+metric('Reconciliation',(s.reconciliation_mismatches||[]).length?'MISMATCH':'OK')+'</div>');
   body+=section('Council of Banners','<div class="metric-grid">'+metric('Active production',div.active_production||0)+metric('Long share',pct((div.long_share||0)*100))+metric('Short share',pct((div.short_share||0)*100))+metric('Warnings',(div.warnings||[]).length)+'</div>');
   body+=section('Exposure by adventurer','<div class="list">'+Object.entries(ex.by_trader||{}).map(function(row){return listItem('Trader '+row[0],money(row[1]),'openTrader(\''+esc(row[0])+'\')')}).join('')+'</div>');
 }
 if(id==='guild'){
   body+=section('Adventurers\' Guild',traderList());
   body+=section('Registered tactics','<div class="list">'+Object.entries(s.strategies||{}).map(function(row){return listItem(row[0],(row[1].family||'strategy')+' · fast '+row[1].fast+' / slow '+row[1].slow)}).join('')+'</div>');
   body+=section('Quest assignments','<div class="list">'+Object.entries(s.assignments||{}).map(function(row){return listItem('Trader '+row[0],row[1].symbol+' '+row[1].direction,'openTrader(\''+esc(row[0])+'\')')}).join('')+'</div>');
 }
 if(id==='quests'){
   const opp=Object.values(s.opportunities||{});
   body+=section('Quest Board',opp.length?'<div class="list">'+opp.map(function(o){return listItem(o.symbol+' '+o.direction,'score '+Number(o.score||0).toFixed(1)+' · '+o.status+' · '+(o.reserved_by?'Trader '+o.reserved_by:'unclaimed'))}).join('')+'</div>':'<div class="empty">No opportunity scrolls are posted.</div>');
 }
 if(id==='scout'){
   const caos=s.caos||{};
   body+=section('Pathfinder Map','<div class="metric-grid">'+metric('Loaded markets',(caos.symbols_loaded||[]).length)+metric('Opportunities',Object.keys(s.opportunities||{}).length)+'</div>');
   body+=section('Routes under observation','<div class="list">'+(caos.symbols_loaded||[]).map(function(sym){return listItem(sym,'execution cost '+String((caos.execution_cost_bps||{})[sym]||0)+' bps')}).join('')+'</div>');
 }
 if(id==='observatory'){
   const caos=s.caos||{};
   body+=section('Celestial Market Map','<div class="metric-grid">'+metric('Symbols loaded',(caos.symbols_loaded||[]).length)+metric('Portfolio entries',(caos.portfolio||[]).length)+metric('Approved sets',Object.keys(caos.approved_by_symbol||{}).length)+metric('Forecast oracles',((caos.experts||{}).forecast||[]).length)+'</div>');
   body+=section('Market instruments','<div class="list">'+Object.entries(caos.execution_cost_bps||{}).map(function(row){return listItem(row[0],String(row[1])+' bps estimated cost')}).join('')+'</div>');
 }
 if(id==='tavern'){
   const news=(s.caos&&s.caos.news)||{}, sentiment=(s.caos&&s.caos.experts&&s.caos.experts.sentiment)||null, intel=c.news_intelligence||s.news_intelligence||{}, contexts=intel.contexts||{}, latest=intel.latest_items||[], newsErrors=intel.errors||[];
   const blocked=Object.values(contexts).filter(function(x){return x&&x.block_new_risk}).length;
   body+=section('Bard\'s Table','<div class="metric-grid">'+metric('News configured',news.configured?'YES':'NO')+metric('Messenger feeds',news.feeds||0)+metric('Sentiment oracle',sentiment||'heuristic fallback')+metric('Markets under ward',blocked)+metric('Feed errors',newsErrors.length)+metric('Last refresh',intel.last_refresh_ms?new Date(intel.last_refresh_ms).toLocaleString():'—')+'</div>');
   body+='<div class="story">'+(news.configured?'The Bard reads configured messengers and turns their reports into context. News never creates an order. Critical negative news may block only NEW risk; reductions and exits remain allowed. Positive headlines never raise exposure above the technical strategy and risk limits.':'No news messengers are configured. The Bard will not invent rumors.')+'</div>';
   const contextRows=Object.entries(contexts);
   body+=section('Market News Wards',contextRows.length?'<div class="list">'+contextRows.map(function(row){const x=row[1]||{};const status=x.block_new_risk?'NEW RISK BLOCKED':(Number(x.score_penalty||0)>0?'CAUTION':'CLEAR');return listItem(row[0]+' · '+status,'severity '+esc(x.severity||'none')+' · sentiment '+Number(x.sentiment||0).toFixed(2)+' · score penalty '+Number(x.score_penalty||0).toFixed(1)+' · '+String((x.headlines||[]).length)+' relevant headline(s)')}).join('')+'</div>':'<div class="empty">No market-specific news context has been calculated yet.</div>');
   body+=section('Latest Dispatches',latest.length?'<div class="list">'+latest.slice(0,20).map(function(x){const sent=x.sentiment&&x.sentiment.signed_score!==undefined?' · sentiment '+Number(x.sentiment.signed_score).toFixed(2):'';return listItem(x.title||'Untitled dispatch',(x.published||'undated')+' · '+(x.source||'unknown source')+sent)}).join('')+'</div>':'<div class="empty">No dispatches have been collected yet.</div>');
   if(newsErrors.length)body+=section('Messenger Errors','<div class="list">'+newsErrors.slice(0,20).map(function(e){return listItem('Feed warning',e)}).join('')+'</div>');
 }
 if(id==='arena'){
   const experiments=Object.values(s.training||{}), rollout=c.rollout||{}, rsummary=c.rollout_summary||{}, releases=Object.values(rollout.releases||{});
   body+=section('Rollout Gate','<div class="metric-grid">'+metric('Releases',rsummary.releases||0)+metric('Shadow',(rsummary.stages||{}).shadow||0)+metric('Paper canary',(rsummary.stages||{}).paper_canary||0)+metric('Eligible',(rsummary.stages||{}).eligible||0)+metric('Active',(rsummary.stages||{}).active||0)+metric('Rolled back',(rsummary.stages||{}).rolled_back||0)+'</div>');
   body+=section('Strategy Releases',releases.length?'<div class="list">'+releases.map(function(r){const ca=r.canary||{};let controls='';if(r.stage==='eligible')controls='<button class="btn" onclick="event.stopPropagation();activateRelease(\''+esc(r.id)+'\')">Activate release</button>';if(r.stage==='active')controls='<button class="btn danger" onclick="event.stopPropagation();rollbackRelease(\''+esc(r.id)+'\')">Rollback</button>';const detail=(r.strategy_id||'')+' · '+r.stage+(r.canary?' · equity '+money(ca.equity)+' · PnL '+pct(ca.pnl_pct)+' · DD '+pct(ca.max_drawdown_pct)+' · '+String(ca.trades||0)+' trades':'')+(r.rollback_reason?' · '+r.rollback_reason:'');return '<div class="list-item"><div class="list-title">'+esc(r.symbol+' · '+String(r.id).slice(0,12))+'</div><div class="list-sub">'+esc(detail)+'</div><div class="control-row">'+controls+'</div></div>'}).join('')+'</div>':'<div class="empty">No champion releases are in rollout yet.</div>');
   body+=section('Production Catalog',Object.keys(rsummary.production_catalog||{}).length?'<div class="list">'+Object.entries(rsummary.production_catalog||{}).map(function(row){return listItem(row[0],row[1])}).join('')+'</div>':'<div class="empty">No research strategy is active for new assignments.</div>');
   body+=section('Tournament Records',experiments.length?'<div class="list">'+experiments.map(function(e){const best=(e.results||[])[0];return listItem(e.symbol+' · '+String(e.id).slice(0,8),(best?'leader '+best.variant:'no results')+' · capital '+money(e.starting_capital))}).join('')+'</div>':'<div class="empty">No tournaments have been recorded.</div>');
 }
 if(id==='workshop'){
   const imp=c.improvements||[], research=c.research||{}, summary=c.research_summary||{};
   body+=section('Research Factory','<div class="metric-grid">'+metric('Hypotheses',summary.hypotheses||0)+metric('Candidates',summary.candidates||0)+metric('Evaluations',summary.evaluations||0)+metric('Champions',Object.keys(summary.champions||{}).length)+'</div>');
   const champs=Object.entries(summary.champions||{});
   body+=section('Champions',champs.length?'<div class="list">'+champs.map(function(row){return listItem(row[0],row[1])}).join('')+'</div>':'<div class="empty">No champion has been promoted yet.</div>');
   const decisions=(research.decisions||[]).slice().reverse().slice(0,10);
   body+=section('Promotion Council',decisions.length?'<div class="list">'+decisions.map(function(d){return listItem((d.status||'decision').toUpperCase()+' · '+(d.symbol||''),(d.candidate_strategy_id||'no candidate')+' · '+(d.reason||''))}).join('')+'</div>':'<div class="empty">No promotion decisions yet.</div>');
   const hypotheses=Object.values(research.hypotheses||{}).slice(-10).reverse();
   body+=section('Hypothesis Scrolls',hypotheses.length?'<div class="list">'+hypotheses.map(function(h){return listItem(h.symbol+' · '+h.family,h.thesis+' · '+h.status)}).join('')+'</div>':'<div class="empty">No research hypotheses have been submitted.</div>');
   body+=section('Improvement Proposals',imp.length?'<div class="list">'+imp.map(function(p){return listItem(p.kind,(p.target?'target '+p.target+' · ':'')+p.reason+(p.requires_human?' · human action required':''))}).join('')+'</div>':'<div class="empty">No improvement proposals right now.</div>');
 }
 if(id==='nexus'){
   const caos=s.caos||{}, experts=caos.experts||{};
   body+=section('Arcane Engine','<div class="metric-grid">'+metric('C.A.O.S kill',caos.kill_switch?'ACTIVE':'OFF')+metric('Orchestrator',caos.orchestrator||'—')+metric('Forecast oracles',(experts.forecast||[]).join(', ')||'none')+metric('Sentiment oracle',experts.sentiment||'none')+'</div>');
   body+=section('Specialist qualifications',Object.keys(caos.expert_qualifications||{}).length?json(caos.expert_qualifications):'<div class="empty">No specialist qualification records.</div>');
   body+=section('Technical diagnostics','<button class="btn" onclick="window.open(\'http://127.0.0.1:5190\',\'_blank\')">Open technical C.A.O.S dashboard</button>');
 }
 if(id==='chronicle'){
   const events=c.recent_events||[], rel=c.execution_reliability||{}, intents=rel.recent_intents||[], counts=rel.counts||{};
   body+=section('Execution Reliability','<div class="metric-grid">'+metric('Intent journal',rel.version||'—')+metric('Total intents',rel.total||0)+metric('Prepared',counts.prepared||0)+metric('Acknowledged',counts.acknowledged||0)+metric('Reconciled',counts.reconciled||0)+metric('Recovery required',rel.recovery_required||0)+'</div>');
   body+=section('External Execution Intents',intents.length?'<div class="list">'+intents.map(function(x){return listItem((x.status||'intent').toUpperCase()+' · '+(x.symbol||''),(x.intent_id||'')+' · plan '+(x.plan_id||'')+(x.reconciliation_status?' · '+x.reconciliation_status:'')+(x.last_error?' · '+x.last_error:''))}).join('')+'</div>':'<div class="empty">No external execution intents are recorded.</div>');
   body+=section('Recent Chronicles',events.length?'<div class="list">'+events.slice(0,30).map(function(e){return listItem(e.kind,e.created_at+' · '+JSON.stringify(e.payload).slice(0,150))}).join('')+'</div>':'<div class="empty">No recent chronicles are available.</div>');
   body+=section('Recovery State','<div class="metric-grid">'+metric('Paper reconciliation',(s.reconciliation_mismatches||[]).length?'MISMATCH':'OK')+metric('External recovery',(rel.recovery_required||0)?'REQUIRED':'CLEAR')+metric('Paper accounts',Object.keys((s.paper&&s.paper.accounts)||{}).length)+'</div><div class="story">Broker credentials are never stored or exposed here. Ambiguous external intents must be reconciled before any retry.</div>');
 }
 if(alerts.length)body+=section('Attention requested','<div class="list">'+alerts.map(function(a){return listItem(a.kind,a.severity||'attention')}).join('')+'</div>');
 body+='<details class="detail-section"><summary style="cursor:pointer;color:#f1d796;font-weight:700">Technical truth</summary>'+json({location:loc,status_snapshot:technicalSnapshot(id,s)})+'</details>';
 return body;
}

function technicalSnapshot(id,s){
 if(id==='citadel')return {audit:s.audit,policy:s.policy,effective_trader_limit:s.effective_trader_limit};
 if(id==='treasury')return s.treasury;
 if(id==='risk')return {risk:s.risk,exposure:s.exposure,diversity:s.diversity,reconciliation:s.reconciliation_mismatches};
 if(id==='guild')return {traders:s.traders,assignments:s.assignments,strategies:s.strategies};
 if(id==='quests')return s.opportunities;
 if(id==='scout')return {symbols_loaded:s.caos&&s.caos.symbols_loaded,execution_cost_bps:s.caos&&s.caos.execution_cost_bps};
 if(id==='observatory')return {approved_by_symbol:s.caos&&s.caos.approved_by_symbol,portfolio:s.caos&&s.caos.portfolio,experts:s.caos&&s.caos.experts};
 if(id==='tavern')return {news:s.caos&&s.caos.news,sentiment:s.caos&&s.caos.experts&&s.caos.experts.sentiment};
 if(id==='arena')return {training:s.training,rollout:s.rollout,rollout_summary:s.rollout_summary};
 if(id==='workshop')return {research:currentCity&&currentCity.research,improvements:currentCity&&currentCity.improvements};
 if(id==='nexus')return s.caos;
 if(id==='chronicle')return currentCity&&currentCity.recent_events;
 return {};
}

function openLocation(id){
 if(!currentCity||!currentStatus)return;
 activeTraderId=null;
 activeLocation=id;
 const loc=currentCity.locations[id];
 if(!loc)return;
 drawerTitle.textContent=loc.title;
 drawerTech.textContent=loc.technical_name+' · '+loc.character;
 drawerBody.innerHTML=locationDetails(id);
 drawer.classList.add('open');drawerBackdrop.classList.add('open');drawer.setAttribute('aria-hidden','false');
}
function closeDrawer(){drawer.classList.remove('open');drawerBackdrop.classList.remove('open');drawer.setAttribute('aria-hidden','true');activeLocation=null;activeTraderId=null}

function price(v){
 const n=Number(v);
 if(!Number.isFinite(n))return '—';
 if(Math.abs(n)>=1000)return n.toFixed(2);
 if(Math.abs(n)>=1)return n.toFixed(4);
 return n.toPrecision(6);
}
function phaseLabel(phase){
 const labels={waiting_assignment:'WAITING ASSIGNMENT',waiting_entry:'WAITING ENTRY',pending_entry:'OPEN ENTRY ORDER',pending_exit:'OPEN EXIT ORDER',in_position:'IN POSITION',paused:'PAUSED',halted:'HALTED',retired:'RETIRED',flat:'FLAT'};
 return labels[phase]||String(phase||'UNKNOWN').replaceAll('_',' ').toUpperCase();
}
function renderTraderChart(chart){
 const bars=chart&&chart.bars||[],position=chart&&chart.position||{},markers=chart&&chart.markers||[],ind=chart&&chart.indicators||{},pending=chart&&chart.pending_order||null,orderEvents=chart&&chart.order_events||[];
 const phase=chart&&chart.phase||'flat';
 const title=esc((chart&&chart.symbol)||'No market assigned');
 const phaseHtml='<span class="trader-phase '+esc(phase)+'">'+esc(phaseLabel(phase))+'</span>';
 if(!bars.length){
  return '<div class="trader-chart-shell"><div class="trader-chart-head"><div><div class="trader-chart-title">'+title+'</div>'+phaseHtml+'</div><div class="trader-chart-meta">PAPER · waiting for market candles</div></div><div class="empty" style="padding:28px 12px">No candle data is loaded for this Trader yet.</div></div>';
 }
 const W=900,H=360,L=58,R=18,T=22,B=32,plotW=W-L-R,plotH=H-T-B;
 let lo=Math.min.apply(null,bars.map(function(b){return Number(b.low)})),hi=Math.max.apply(null,bars.map(function(b){return Number(b.high)}));
 if(position.avg_price){lo=Math.min(lo,Number(position.avg_price));hi=Math.max(hi,Number(position.avg_price))}
 if(pending&&pending.trigger_price){lo=Math.min(lo,Number(pending.trigger_price));hi=Math.max(hi,Number(pending.trigger_price))}
 let span=hi-lo;if(!Number.isFinite(span)||span<=0)span=Math.max(Math.abs(hi)*.01,1);
 lo-=span*.06;hi+=span*.06;span=hi-lo;
 const x=function(i){return L+(bars.length<=1?plotW/2:(i/(bars.length-1))*plotW)};
 const y=function(v){return T+((hi-Number(v))/span)*plotH};
 let svg='';
 for(let i=0;i<=4;i++){const yy=T+(plotH*i/4),val=hi-(span*i/4);svg+='<line class="chart-grid" x1="'+L+'" y1="'+yy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+yy.toFixed(1)+'"></line><text class="chart-axis" x="4" y="'+(yy+3).toFixed(1)+'">'+esc(price(val))+'</text>'}
 const step=plotW/Math.max(bars.length,1),bodyW=Math.max(1.4,Math.min(8,step*.62));
 bars.forEach(function(b,i){const xx=x(i),up=Number(b.close)>=Number(b.open),cls=up?'up':'down',yo=y(b.open),yc=y(b.close),yh=y(b.high),yl=y(b.low),top=Math.min(yo,yc),height=Math.max(1.2,Math.abs(yc-yo));svg+='<line class="chart-wick '+cls+'" x1="'+xx.toFixed(2)+'" y1="'+yh.toFixed(2)+'" x2="'+xx.toFixed(2)+'" y2="'+yl.toFixed(2)+'"></line><rect class="chart-body '+cls+'" x="'+(xx-bodyW/2).toFixed(2)+'" y="'+top.toFixed(2)+'" width="'+bodyW.toFixed(2)+'" height="'+height.toFixed(2)+'"></rect>'});
 const byTs={};bars.forEach(function(b,i){byTs[String(b.ts)]=i});
 function poly(rows,cls){if(!rows||!rows.length)return '';const pts=rows.map(function(p){let i=byTs[String(p.ts)];if(i===undefined)return null;return x(i).toFixed(1)+','+y(p.value).toFixed(1)}).filter(Boolean);return pts.length>1?'<polyline class="'+cls+'" points="'+pts.join(' ')+'"></polyline>':''}
 svg+=poly(ind.ma7,'chart-ma7')+poly(ind.ma25,'chart-ma25')+poly(ind.ma99,'chart-ma99');
 if(position.avg_price){const yy=y(position.avg_price);svg+='<line class="chart-average" x1="'+L+'" y1="'+yy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+yy.toFixed(1)+'"></line><text class="chart-avg-label" x="'+(L+5)+'" y="'+(yy-5).toFixed(1)+'">AVG '+esc(price(position.avg_price))+'</text>'}
 if(position.current_price){const yy=y(position.current_price);svg+='<line class="chart-current" x1="'+L+'" y1="'+yy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+yy.toFixed(1)+'"></line>'}
 if(pending&&pending.trigger_price){const yy=y(pending.trigger_price),label='OPEN '+String(pending.side||'').toUpperCase()+' '+String(pending.order_type||'').toUpperCase()+' '+price(pending.trigger_price);svg+='<line class="chart-pending" x1="'+L+'" y1="'+yy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+yy.toFixed(1)+'"></line><text class="chart-pending-label" x="'+(W-R-4)+'" y="'+(yy-6).toFixed(1)+'">'+esc(label)+'</text>'}
 markers.forEach(function(m){let best=0,bestD=Infinity;bars.forEach(function(b,i){const d=Math.abs(Number(b.ts)-Number(m.ts));if(d<bestD){bestD=d;best=i}});const xx=x(best),yy=y(m.price),buy=m.kind==='buy',cy=buy?Math.min(H-B-14,yy+18):Math.max(T+14,yy-18),cls=buy?'chart-buy':'chart-sell',letter=buy?'B':'S';svg+='<line x1="'+xx.toFixed(1)+'" y1="'+yy.toFixed(1)+'" x2="'+xx.toFixed(1)+'" y2="'+cy.toFixed(1)+'" stroke="rgba(255,255,255,.28)" stroke-width="1"></line><circle class="'+cls+'" cx="'+xx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="10"></circle><text class="chart-marker-text" x="'+xx.toFixed(1)+'" y="'+(cy+.5).toFixed(1)+'">'+letter+'</text>'});
 const first=new Date(Number(bars[0].ts)).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),last=new Date(Number(bars[bars.length-1].ts)).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
 svg+='<text class="chart-axis" x="'+L+'" y="'+(H-8)+'">'+esc(first)+'</text><text class="chart-axis" text-anchor="end" x="'+(W-R)+'" y="'+(H-8)+'">'+esc(last)+'</text>';
 const pnl=position.unrealized_pnl_pct===null||position.unrealized_pnl_pct===undefined?'—':pct(position.unrealized_pnl_pct);
 const events=markers.slice(-8).reverse().map(function(m){return '<div class="chart-event"><strong>'+(m.kind==='buy'?'🟢 BUY':'🔴 SELL')+' · '+esc(price(m.price))+'</strong>'+esc(new Date(Number(m.ts)).toLocaleString())+' · '+esc(m.action||'fill')+'</div>'}).join('');
 const pendingCard=pending?'<div class="pending-order-card"><strong>🟠 OPEN PAPER ORDER · '+esc(String(pending.side||'').toUpperCase())+' '+esc(String(pending.order_type||'').toUpperCase())+'</strong>Trigger <b>'+esc(price(pending.trigger_price))+'</b> · notional <b>'+esc(money(pending.notional))+'</b> · waiting <b>'+esc(String(pending.age_bars||0))+' candle(s)</b><br>Strategy '+esc(pending.strategy||'—')+' · plan <code>'+esc(String(pending.plan_id||'').slice(0,24))+'</code></div>':'';
 const orderHistory=orderEvents.length?'<div class="order-history">'+orderEvents.slice(-6).reverse().map(function(o){const icon=o.kind==='opened'?'🟠':(o.kind==='filled'?'✅':'✕');return '<div class="order-history-row"><b>'+icon+' '+esc(String(o.kind||'order').toUpperCase())+' '+esc(String(o.side||'').toUpperCase())+'</b> · '+esc(price(o.trigger_price))+' · '+esc(new Date(Number(o.ts)).toLocaleString())+(o.reason?' · '+esc(o.reason):'')+'</div>'}).join('')+'</div>':'';
 const headOrder=pending?'<br>Open '+esc(String(pending.side||'').toUpperCase())+' @ '+esc(price(pending.trigger_price)):'';
 return '<div class="trader-chart-shell"><div class="trader-chart-head"><div><div class="trader-chart-title">'+title+' · PAPER</div>'+phaseHtml+'</div><div class="trader-chart-meta">Last '+bars.length+' candles<br>Price '+esc(price(position.current_price))+(position.avg_price?'<br>Avg entry '+esc(price(position.avg_price))+' · PnL '+esc(pnl):'')+headOrder+'</div></div><svg class="trader-chart" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="PAPER candlestick chart for '+title+'">'+svg+'</svg>'+pendingCard+'<div class="chart-legend"><span><b>MA7</b> gold</span><span><b>MA25</b> violet</span><span><b>MA99</b> cyan</span><span><b style="color:#ffae42">OPEN</b> pending limit order</span><span><b>B</b> PAPER buy</span><span><b>S</b> PAPER sell/reduce</span>'+(position.avg_price?'<span><b>AVG</b> active position average</span>':'')+'</div>'+(events?'<div class="chart-events">'+events+'</div>':'')+orderHistory+'</div>';
}
async function refreshTraderChart(id){
 const slot=byId('traderLiveChart');
 if(!slot||activeTraderId!==id)return;
 try{
  const chart=await api('/api/company/traders/'+encodeURIComponent(id)+'/chart?limit=160');
  if(activeTraderId===id&&byId('traderLiveChart'))byId('traderLiveChart').innerHTML=renderTraderChart(chart);
 }catch(e){
  if(activeTraderId===id&&byId('traderLiveChart'))byId('traderLiveChart').innerHTML='<div class="trader-chart-shell"><div class="empty" style="padding:20px">Chart unavailable: '+esc(e.message)+'</div></div>';
 }
}

async function openTrader(id){
 const t=currentStatus&&currentStatus.traders&&currentStatus.traders.traders&&currentStatus.traders.traders[id];
 if(!t)return;
 activeLocation=null;activeTraderId=id;
 const bal=(currentStatus.treasury&&currentStatus.treasury.balances&&currentStatus.treasury.balances['TRADER:'+id])||0;
 const exp=(currentStatus.exposure&&currentStatus.exposure.by_trader&&currentStatus.exposure.by_trader[id])||0;
 const requested=t.trade_exposure_pct===null||t.trade_exposure_pct===undefined?t.max_trade_exposure_pct:t.trade_exposure_pct;
 const maxNotional=Number(bal)*Number(t.max_trade_exposure_pct||0)/100;
 const requestedNotional=Number(bal)*Number(requested||0)/100;
 const fabric=currentStatus.execution_fabric||{};
 const lastPlan=(fabric.last_plans||{})[id]||null;
 drawerTitle.textContent='Adventurer '+id;
 drawerTech.textContent='Trader '+id+' · '+t.status+' · live PAPER view';
 let actions='';
 if(t.status==='active')actions='<button class="btn" onclick="pauseTrader(\''+esc(id)+'\')">Pause Adventurer</button>';
 if(t.status==='paused')actions='<button class="btn" onclick="resumeTrader(\''+esc(id)+'\')">Resume Adventurer</button>';
 const exposureControls='<div class="control-row"><label>Chosen size % <input id="traderSizeInput" type="number" min="0.01" step="0.01" value="'+esc(requested)+'"></label><label>Max seal % <input id="traderMaxInput" type="number" min="0.01" max="100" step="0.01" value="'+esc(t.max_trade_exposure_pct)+'"></label><button class="btn" onclick="setTraderExposure(\''+esc(id)+'\')">Apply</button></div>';
 drawerBody.innerHTML='<div class="story">'+traderAvatar(t.status)+' This adventurer is '+esc(t.status)+'. The chart below uses the same live market candles and PAPER fills used by the Company.</div>'+
 section('Live PAPER Chart','<div id="traderLiveChart"><div class="trader-chart-shell"><div class="empty" style="padding:20px">Loading market chart…</div></div></div>')+
 section('Current Quest','<div class="metric-grid">'+metric('Market',t.market||'none')+metric('Direction',t.direction||'—')+metric('Strategy',t.strategy_id||'—')+metric('Mode',t.mode)+'</div>')+
 section('Capital & Risk Seal','<div class="metric-grid">'+metric('Realized capital',money(bal))+metric('Open exposure',money(exp))+metric('Chosen sizing',pct(requested))+metric('Maximum exposure',pct(t.max_trade_exposure_pct))+metric('Requested notional',money(requestedNotional))+metric('Maximum notional',money(maxNotional))+'</div>')+
 section('Execution Fabric',lastPlan?'<div class="metric-grid">'+metric('Fabric',fabric.version||'—')+metric('Plan action',lastPlan.action||'—')+metric('Desired target',money(lastPlan.desired_target_notional))+metric('Effective target',money(lastPlan.effective_target_notional))+metric('Order delta',money(lastPlan.order_notional))+metric('Risk reducing',lastPlan.risk_reducing?'YES':'NO')+'</div><div class="list-sub">Plan '+esc(lastPlan.plan_id||'')+'</div>':'<div class="empty">No execution plan has been produced for this Trader yet.</div>')+
 section('Guild Controls',actions+exposureControls)+
 '<details class="detail-section"><summary style="cursor:pointer;color:#f1d796;font-weight:700">Technical truth</summary>'+json({trader:t,paper:currentStatus.paper&&currentStatus.paper.accounts&&currentStatus.paper.accounts[id],assignment:currentStatus.assignments&&currentStatus.assignments[id]})+'</details>';
 drawer.classList.add('open');drawerBackdrop.classList.add('open');drawer.setAttribute('aria-hidden','false');
 await refreshTraderChart(id);
}

async function startOperations(){
 try{
  await api('/api/company/start',{method:'POST'});
  await tick();
 }catch(e){alert(e.message)}
}
async function stopOperations(){
 if(!confirm('Stop opening new risk? Existing PAPER positions will be allowed to complete their risk-reducing path first.'))return;
 try{
  await api('/api/company/stop',{method:'POST'});
  await tick();
 }catch(e){alert(e.message)}
}
async function emergencyStopOperations(){
 if(!confirm('EMERGENCY STOP: cancel pending orders and immediately flatten every PAPER position that can be closed?'))return;
 try{
  const r=await api('/api/company/emergency-stop',{method:'POST'});
  await tick();
  const failed=Object.keys(r.flatten_errors||{});
  if(failed.length)alert('Emergency Stop active. Could not flatten: '+failed.join(', '));
 }catch(e){alert(e.message)}
}

async function activateRelease(id){
 try{
  await api('/api/company/rollout/'+encodeURIComponent(id)+'/activate',{method:'POST'});
  await tick();openLocation('arena');
 }catch(e){alert(e.message)}
}
async function rollbackRelease(id){
 if(!confirm('Rollback this strategy release for future assignments? Existing Trader positions will not be force-closed.'))return;
 try{
  await api('/api/company/rollout/'+encodeURIComponent(id)+'/rollback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'themed_city_manual_rollback'})});
  await tick();openLocation('arena');
 }catch(e){alert(e.message)}
}

async function setLimit(){
 try{const v=Number(document.getElementById('limitInput').value);await api('/api/company/limit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:v})});await tick();openLocation('citadel')}catch(e){alert(e.message)}
}
async function emergencyStop(){
 if(!confirm('Seal the city gates and activate EMERGENCY STOP? The themed UI cannot reset the kill switch.'))return;
 try{await api('/api/company/emergency-stop',{method:'POST'});await tick();openLocation('risk')}catch(e){alert(e.message)}
}
async function pauseTrader(id){try{await api('/api/company/traders/'+encodeURIComponent(id)+'/pause',{method:'POST'});await tick();openTrader(id)}catch(e){alert(e.message)}}
async function resumeTrader(id){try{await api('/api/company/traders/'+encodeURIComponent(id)+'/resume',{method:'POST'});await tick();openTrader(id)}catch(e){alert(e.message)}}
async function setTraderExposure(id){
 try{
  const max=Number(document.getElementById('traderMaxInput').value);
  const size=Number(document.getElementById('traderSizeInput').value);
  await api('/api/company/traders/'+encodeURIComponent(id)+'/exposure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_trade_exposure_pct:max,trade_exposure_pct:size})});
  await tick();openTrader(id);
 }catch(e){alert(e.message)}
}

async function tick(){
 try{
  const pair=await Promise.all([api('/api/company/status'),api('/api/company/city'),api('/api/execution/status')]);
  currentStatus=pair[0];currentCity=pair[1];currentExecution=pair[2];updateHud();
  if(activeTraderId)await refreshTraderChart(activeTraderId);
  else if(activeLocation)openLocation(activeLocation);
 }catch(e){
  healthRune.textContent='CITY OFFLINE';healthRune.className='rune bad';
  cityMoodTitle.textContent='The city has gone silent.';cityMoodText.textContent=e.message;
 }
}

document.querySelectorAll('.place').forEach(function(el){el.addEventListener('click',function(){openLocation(el.dataset.location)})});
settingsBtn.addEventListener('click',openSettings);
modeRune.addEventListener('click',openExecution);
startOpsBtn.addEventListener('click',startOperations);
stopOpsBtn.addEventListener('click',stopOperations);
emergencyOpsBtn.addEventListener('click',emergencyStopOperations);
drawerClose.addEventListener('click',closeDrawer);drawerBackdrop.addEventListener('click',closeDrawer);
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDrawer()});
tick();setInterval(tick,2000);
</script>
</body>
</html>'''


def serve_company(
    control: CompanyControlPort,
    *,
    host: str = "127.0.0.1",
    port: int = 5191,
    open_browser: bool = True,
    settings_service=None,
    execution_service=None,
    chat_service=None,
) -> ThreadingHTTPServer:
    mapper = CityPresentationMapper()
    cell = TradeCompanyCell(control)

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

        def _city_payload(self) -> dict:
            status = control.get_company_status()
            return mapper.build(
                status,
                improvements=control.request_improvement(),
                recent_events=control.get_recent_events(40),
            )

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/api/cell/v1/manifest":
                self._json(200, cell.get_manifest())
                return
            if path == "/api/cell/v1/status":
                self._json(200, cell.get_status())
                return
            if path == "/api/cell/v1/health":
                self._json(200, cell.get_health())
                return
            if path == "/api/cell/v1/metrics":
                self._json(200, cell.get_metrics())
                return
            if path == "/api/cell/v1/alerts":
                self._json(200, cell.get_alerts())
                return
            if path == "/api/cell/v1/events":
                self._json(200, cell.get_recent_events(50))
                return
            if path == "/api/cell/v1/report":
                self._json(200, cell.get_report())
                return
            if path == "/api/company/status":
                self._json(200, control.get_company_status())
                return
            if path == "/api/company/city":
                self._json(200, self._city_payload())
                return
            if path == "/api/company/treasury":
                self._json(200, control.get_treasury())
                return
            if path == "/api/company/traders":
                self._json(200, control.list_traders())
                return
            if (
                path.startswith("/api/company/traders/")
                and path.endswith("/chart")
            ):
                parts = path.strip("/").split("/")
                if len(parts) != 5:
                    self.send_error(404)
                    return
                trader_id = unquote(parts[3])
                try:
                    limit = int(
                        query.get("limit", ["160"])[0]
                    )
                except (TypeError, ValueError):
                    limit = 160
                self._json(
                    200,
                    control.get_trader_chart(
                        trader_id,
                        limit=limit,
                    ),
                )
                return
            if path == "/api/company/opportunities":
                self._json(200, control.list_opportunities())
                return
            if path == "/api/company/experiments":
                self._json(200, control.list_experiments())
                return
            if path == "/api/company/reliability":
                self._json(
                    200,
                    control.get_execution_reliability(),
                )
                return
            if path == "/api/company/rollout":
                self._json(200, control.get_strategy_rollouts())
                return
            if path == "/api/company/events":
                self._json(200, control.get_recent_events(50))
                return
            if path == "/api/execution/status":
                if execution_service is None:
                    self._json(
                        200,
                        {
                            "enabled": False,
                            "mode": "paper",
                        },
                    )
                else:
                    self._json(
                        200,
                        {
                            "enabled": True,
                            **execution_service.status(),
                        },
                    )
                return
            if path == "/api/execution/proposals":
                if execution_service is None:
                    self._json(200, [])
                else:
                    self._json(
                        200,
                        execution_service.list_proposals(),
                    )
                return
            if path == "/api/chat/history":
                if chat_service is None:
                    self._json(
                        200,
                        {
                            "enabled": False,
                            "messages": [],
                        },
                    )
                else:
                    self._json(
                        200,
                        {
                            "enabled": True,
                            "messages": chat_service.messages(),
                        },
                    )
                return
            if path == "/api/settings":
                if settings_service is None:
                    self._json(
                        200,
                        {
                            "enabled": False,
                            "reason": "runtime_settings_unavailable",
                        },
                    )
                else:
                    self._json(
                        200,
                        {
                            "enabled": True,
                            **settings_service.get_settings(),
                        },
                    )
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
                if path == "/api/cell/v1/command":
                    payload = self._read_json()
                    self._json(
                        200,
                        cell.execute_command(
                            str(payload["name"]),
                            payload.get("args"),
                        ),
                    )
                    return
                if path == "/api/company/start":
                    self._json(200, control.start_operations())
                    return
                if path == "/api/company/stop":
                    rejected = (
                        execution_service.cancel_new_risk_proposals()
                        if execution_service is not None
                        else []
                    )
                    result = control.stop_operations()
                    result["rejected_external_entries"] = rejected
                    self._json(200, result)
                    return
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
                    self._json(
                        200,
                        (
                            execution_service.emergency_stop()
                            if execution_service is not None
                            else control.emergency_stop()
                        ),
                    )
                    return
                if path == "/api/execution/mode":
                    if execution_service is None:
                        raise RuntimeError(
                            "runtime_execution_unavailable"
                        )
                    payload = self._read_json()
                    self._json(
                        200,
                        execution_service.set_mode(
                            str(payload.get("mode", "paper")),
                            confirmation=str(
                                payload.get("confirmation", "")
                            ),
                        ),
                    )
                    return
                if path == "/api/execution/confirm":
                    if execution_service is None:
                        raise RuntimeError(
                            "runtime_execution_unavailable"
                        )
                    payload = self._read_json()
                    self._json(
                        200,
                        execution_service.confirm_real(
                            str(payload["intent_id"]),
                            confirmation=str(
                                payload.get("confirmation", "")
                            ),
                        ),
                    )
                    return
                if path == "/api/execution/reject":
                    if execution_service is None:
                        raise RuntimeError(
                            "runtime_execution_unavailable"
                        )
                    payload = self._read_json()
                    self._json(
                        200,
                        execution_service.reject_real(
                            str(payload["intent_id"])
                        ),
                    )
                    return
                if path == "/api/chat":
                    if chat_service is None:
                        raise RuntimeError(
                            "company_chat_unavailable"
                        )
                    payload = self._read_json()
                    self._json(
                        200,
                        chat_service.ask(
                            str(payload.get("message", ""))
                        ),
                    )
                    return
                if path == "/api/chat/clear":
                    if chat_service is None:
                        raise RuntimeError(
                            "company_chat_unavailable"
                        )
                    self._json(200, chat_service.clear())
                    return
                if path.startswith("/api/settings/"):
                    if settings_service is None:
                        raise RuntimeError(
                            "runtime_settings_unavailable"
                        )
                    payload = self._read_json()
                    if path == "/api/settings/ollama/start":
                        self._json(
                            200,
                            settings_service.start_managed_ollama(),
                        )
                        return
                    if path == "/api/settings/ollama/stop":
                        self._json(
                            200,
                            settings_service.stop_managed_ollama(),
                        )
                        return
                    if path == "/api/settings/ollama/pick":
                        self._json(
                            200,
                            settings_service.pick_managed_ollama_model(),
                        )
                        return
                    if path == "/api/settings/ollama/import":
                        self._json(
                            200,
                            settings_service.import_managed_ollama_model(
                                source_path=str(
                                    payload.get(
                                        "source_path",
                                        "",
                                    )
                                ),
                                model_name=str(
                                    payload.get(
                                        "model_name",
                                        "",
                                    )
                                ),
                            ),
                        )
                        return
                    if path == "/api/settings/company/save":
                        self._json(
                            200,
                            settings_service.save_company_policy(
                                trader_initial_bucket=float(
                                    payload[
                                        "trader_initial_bucket"
                                    ]
                                ),
                                trader_stop_floor=float(
                                    payload[
                                        "trader_stop_floor"
                                    ]
                                ),
                                default_trader_max_exposure_pct=float(
                                    payload[
                                        "default_trader_max_exposure_pct"
                                    ]
                                ),
                                company_max_drawdown_pct=float(
                                    payload[
                                        "company_max_drawdown_pct"
                                    ]
                                ),
                            ),
                        )
                        return
                    if path == "/api/settings/llm/discover":
                        self._json(
                            200,
                            settings_service.discover_models(
                                provider=str(
                                    payload.get(
                                        "provider",
                                        "static",
                                    )
                                ),
                                base_url=str(
                                    payload.get(
                                        "base_url",
                                        "",
                                    )
                                ),
                                api_key=payload.get(
                                    "api_key"
                                ),
                            ),
                        )
                        return
                    if path == "/api/settings/llm/test":
                        self._json(
                            200,
                            settings_service.test_llm(
                                provider=str(
                                    payload.get(
                                        "provider",
                                        "static",
                                    )
                                ),
                                model=str(
                                    payload.get(
                                        "model",
                                        "",
                                    )
                                ),
                                base_url=str(
                                    payload.get(
                                        "base_url",
                                        "",
                                    )
                                ),
                                api_key=payload.get(
                                    "api_key"
                                ),
                            ),
                        )
                        return
                    if path == "/api/settings/llm/save":
                        self._json(
                            200,
                            settings_service.save_llm(
                                provider=str(
                                    payload.get(
                                        "provider",
                                        "static",
                                    )
                                ),
                                model=str(
                                    payload.get(
                                        "model",
                                        "",
                                    )
                                ),
                                base_url=str(
                                    payload.get(
                                        "base_url",
                                        "",
                                    )
                                ),
                                api_key=payload.get(
                                    "api_key"
                                ),
                                clear_api_key=bool(
                                    payload.get(
                                        "clear_api_key",
                                        False,
                                    )
                                ),
                            ),
                        )
                        return
                    if path == "/api/settings/news/save":
                        self._json(
                            200,
                            settings_service.save_news_sources(
                                payload.get("sources", [])
                            ),
                        )
                        return
                    if path == "/api/settings/news/discover":
                        self._json(
                            200,
                            settings_service.discover_news_feed(
                                str(payload.get("url", ""))
                            ),
                        )
                        return
                    if path == "/api/settings/news/test":
                        self._json(
                            200,
                            settings_service.test_news_source(
                                str(payload.get("url", ""))
                            ),
                        )
                        return
                    if path == "/api/settings/news/defaults":
                        self._json(
                            200,
                            settings_service.restore_default_news_sources(),
                        )
                        return
                    if path == "/api/settings/news/preview":
                        self._json(
                            200,
                            settings_service.preview_news(
                                limit=int(payload.get("limit", 20)),
                                query=payload.get("query"),
                            ),
                        )
                        return
                    if path == "/api/settings/brokers/save":
                        self._json(
                            200,
                            settings_service.save_broker_profile(
                                profile_id=payload.get(
                                    "profile_id"
                                ),
                                label=str(
                                    payload.get(
                                        "label",
                                        "",
                                    )
                                ),
                                provider=str(
                                    payload.get(
                                        "provider",
                                        "",
                                    )
                                ),
                                environment=str(
                                    payload.get(
                                        "environment",
                                        "",
                                    )
                                ),
                                api_key=payload.get(
                                    "api_key"
                                ),
                                api_secret=payload.get(
                                    "api_secret"
                                ),
                            ),
                        )
                        return
                    if path == "/api/settings/brokers/test":
                        self._json(
                            200,
                            settings_service.test_broker(
                                str(
                                    payload["profile_id"]
                                ),
                                api_key=payload.get(
                                    "api_key"
                                ),
                                api_secret=payload.get(
                                    "api_secret"
                                ),
                            ),
                        )
                        return
                    if path == "/api/settings/brokers/active":
                        self._json(
                            200,
                            settings_service.set_active_broker(
                                payload.get(
                                    "profile_id"
                                )
                            ),
                        )
                        return
                    if path == "/api/settings/brokers/delete":
                        self._json(
                            200,
                            settings_service.delete_broker_profile(
                                str(
                                    payload["profile_id"]
                                )
                            ),
                        )
                        return
                parts = [
                    unquote(part)
                    for part in path.split("/")
                    if part
                ]
                if (
                    len(parts) == 5
                    and parts[:3] == ["api", "company", "rollout"]
                ):
                    release_id = parts[3]
                    action = parts[4]
                    if action == "activate":
                        self._json(
                            200,
                            control.activate_strategy_release(
                                release_id
                            ),
                        )
                        return
                    if action == "rollback":
                        payload = self._read_json()
                        self._json(
                            200,
                            control.rollback_strategy_release(
                                release_id,
                                reason=str(
                                    payload.get(
                                        "reason",
                                        "manual_rollback",
                                    )
                                ),
                            ),
                        )
                        return
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
                    if action == "exposure":
                        payload = self._read_json()
                        self._json(
                            200,
                            control.configure_trader_exposure(
                                trader_id,
                                max_trade_exposure_pct=float(
                                    payload[
                                        "max_trade_exposure_pct"
                                    ]
                                ),
                                trade_exposure_pct=(
                                    float(
                                        payload[
                                            "trade_exposure_pct"
                                        ]
                                    )
                                    if payload.get(
                                        "trade_exposure_pct"
                                    )
                                    is not None
                                    else None
                                ),
                            ),
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
