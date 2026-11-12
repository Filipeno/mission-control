import json, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mc", "project")
os.makedirs(ROOT, exist_ok=True)

def ic(d, extra=""):
    return f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{d}{extra}</svg>'
I_HOME = ic('<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>')
I_AI = ic('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>')
I_DOC = ic('<path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6"/>')
I_SYS = ic('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>')
I_MIC = ic('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>')
I_SEND = ic('<path d="M4 12l16-8-6 16-2-7z"/>')
I_FP = ic('<path d="M12 11v3M8.5 8.5a5 5 0 0 1 8.5 3.5v2M7 12v1a8 8 0 0 0 1 4M12 7a5 5 0 0 0-5 5M16.5 17a10 10 0 0 0 .5-3M12 14a6 6 0 0 1-2 4.5M15 15.5a8 8 0 0 1-1.5 4"/>')
I_CAM = ic('<path d="M4 8h3l2-2h6l2 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>')
I_POWER = ic('<path d="M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0"/>')

FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">'

BASE = """
body{margin:0}
*{box-sizing:border-box}
p,h1,h2,h3{margin:0}
.app{width:390px;min-height:100vh;display:flex;flex-direction:column;font-family:Inter,system-ui,sans-serif}
.scroll{flex:1;display:flex;flex-direction:column}
.top{display:flex;justify-content:space-between;align-items:flex-end}
.row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.btnrow{display:flex;gap:8px;margin-top:14px}
.btn{font:inherit;font-weight:600;font-size:15px;min-height:44px;padding:0 16px;display:inline-flex;align-items:center;justify-content:center;gap:8px;cursor:pointer;text-decoration:none}
.btn.grow{flex:1}
.iconbtn{width:44px;height:44px;padding:0}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
.bar{height:6px;border-radius:99px;overflow:hidden}
.bar>span{display:block;height:100%;border-radius:99px}
.list{list-style:none;margin:0;padding:0}
.list li{display:flex;gap:12px;align-items:center;padding:12px 0}
.dot{width:10px;height:10px;border-radius:50%;flex:none}
.tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:8px 8px 14px}
.tabs a{display:flex;flex-direction:column;align-items:center;gap:4px;font-size:12px;font-weight:500;text-decoration:none;min-height:48px;justify-content:center;border-radius:12px}
.seg{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));padding:4px}
.seg button{font:inherit;font-size:14px;font-weight:600;min-height:40px;border:0;cursor:pointer}
.choice{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
.choice button{font:inherit;font-size:13px;font-weight:600;min-height:44px;cursor:pointer}
.thumbs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}
.thumb{height:96px;display:flex;align-items:flex-end;padding:8px;font-size:12px;font-weight:600}
.compose{display:flex;gap:8px;align-items:center}
.compose input{flex:1;font:inherit;font-size:15px;min-height:44px;padding:0 14px}
.shot{height:150px;display:flex;align-items:center;justify-content:center;font-size:13px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
"""

