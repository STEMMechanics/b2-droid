"""Password-protected local web chat, diagnostics, Wi-Fi, and data export."""
import base64, hmac, json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGE = b'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>B2</title><style>body{font:16px system-ui;background:#101820;color:#eee;margin:0}h1{color:#ffca28}.layout{display:grid;grid-template-columns:190px 1fr;min-height:100vh}aside{background:#17232d;padding:18px;position:sticky;top:0;height:100vh;box-sizing:border-box}aside button{display:block;width:100%;margin:7px 0;text-align:left}main{max-width:950px;padding:20px}.panel{display:none}.panel.active{display:block}.card{background:#1d2a35;border-radius:12px;padding:16px;margin:14px 0}input,select,button{padding:10px;margin:3px}input[type=range]{width:min(420px,80%)}pre{white-space:pre-wrap;max-height:55vh;overflow:auto}.me{color:#8bd3ff}.b2{color:#ffca28}.llm-route{border:1px solid #40505d;border-radius:8px;padding:8px;margin:8px 0}.llm-route input{max-width:210px}@media(max-width:650px){.layout{grid-template-columns:1fr}aside{height:auto;position:static}aside button{display:inline-block;width:auto}}</style></head><body><div class="layout"><aside><h1>B2</h1><button onclick="show('vision')">Vision</button><button onclick="show('chatPanel')">Chat</button><button onclick="show('logs')">Logs</button><button onclick="show('memoryPanel')">People & memory</button><button onclick="show('audioPanel');audioSettings()">Audio</button><button onclick="show('configPanel');configSettings()">Settings</button><button onclick="show('llmPanel');llmRoutes()">AI Connections</button><button onclick="show('wifi')">Wi-Fi</button></aside><main>
<section id="vision" class="panel active"><div class="card"><h2>What B2 sees &mdash; <span id="stateBadge">connecting</span></h2><img id="camera" alt="Live B2 camera" style="width:100%;max-height:520px;object-fit:contain;background:#000"><pre id="status"></pre></div></section>
<section id="logs" class="panel"><div class="card"><h2>Running activity and chat log</h2><button onclick="location.href='/api/logs'">Download combined log</button><select id="sessions"></select><button onclick="downloadSession()">Download session</button><label><input id="followLogs" type="checkbox" checked> Follow newest entries</label><pre id="liveLog"></pre></div></section>
<section id="chatPanel" class="panel"><div class="card"><h2>Chat</h2><div id="chat"></div><form id="cf"><input id="msg" maxlength="500"><button>Send</button></form></div></section>
<section id="memoryPanel" class="panel"><div class="card"><h2>People, memories and reminders</h2><button onclick="memory()">Refresh</button><pre id="mem"></pre></div></section>
<section id="audioPanel" class="panel"><div class="card"><h2>Voice volume</h2><form id="af"><label>Base volume: <output id="volumeValue">65</output>%</label><br><input id="volume" type="range" min="0" max="100" value="65" oninput="$('#volumeValue').value=this.value"><br><label><input id="automaticVolume" type="checkbox" checked> Automatically raise volume as background noise increases</label><br><button>Apply volume</button></form><pre id="audioStatus"></pre></div><div class="card"><h2>Audio devices</h2><p>Saving devices restarts B2. The dashboard should reconnect within a few seconds.</p><form id="deviceForm"><label>Microphone<br><select id="captureDevice"></select></label><br><label>Speaker<br><select id="playbackDevice"></select></label><br><label>Minimum speech level <input id="speechThreshold" type="number" min="20" max="5000"></label><br><button>Save devices and restart</button></form><button onclick="audioDevices()">Rescan devices</button><pre id="deviceStatus"></pre></div></section>
<section id="configPanel" class="panel"><div class="card"><h2>Safe runtime configuration</h2><p>Only operational settings are shown; passwords and tokens are never exposed. Saving restarts B2.</p><form id="configForm"><label>Camera <input id="cameraDevice" placeholder="/dev/video0"></label><br><label>Motor startup PWM <input id="motorFloor" type="number" min="0" max="255"></label><br><label>Motor maximum PWM <input id="motorMax" type="number" min="0" max="255"></label><br><label>Stall cooldown seconds <input id="stallCooldown" type="number" min="1" max="600"></label><br><button>Save configuration and restart</button></form><pre id="configStatus"></pre></div></section>
<section id="llmPanel" class="panel"><div class="card"><h2>Language model connections</h2><p>Lower priority numbers run first. Failed or timed-out connections fall through to the next enabled connection. API keys are write-only.</p><div id="llmRoutes"></div><button onclick="addLlmRoute()">Add connection</button><button onclick="saveLlmRoutes()">Save priority</button><pre id="llmStatus"></pre></div></section>
<section id="wifi" class="panel"><div class="card"><h2>Wi-Fi</h2><button onclick="scan()">Scan</button><form id="wf"><select id="ssid"></select><input id="pass" type="password" placeholder="Password"><button>Connect</button></form><pre id="wr"></pre></div></section></main></div>
<script>const $=s=>document.querySelector(s),esc=s=>{let d=document.createElement('div');d.textContent=s;return d.innerHTML};function show(id){document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active')}async function status(){let r=await fetch('/api/status'),j=await r.json();$('#stateBadge').textContent=j.state||'unknown';$('#status').textContent=JSON.stringify(j,null,2)}async function live(){let r=await fetch('/api/logs/tail');if(r.ok){let p=$('#liveLog'),nearBottom=p.scrollHeight-p.scrollTop-p.clientHeight<40,follow=$('#followLogs').checked&&(nearBottom||!p.textContent);p.textContent=await r.text();if(follow)p.scrollTop=p.scrollHeight}$('#camera').src='/api/camera.jpg?t='+Date.now()}async function sessions(){let s=$('#sessions'),selected=s.value,r=await fetch('/api/sessions'),j=await r.json(),names=j.sessions||[];s.innerHTML=names.map(x=>`<option>${esc(x)}</option>`).join('');if(names.includes(selected))s.value=selected}function downloadSession(){let n=$('#sessions').value;if(n)location.href='/api/session?name='+encodeURIComponent(n)}async function memory(){let r=await fetch('/api/memory');$('#mem').textContent=JSON.stringify(await r.json(),null,2)}async function audioSettings(){let r=await fetch('/api/audio'),j=await r.json();$('#volume').value=j.volume;$('#volumeValue').value=j.volume;$('#automaticVolume').checked=!!j.automatic;$('#audioStatus').textContent=JSON.stringify(j,null,2);await audioDevices()}function deviceOptions(items,current,recommended){return (items||[]).map(x=>`<option value="${esc(x.device)}" ${(x.device===current||x.numeric_device===current)?'selected':''}>${esc(x.label)}${x.device===recommended?' (recommended)':''}</option>`).join('')}async function audioDevices(){let [dr,cr]=await Promise.all([fetch('/api/audio/devices'),fetch('/api/config')]),d=await dr.json(),c=await cr.json(),s=c.settings||{};$('#captureDevice').innerHTML=deviceOptions(d.capture,s.B2_AUDIO_DEVICE,d.recommended_capture);$('#playbackDevice').innerHTML=deviceOptions(d.playback,s.B2_OUTPUT_DEVICE,d.recommended_playback);$('#speechThreshold').value=s.B2_MIN_SPEECH_THRESHOLD||100;$('#deviceStatus').textContent=JSON.stringify({recommended_capture:d.recommended_capture,recommended_playback:d.recommended_playback,last_result:c.last_result},null,2)}async function scan(){let r=await fetch('/api/wifi'),j=await r.json();$('#ssid').innerHTML=(j.networks||[]).map(x=>`<option>${esc(x)}</option>`).join('');$('#wr').textContent=j.error||''}$('#followLogs').onchange=e=>{if(e.target.checked){let p=$('#liveLog');p.scrollTop=p.scrollHeight}};$('#cf').onsubmit=async e=>{e.preventDefault();let t=$('#msg').value.trim();if(!t)return;$('#msg').value='';$('#chat').innerHTML+=`<p class="me">You: ${esc(t)}</p>`;let r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})}),j=await r.json();$('#chat').innerHTML+=`<p class="b2">B2: ${esc(j.reply||j.error||'No reply')}</p>`};$('#af').onsubmit=async e=>{e.preventDefault();let r=await fetch('/api/audio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({volume:Number($('#volume').value),automatic:$('#automaticVolume').checked})}),j=await r.json();$('#audioStatus').textContent=JSON.stringify(j,null,2)};$('#deviceForm').onsubmit=async e=>{e.preventDefault();let settings={B2_AUDIO_DEVICE:$('#captureDevice').value,B2_OUTPUT_DEVICE:$('#playbackDevice').value,B2_MIN_SPEECH_THRESHOLD:Number($('#speechThreshold').value)},r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings})}),j=await r.json();$('#deviceStatus').textContent=JSON.stringify(j,null,2)};$('#wf').onsubmit=async e=>{e.preventDefault();let r=await fetch('/api/wifi',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:$('#ssid').value,password:$('#pass').value})});$('#pass').value='';$('#wr').textContent=JSON.stringify(await r.json(),null,2)};status();live();sessions();memory();audioSettings();scan();setInterval(status,500);setInterval(live,1000);setInterval(sessions,10000)</script></body></html>'''

PAGE = PAGE.replace(b"</body>", b'''<script>
async function configSettings(){
  let r=await fetch('/api/config'),j=await r.json(),s=j.settings||{};
  $('#cameraDevice').value=s.B2_CAMERA||'/dev/video0';
  $('#motorFloor').value=s.B2_MOTOR_STARTUP_FLOOR;
  $('#motorMax').value=s.B2_MOTOR_SPEED_MAX;
  $('#stallCooldown').value=s.B2_MOTOR_STALL_COOLDOWN;
  $('#configStatus').textContent=JSON.stringify(j.last_result||{},null,2);
}
$('#configForm').onsubmit=async e=>{
  e.preventDefault();
  let settings={B2_CAMERA:$('#cameraDevice').value,
    B2_MOTOR_STARTUP_FLOOR:Number($('#motorFloor').value),
    B2_MOTOR_SPEED_MAX:Number($('#motorMax').value),
    B2_MOTOR_STALL_COOLDOWN:Number($('#stallCooldown').value)};
  let r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings})});
  $('#configStatus').textContent=JSON.stringify(await r.json(),null,2);
};
let llmConnections=[];
function renderLlmRoutes(){
  $('#llmRoutes').innerHTML=llmConnections.map((r,i)=>`<div class="llm-route">
    <label>Enabled <input data-k="enabled" data-i="${i}" type="checkbox" ${r.enabled?'checked':''}></label>
    <label>Priority <input data-k="priority" data-i="${i}" type="number" min="0" max="999" value="${Number(r.priority)}"></label><br>
    <label>ID <input data-k="id" data-i="${i}" value="${esc(r.id||'')}"></label>
    <label>Label <input data-k="label" data-i="${i}" value="${esc(r.label||'')}"></label><br>
    <label>LiteLLM model <input data-k="model" data-i="${i}" value="${esc(r.model||'')}" placeholder="openai/gpt-5"></label>
    <label>API base <input data-k="api_base" data-i="${i}" value="${esc(r.api_base||'')}" placeholder="https://api.openai.com/v1"></label><br>
    <label>API key <input data-k="api_key" data-i="${i}" type="password" placeholder="${r.has_api_key?'stored; leave blank to keep':'required'}"></label>
    <label>Timeout <input data-k="timeout" data-i="${i}" type="number" min="2" max="120" value="${Number(r.timeout||30)}"></label>
    <button onclick="llmConnections.splice(${i},1);renderLlmRoutes()">Remove</button></div>`).join('');
  document.querySelectorAll('#llmRoutes input').forEach(x=>x.onchange=()=>{
    let r=llmConnections[Number(x.dataset.i)],k=x.dataset.k;
    r[k]=x.type==='checkbox'?x.checked:(x.type==='number'?Number(x.value):x.value);
  });
}
async function llmRoutes(){let r=await fetch('/api/llm/routes'),j=await r.json();llmConnections=j.connections||[];renderLlmRoutes();$('#llmStatus').textContent='Default fallback: '+(j.default||'local-ai')}
function addLlmRoute(){llmConnections.push({id:'external-ai',label:'External AI',model:'openai/gpt-5',api_base:'https://api.openai.com/v1',enabled:true,priority:10,timeout:20,has_api_key:false});renderLlmRoutes()}
async function saveLlmRoutes(){let r=await fetch('/api/llm/routes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({connections:llmConnections})}),j=await r.json();if(r.ok){llmConnections=j.connections||[];renderLlmRoutes()}$('#llmStatus').textContent=JSON.stringify(j,null,2)}
</script></body>''')


def _session_sort_key(path):
    try:
        date, number = path.stem.rsplit("-", 1)
        return date, int(number)
    except (ValueError, TypeError):
        return "", -1

def start_web(on_message, get_status, get_memory, wifi_scan, wifi_connect, get_camera, get_audio, set_audio, get_devices, get_config, set_config, get_llm_routes=None, set_llm_routes=None):
    password=os.environ.get("B2_WEB_PASSWORD")
    if not password: print("Web dashboard disabled: B2_WEB_PASSWORD is not set."); return None
    username=os.environ.get("B2_WEB_USERNAME","admin"); host=os.environ.get("B2_WEB_HOST","0.0.0.0"); port=int(os.environ.get("B2_WEB_PORT","8088")); log_file=os.environ.get("B2_LOG_FILE","/var/log/b2-droid/app.log"); log_dir=Path(os.environ.get("B2_LOG_DIR","/var/log/b2-droid"))
    class Handler(BaseHTTPRequestHandler):
        def auth(self):
            try:
                scheme,value=self.headers.get("Authorization","").split(" ",1); user,supplied=base64.b64decode(value).decode().split(":",1)
                return scheme.lower()=="basic" and hmac.compare_digest(user,username) and hmac.compare_digest(supplied,password)
            except (ValueError,UnicodeError): return False
        def send(self,code,body,content="application/json",attachment=None):
            self.send_response(code); self.send_header("Content-Type",content); self.send_header("Cache-Control","no-store")
            if attachment:self.send_header("Content-Disposition",f'attachment; filename="{attachment}"')
            self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        def allowed(self):
            if self.auth():return True
            self.send_response(401); self.send_header("WWW-Authenticate",'Basic realm="B2 adult dashboard"'); self.send_header("Content-Length","0"); self.end_headers(); return False
        def payload(self):return json.loads(self.rfile.read(min(int(self.headers.get("Content-Length","0")),4096)))
        def do_GET(self):
            if not self.allowed():return
            try:
                if self.path=="/":return self.send(200,PAGE,"text/html; charset=utf-8")
                if self.path=="/api/status":data=get_status()
                elif self.path=="/api/memory":data=get_memory()
                elif self.path=="/api/audio":data=get_audio()
                elif self.path=="/api/audio/devices":data=get_devices()
                elif self.path=="/api/config":data=get_config()
                elif self.path=="/api/llm/routes" and get_llm_routes:data=get_llm_routes()
                elif self.path=="/api/wifi":data={"networks":wifi_scan()}
                elif self.path.startswith("/api/camera.jpg"):
                    body=get_camera()
                    if body is None:return self.send(503,b"Camera frame unavailable","text/plain")
                    return self.send(200,body,"image/jpeg")
                elif self.path=="/api/logs/tail":
                    try:
                        with open(log_file,"rb") as f:
                            f.seek(0,2); size=f.tell(); f.seek(max(0,size-65536)); body=f.read()
                    except OSError as e:body=f"Log unavailable: {e}\n".encode()
                    return self.send(200,body,"text/plain; charset=utf-8")
                elif self.path=="/api/sessions":
                    data={"sessions":[p.name for p in sorted(log_dir.glob("????-??-??-*.log"),key=_session_sort_key,reverse=True)]}
                elif self.path.startswith("/api/session?"):
                    name=parse_qs(urlparse(self.path).query).get("name",[""])[0]
                    candidate=log_dir/name
                    if not name or Path(name).name!=name or not candidate.is_file():return self.send(404,b'{"error":"session not found"}')
                    return self.send(200,candidate.read_bytes(),"text/plain; charset=utf-8",name)
                elif self.path=="/api/logs":
                    try:
                        with open(log_file,"rb") as f:body=f.read()[-2_000_000:]
                    except OSError as e:body=f"Log unavailable: {e}\n".encode()
                    return self.send(200,body,"text/plain; charset=utf-8","b2-diagnostics.log")
                else:return self.send(404,b'{"error":"not found"}')
                self.send(200,json.dumps(data).encode())
            except Exception as e:self.send(500,json.dumps({"error":str(e)}).encode())
        def do_POST(self):
            if not self.allowed():return
            try:
                data=self.payload()
                if self.path=="/api/chat":result={"reply":on_message(str(data.get("message",""))[:500])}
                elif self.path=="/api/wifi":result=wifi_connect(str(data.get("ssid",""))[:128],str(data.get("password",""))[:256])
                elif self.path=="/api/audio":result=set_audio(data.get("volume",65),data.get("automatic",True))
                elif self.path=="/api/config":result=set_config(data.get("settings",{}))
                elif self.path=="/api/llm/routes" and set_llm_routes:result=set_llm_routes(data)
                else:return self.send(404,b'{"error":"not found"}')
                self.send(200,json.dumps(result).encode())
            except Exception as e:self.send(400,json.dumps({"error":str(e)}).encode())
        def log_message(self,format,*args):return
    server=ThreadingHTTPServer((host,port),Handler); threading.Thread(target=server.serve_forever,daemon=True).start(); print(f"Web dashboard listening on {host}:{port}."); return server