DARK = BASE + """
.app{background:#0B0E14;color:#E6EAF2}
.scroll{padding:22px 16px 16px;gap:12px}
h1{font-family:'Space Grotesk',sans-serif;font-size:28px;font-weight:600;letter-spacing:-.01em}
h2{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9AA4B5;margin:8px 2px 0}
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#4CC2FF;margin-bottom:2px}
.card,.tile{background:#141922;border:1px solid #232B38;border-radius:16px;padding:16px}
.grid2{gap:12px}
.tile{padding:14px}
.label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9AA4B5}
.big{font-family:'Space Grotesk',sans-serif;font-size:30px;font-weight:600;margin-top:4px}
.val{font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:600;margin-top:6px}
.sub,.muted{font-size:13px;color:#9AA4B5;margin-top:2px}
.mono{font-family:'JetBrains Mono',monospace;font-weight:500}
.chip{font-size:12px;font-weight:600;padding:5px 10px;border-radius:99px;background:#1C2330;color:#C9D2E0;white-space:nowrap}
.chip.ok{background:#12291F;color:#5FE3AA}
.chip.warn{background:#2E2412;color:#FFC56B}
.chip.info{background:#0F2433;color:#7FD3FF}
.btn{background:#1C2330;border:1px solid #2A3342;color:#E6EAF2;border-radius:12px}
.btn.primary{background:#4CC2FF;border-color:#4CC2FF;color:#04121C}
.btn.danger{color:#FF8A8A}
.bar{background:#232B38}.bar>span{background:#4CC2FF}.bar>span.hot{background:#FFB547}
.list li+li{border-top:1px solid #1E2531}
.dot.work{background:#4CC2FF;box-shadow:0 0 0 4px rgba(76,194,255,.15)}.dot.wait{background:#FFB547}.dot.idle{background:#5B6476}.dot.limit{background:#FF6B6B}.dot.off{background:#5B6476}.dot.on{background:#3DDC97}
.tabs{background:#0F131B;border-top:1px solid #1E2531}
.tabs a{color:#8C96A8}.tabs a[aria-current=page]{color:#4CC2FF;background:#13202C}
.link{display:flex;justify-content:space-between;align-items:center;text-decoration:none;color:inherit}
.count{font-family:'Space Grotesk',sans-serif;font-size:28px;font-weight:700;color:#FFC56B}
.tag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#7FD3FF}
.seg{background:#141922;border:1px solid #232B38;border-radius:12px}.seg button{background:transparent;color:#9AA4B5;border-radius:9px}.seg button[aria-pressed=true]{background:#1F2937;color:#E6EAF2}
.choice button{background:#1C2330;border:1px solid #2A3342;color:#C9D2E0;border-radius:10px}
.choice button[aria-pressed=true].pass{background:#12291F;border-color:#3DDC97;color:#5FE3AA}
.choice button[aria-pressed=true].fail{background:#2E1616;border-color:#FF6B6B;color:#FF9C9C}
.thumb{border-radius:12px;border:1px solid #2A3342}
.thumb.a{background:#0B0E14;color:#7FD3FF}.thumb.b{background:#F7F7F5;color:#1A1A1A}
.compose input{background:#141922;border:1px solid #2A3342;border-radius:12px;color:#E6EAF2}
.compose input::placeholder{color:#8C96A8}
.shot{background:#0F131B;border:1px dashed #2A3342;border-radius:12px;color:#8C96A8;margin-top:12px}
.note{background:#1C2330;border-radius:10px;padding:10px 12px;font-size:13px;color:#C9D2E0;margin-top:10px}
.ok{color:#5FE3AA}.warnt{color:#FFC56B}
.check{padding:14px 0}.check+.check{border-top:1px solid #1E2531}
.home-bg{background:#151A26}
"""

CLEAN = BASE + """
.app{background:#F7F7F5;color:#1A1A1A}
.scroll{padding:28px 20px 20px;gap:16px}
h1{font-size:34px;font-weight:700;letter-spacing:-.025em}
h2{font-size:15px;font-weight:600;color:#1A1A1A;margin:10px 4px -4px}
.eyebrow{font-size:13px;font-weight:500;color:#5C5C5C;margin-bottom:2px}
.card{background:#FFFFFF;border:1px solid #E8E6E1;border-radius:20px;padding:20px}
.grid2{grid-template-columns:1fr;background:#FFFFFF;border:1px solid #E8E6E1;border-radius:20px;padding:4px 20px}
.tile{display:flex;align-items:center;gap:8px;padding:14px 0}
.tile+.tile{border-top:1px solid #EFEDE8}
.tile .label{flex:1;font-size:15px;font-weight:500;color:#1A1A1A}
.tile .val{font-size:15px;font-weight:600}
.tile .sub{display:none}
.label{font-size:14px;font-weight:500;color:#5C5C5C}
.big{font-size:30px;font-weight:700;letter-spacing:-.02em;margin-top:2px}
.val{font-size:17px;font-weight:600}
.sub,.muted{font-size:14px;color:#5C5C5C;margin-top:2px}
.mono{font-variant-numeric:tabular-nums}
.chip{font-size:13px;font-weight:500;padding:6px 12px;border-radius:99px;background:#EFEDE8;color:#3D3D3D;white-space:nowrap}
.chip.ok{background:#E5F2EA;color:#1F6B3F}
.chip.warn{background:#FBEEDC;color:#8A4B08}
.chip.info{background:#E6ECF8;color:#234A9E}
.btn{background:#EFEDE8;border:0;color:#1A1A1A;border-radius:99px}
.btn.primary{background:#1A1A1A;color:#FFFFFF}
.btn.danger{color:#A12A2A}
.bar{background:#ECEAE5}.bar>span{background:#1A1A1A}.bar>span.hot{background:#B5590B}
.list li+li{border-top:1px solid #EFEDE8}
.dot.work{background:#2B59C3}.dot.wait{background:#D9822B}.dot.idle{background:#B9B6AE}.dot.limit{background:#C2412D}.dot.off{background:#B9B6AE}.dot.on{background:#2F8F5B}
.tabs{background:#FFFFFF;border-top:1px solid #E8E6E1}
.tabs a{color:#6B6B6B}.tabs a[aria-current=page]{color:#1A1A1A;font-weight:700}
.link{display:flex;justify-content:space-between;align-items:center;text-decoration:none;color:inherit}
.count{font-size:28px;font-weight:700;color:#1A1A1A}
.tag{font-size:13px;font-weight:500;color:#5C5C5C}
.seg{background:#EFEDE8;border-radius:99px}.seg button{background:transparent;color:#5C5C5C;border-radius:99px}.seg button[aria-pressed=true]{background:#FFFFFF;color:#1A1A1A;box-shadow:0 1px 2px rgba(0,0,0,.08)}
.choice button{background:#FFFFFF;border:1px solid #E0DDD6;color:#3D3D3D;border-radius:99px}
.choice button[aria-pressed=true].pass{background:#1F6B3F;border-color:#1F6B3F;color:#FFFFFF}
.choice button[aria-pressed=true].fail{background:#A12A2A;border-color:#A12A2A;color:#FFFFFF}
.thumb{border-radius:14px;border:1px solid #E0DDD6}
.thumb.a{background:#0B0E14;color:#7FD3FF}.thumb.b{background:#F7F7F5;color:#1A1A1A}
.compose input{background:#FFFFFF;border:1px solid #E0DDD6;border-radius:99px;color:#1A1A1A}
.compose input::placeholder{color:#6B6B6B}
.shot{background:#F1EFEA;border-radius:14px;color:#5C5C5C;margin-top:14px}
.note{background:#F4F2EE;border-radius:12px;padding:10px 12px;font-size:14px;color:#3D3D3D;margin-top:10px}
.ok{color:#1F6B3F}.warnt{color:#8A4B08}
.check{padding:16px 0}.check+.check{border-top:1px solid #EFEDE8}
.home-bg{background:#E6E3DC}
"""

def tabs(p, active):
    items = [("home", "Home", I_HOME), ("claude", "Claude", I_AI), ("docs", "Docs", I_DOC), ("system", "System", I_SYS)]
    out = []
    for key, label, icon in items:
        href = fname(p, key)
        cur = ' aria-current="page"' if key == active else ""
        out.append(f'<a href="{href}"{cur}>{icon}<span>{label}</span></a>')
    return '<nav class="tabs" aria-label="Main tabs">' + "".join(out) + "</nav>"

def fname(p, key):
    if p == "dark" and key == "home":
        return "Main.dc.html"
    return f"{p}-{key}.dc.html"

def top(title, chip, chipcls="ok"):
    return f'<header class="top"><div><p class="eyebrow">Mission Control</p><h1>{title}</h1></div><span class="chip {chipcls}">{chip}</span></header>'

def home(p):
    return top("Home", "Home Wi-Fi") + f"""
<section class="card" aria-label="Gaming PC">
  <div class="row"><div><p class="label">Gaming PC</p><p class="big">Asleep</p><p class="muted">Since 01:12 · auto-sleep after 30 min idle</p></div><span class="dot off" aria-hidden="true"></span></div>
  <div class="btnrow"><button class="btn primary grow" type="button">{I_POWER}Wake PC</button><button class="btn" type="button">Sleep</button></div>
</section>
<div class="grid2">
  <div class="tile"><p class="label">Room</p><p class="val">Empty</p><p class="sub">Presence sensor</p></div>
  <div class="tile"><p class="label">Lights</p><p class="val">Off</p><p class="sub">Tap to turn on</p></div>
  <div class="tile"><p class="label">Auto-sleep</p><p class="val">On</p><p class="sub">30 min idle</p></div>
  <div class="tile"><p class="label">Pi</p><p class="val ok">Healthy</p><p class="sub mono">41 °C · up 12 d</p></div>
</div>
<a class="card link" href="{fname(p,'claude')}"><div><p class="label">Waiting for you</p><p class="muted">1 commit · 1 design pick · 1 question</p></div><span class="count mono">3</span></a>
<section class="card" aria-label="Checklist progress">
  <div class="row"><p class="label">Slime Keepers phone test</p><p class="mono">12 / 20</p></div>
  <div class="bar" style="margin-top:12px"><span style="width:60%"></span></div>
</section>
<h2>Recent</h2>
<ul class="list">
  <li><span class="dot work" aria-hidden="true"></span><div style="flex:1"><p>factory-machines-flow finished a turn</p><p class="muted mono">07:52</p></div></li>
  <li><span class="dot wait" aria-hidden="true"></span><div style="flex:1"><p>goo-pass-season is waiting for you</p><p class="muted mono">07:49</p></div></li>
  <li><span class="dot idle" aria-hidden="true"></span><div style="flex:1"><p>PC went to sleep (no one in the room)</p><p class="muted mono">01:12</p></div></li>
</ul>
"""

def claude(p):
    return top("Claude", "2 working", "info") + f"""
<h2>Approvals · 3</h2>
<section class="card" aria-label="Commit approval">
  <p class="tag">Commit</p>
  <p class="val" style="margin-top:6px">Commit Candy Kitchen props to v2</p>
  <p class="muted">factory-machines-flow · 4 files · picture attached</p>
  <div class="btnrow"><button class="btn primary grow" type="button">{I_FP}Approve</button><button class="btn danger" type="button">Reject</button><button class="btn" type="button">Reply</button></div>
</section>
<section class="card" aria-label="Design pick">
  <p class="tag">Design pick</p>
  <p class="val" style="margin-top:6px">Mission Control: which style?</p>
  <div class="thumbs"><button class="thumb a" type="button">A · Dark dashboard</button><button class="thumb b" type="button">B · Clean minimal</button></div>
</section>
<section class="card" aria-label="Question">
  <p class="tag">Question</p>
  <p class="val" style="margin-top:6px">Show Slime Factory Tycoon stats until 2.0 is live?</p>
  <div class="choice" style="margin-top:12px"><button type="button">Yes</button><button type="button">No</button><button type="button">Reply</button></div>
</section>
<h2>Sessions</h2>
<ul class="list">
  <li><span class="dot work" aria-hidden="true"></span><p style="flex:1">factory-machines-flow</p><span class="chip info">Working</span></li>
  <li><span class="dot wait" aria-hidden="true"></span><p style="flex:1">goo-pass-season</p><span class="chip warn">Needs you</span></li>
  <li><span class="dot limit" aria-hidden="true"></span><p style="flex:1">Codex</p><span class="chip">Limit · back 20 Nov</span></li>
  <li><span class="dot idle" aria-hidden="true"></span><p style="flex:1">Gemini</p><span class="chip">Idle</span></li>
</ul>
<h2>Usage</h2>
<section class="card" aria-label="AI usage">
  <div class="row"><p>Claude · 5 hours</p><p class="mono">23% · resets 10:09</p></div>
  <div class="bar" style="margin:8px 0 14px"><span style="width:23%"></span></div>
  <div class="row"><p>Claude · week</p><p class="mono warnt">92% · resets 00:00</p></div>
  <div class="bar" style="margin:8px 0 14px"><span class="hot" style="width:92%"></span></div>
  <div class="row"><p>Codex</p><p class="mono">resets 20 Nov</p></div>
  <div class="row" style="margin-top:8px"><p>Gemini</p><p class="mono">daily reset 09:00</p></div>
</section>
<form class="compose" onsubmit="return false"><label class="sr" for="idea-{p}">Idea for Claude</label><input id="idea-{p}" placeholder="Send an idea to Claude…"><button class="btn iconbtn" type="button" aria-label="Record voice">{I_MIC}</button><button class="btn primary iconbtn" type="submit" aria-label="Send">{I_SEND}</button></form>
"""

def docs(p):
    def chk(n, title, state, extra=""):
        pas = ' aria-pressed="true"' if state == "pass" else ' aria-pressed="false"'
        fai = ' aria-pressed="true"' if state == "fail" else ' aria-pressed="false"'
        return f"""<div class="check"><div class="row"><p><span class="mono muted">{n}</span>&nbsp; {title}</p></div>
<div class="choice" style="margin-top:10px"><button class="pass" type="button"{pas}>Pass</button><button class="fail" type="button"{fai}>Fail</button><button type="button" aria-pressed="false">Skip</button></div>{extra}</div>"""
    fail_extra = f'<p class="note">Buy buttons cut off at the bottom on a small phone.</p><div class="btnrow" style="margin-top:10px"><button class="btn" type="button">{I_CAM}1 screenshot</button><button class="btn" type="button">2 comments</button></div>'
    return top("Docs", "On the Pi") + f"""
<div class="seg" role="group" aria-label="View"><button type="button" aria-pressed="true">Checklists</button><button type="button" aria-pressed="false">Docs</button></div>
<section class="card" aria-label="Checklist">
  <p class="label">Slime Keepers phone test · test place v30</p>
  <div class="row" style="margin-top:8px"><p class="val">12 of 20 done</p><span class="chip warn">2 failed</span></div>
  <div class="bar" style="margin:12px 0 4px"><span style="width:60%"></span></div>
  {chk(13, "Tutorial egg hatches on first join", "pass")}
  {chk(14, "Shop opens on a small phone", "fail", fail_extra)}
  {chk(15, "Goo Pass panel scrolls smoothly", None)}
  {chk(16, "Teleport Hub → Beach keeps your slimes", None)}
</section>
<h2>Docs</h2>
<ul class="list">
  <li>{I_DOC}<div style="flex:1"><p>Mission Control PLAN.md</p><p class="muted">Edited by Claude · 2 h ago</p></div></li>
  <li>{I_DOC}<div style="flex:1"><p>Feel and retention pass</p><p class="muted">3 open comments</p></div></li>
</ul>
"""

def system(p):
    def svc(name, state, cls="ok"):
        return f'<li><span class="dot {"on" if cls=="ok" else "wait"}" aria-hidden="true"></span><p style="flex:1">{name}</p><p class="mono {cls if cls!="ok" else "ok"}">{state}</p></li>'
    return top("System", "All OK") + f"""
<section class="card" aria-label="Gaming PC">
  <div class="row"><p class="label">Gaming PC</p><button class="btn" type="button">{I_CAM}New screenshot</button></div>
  <div class="shot">Last screenshot · 01:10</div>
  <div class="row" style="margin-top:12px"><p class="muted">CPU <span class="mono">—</span> · GPU <span class="mono">—</span></p><p class="muted">Asleep, no live temps</p></div>
</section>
<div class="grid2">
  <div class="tile"><p class="label">Raspberry Pi</p><p class="val mono">41 °C</p><p class="sub">Disk 62% · up 12 d</p></div>
  <div class="tile"><p class="label">Mini PC</p><p class="val ok">Healthy</p><p class="sub">Home Assistant up 24 d</p></div>
</div>
<h2>Services</h2>
<ul class="list">
  {svc("Vaultwarden backup", "6 h ago")}
  {svc("Cloudflare tunnel", "Up")}
  {svc("bp-gateway", "Up")}
  {svc("pc-waker", "Up")}
</ul>
<section class="card" aria-label="Roblox">
  <div class="row"><p class="label">Roblox · Slime Factory Tycoon</p><span class="chip">Until 2.0 is live</span></div>
  <div class="row" style="margin-top:10px"><div><p class="val mono">[live]</p><p class="sub">Playing now</p></div><div><p class="val mono">[visits]</p><p class="sub">Visits today</p></div><div><p class="val mono">[fav]</p><p class="sub">Favorites</p></div></div>
</section>
<h2>Timeline</h2>
<ul class="list">
  <li><p class="mono muted">07:52</p><p style="flex:1">Claude session finished a turn</p></li>
  <li><p class="mono muted">03:00</p><p style="flex:1">Vaultwarden backup saved</p></li>
  <li><p class="mono muted">01:12</p><p style="flex:1">PC slept (room empty 30 min)</p></li>
</ul>
"""

def widget(p):
    return f"""<div class="home-bg" style="min-height:844px;padding:56px 16px;display:flex;flex-direction:column;gap:24px">
<p class="label">Phone home screen</p>
<section class="card" aria-label="Mission Control widget, large" style="border-radius:24px">
  <div class="row"><p class="eyebrow" style="margin:0">Mission Control</p><span class="chip ok">Home</span></div>
  <div class="row" style="margin-top:12px"><div><p class="label">PC</p><p class="big" style="font-size:24px">Asleep</p></div><button class="btn primary" type="button">{I_POWER}Wake</button></div>
  <div class="grid2" style="margin-top:12px">
    <div class="tile"><p class="label">Claude</p><p class="val">2 working</p><p class="sub">3 need you</p></div>
    <div class="tile"><p class="label">Checklist</p><p class="val mono">12/20</p><p class="sub">2 failed</p></div>
  </div>
</section>
<div style="display:flex;gap:16px">
<section class="card" aria-label="Mission Control widget, small" style="width:170px;height:170px;border-radius:24px;display:flex;flex-direction:column;justify-content:space-between">
  <div><p class="label">PC</p><p class="val">Asleep</p></div>
  <button class="btn primary" type="button">{I_POWER}Wake</button>
</section>
<section class="card" aria-label="Approvals widget, small" style="width:170px;height:170px;border-radius:24px;display:flex;flex-direction:column;justify-content:space-between">
  <div><p class="label">Approvals</p><p class="count mono">3</p></div>
  <p class="muted">Open Claude tab</p>
</section>
</div>
</div>"""

SCREENS = [("home", "Home", home), ("claude", "Claude", claude), ("docs", "Docs & Checklists", docs), ("system", "System", system), ("widget", "Widget", widget)]
STYLES = [("dark", "Dark dashboard", DARK), ("clean", "Clean minimal", CLEAN)]

def page(p, key, title, body, css):
    if key == "widget":
        inner = f'<div class="app">{body}</div>'
    else:
        inner = f'<div class="app"><main class="scroll">{body}</main>{tabs(p, key)}</div>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} · {dict((s[0], s[1]) for s in STYLES)[p]}</title>
<script src="./support.js"></script>
{FONTS}
</head>
<body>
<x-dc>
<helmet>
{FONTS}
<style>{css}</style>
</helmet>
{inner}
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{}}'>
class Component extends DCLogic {{
  renderVals() {{ return {{}}; }}
}}
</script>
</body>
</html>
"""

boards, order = {}, []
H = {"home": 1000, "claude": 1480, "docs": 1300, "system": 1200, "widget": 844}
ROW_Y = {"dark": 0, "clean": 1480 + 120 + 300}
notes = {
    "t-dark": {"x": 0, "y": -300, "text": "A · Dark dashboard", "kind": "title1", "maxW": 2270},
    "t-clean": {"x": 0, "y": ROW_Y["clean"] - 300, "text": "B · Clean minimal", "kind": "title1", "maxW": 2270},
    "n-sample": {"x": 2430, "y": 0, "text": "Sample data. Session names and usage are real from 9 Nov 08:00; temps, counts and Roblox numbers are placeholders. No IPs, MACs or email anywhere. Tabs at the bottom link the screens: press Play to click through.", "w": 300, "fill": "yellow" if False else "gray"},
}
for p, pname, css in STYLES:
    for i, (key, title, fn) in enumerate(SCREENS):
        f = fname(p, key)
        with open(os.path.join(ROOT, f), "w", encoding="utf-8") as fh:
            fh.write(page(p, key, title, fn(p), css))
        boards[f] = {"x": i * (390 + 80), "y": ROW_Y[p], "w": 390, "h": H[key], "title": f"{pname} · {title}", "is_interactive": key != "widget"}
        order.append(f)

canvas = {"v": 3, "createdOnFiles": {"v": 1, "at": "2026-11-09T08:15:00Z"}, "title": "Mission Control mockups",
          "launch": {"view": "canvas"}, "pages": [], "boards": boards, "order": order, "notes": notes, "designSystems": []}
with open(os.path.join(ROOT, "canvas.json"), "w", encoding="utf-8") as fh:
    json.dump(canvas, fh, indent=1)
print("\n".join(sorted(os.listdir(ROOT))))
