"""
Web-UI voor de Proact Service Desk Assistant v3 (Flask + streaming).

    python src/app.py   ->   http://127.0.0.1:5000  (of http://<VM-IP>:5000)

v3: strakkere (Claude-achtige) interface + gespreksgeheugen.
"""

from __future__ import annotations
import json

from flask import Flask, request, Response, render_template_string, stream_with_context, jsonify

from rag import prepare, remember
from lmclient import ask_llm_stream
import config
import ad

app = Flask(__name__)
SESSIONS: dict[str, dict] = {}


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.route("/")
def home():
    return render_template_string(PAGE)


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    session_id = (data.get("session_id") or "default").strip()
    session = SESSIONS.setdefault(session_id, {})

    if not ad.enabled():
        return jsonify({"ok": False, "error": "Inloggen is niet beschikbaar (AD niet geconfigureerd)."})
    try:
        user = ad.authenticate(username, password)
    except Exception:
        return jsonify({"ok": False, "error": "Kan de AD-server niet bereiken."})
    if not user:
        return jsonify({"ok": False, "error": "Onjuiste gebruikersnaam of wachtwoord."})

    is_agent = (user.get("sam", "").lower() in config.AD_AGENTS)
    session["auth"] = {
        "sam": user.get("sam", ""), "name": user.get("name", ""),
        "company": user.get("company", ""), "mail": user.get("mail", ""),
        "is_agent": is_agent,
    }
    return jsonify({"ok": True, "name": user.get("name") or user.get("sam"), "agent": is_agent})


@app.route("/logout", methods=["POST"])
def logout():
    data = request.get_json(force=True, silent=True) or {}
    s = SESSIONS.get((data.get("session_id") or "default").strip())
    if s:
        s.pop("auth", None)
    return jsonify({"ok": True})


@app.route("/me", methods=["POST"])
def me():
    data = request.get_json(force=True, silent=True) or {}
    s = SESSIONS.get((data.get("session_id") or "default").strip(), {})
    a = s.get("auth")
    if a:
        return jsonify({"loggedin": True, "name": a.get("name") or a.get("sam"), "agent": a.get("is_agent")})
    return jsonify({"loggedin": False, "login_available": ad.enabled()})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("question") or "").strip()
    session_id = (data.get("session_id") or "default").strip()
    session = SESSIONS.setdefault(session_id, {})

    def generate():
        if not question:
            yield sse({"type": "message", "kind": "info", "text": "Stel eerst een vraag."})
            yield sse({"type": "done"})
            return

        try:
            plan = prepare(question, session)
        except FileNotFoundError:
            yield sse({"type": "error", "text": "De kennisbank is nog niet geïndexeerd. "
                                                "Draai eerst 'python src/ingest.py'."})
            yield sse({"type": "done"})
            return
        except Exception:
            yield sse({"type": "error", "text": "Ik kan de kennisbank nu niet bereiken. "
                                                "Staat de LM Studio-server aan (Running)?"})
            yield sse({"type": "done"})
            return

        reply_text = ""
        if plan["mode"] == "direct":
            reply_text = plan["text"]
            yield sse({"type": "message", "kind": plan["kind"], "text": plan["text"]})
        else:
            yield sse({"type": "start"})
            got_any = False
            try:
                for piece in ask_llm_stream(plan["user_prompt"]):
                    got_any = True
                    reply_text += piece
                    yield sse({"type": "token", "text": piece})
            except Exception:
                if not got_any:
                    yield sse({"type": "error", "text": "Het model gaf geen antwoord. "
                                                        "Is het antwoordmodel geladen in LM Studio?"})
                    yield sse({"type": "done"})
                    return
            # Interne bronbestanden (bv. 02-outlook.md) tonen we NIET aan de klant.
            # De nette, publieke 'Meer info'-link hieronder blijft wel staan.
            if plan.get("links"):
                yield sse({"type": "links", "links": plan["links"]})

        # Gespreksgeheugen bijwerken.
        if reply_text:
            remember(session, "user", question)
            remember(session, "assistant", reply_text)
        yield sse({"type": "done"})

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=headers)


PAGE = r"""
<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proact Service Desk Assistant</title>
<style>
  :root{
    --bg:#f7f6f1; --surface:#ffffff; --text:#2a2926; --muted:#6b6760;
    --line:#e7e3da; --user:#edeae1; --accent:#c96442; --accent-ink:#fff;
    --card:#fbfaf6; --green:#2e9e5b; --blue:#2f6fed; --amber:#c8871f;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#262624; --surface:#2f2e2b; --text:#ece9e2; --muted:#a39e94;
           --line:#3c3a36; --user:#3a3834; --card:#302f2c; }
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0; background:var(--bg); color:var(--text);
       font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       display:flex; flex-direction:column; height:100vh;}
  header{padding:14px 20px; border-bottom:1px solid var(--line); text-align:center;}
  header h1{margin:0; font-size:15px; font-weight:600; letter-spacing:.01em;}
  header p{margin:2px 0 0; font-size:12px; color:var(--muted);}
  #scroll{flex:1; overflow-y:auto;}
  #chat{max-width:760px; margin:0 auto; padding:26px 20px 10px; display:flex; flex-direction:column; gap:20px;}
  .row{display:flex; flex-direction:column;}
  .row.me{align-items:flex-end;}
  .bubble{max-width:90%; line-height:1.6; white-space:pre-wrap; word-wrap:break-word;}
  .me .bubble{background:var(--user); padding:11px 15px; border-radius:16px 16px 4px 16px;}
  .bot .bubble{padding:2px 0;}
  .bot.card .bubble{background:var(--card); border:1px solid var(--line); border-left:3px solid var(--muted);
                    padding:12px 15px; border-radius:10px;}
  .bot.ticket .bubble{border-left-color:var(--green);}
  .bot.reset  .bubble, .bot.reset_ask .bubble{border-left-color:var(--blue);}
  .bot.notfound .bubble, .bot.error .bubble{border-left-color:var(--amber);}
  .who{font-size:11px; color:var(--muted); margin-bottom:4px; letter-spacing:.03em;}
  .sources{margin-top:10px; font-size:12px; color:var(--muted);}
  .typing span{display:inline-block; width:6px; height:6px; margin-right:3px; border-radius:50%;
               background:var(--muted); animation:blink 1.2s infinite both;}
  .typing span:nth-child(2){animation-delay:.2s} .typing span:nth-child(3){animation-delay:.4s}
  @keyframes blink{0%,80%,100%{opacity:.25} 40%{opacity:1}}
  footer{border-top:1px solid var(--line); background:var(--bg);}
  .composer{max-width:760px; margin:0 auto; padding:14px 20px 8px; display:flex; gap:10px; align-items:flex-end;}
  .inputwrap{flex:1; background:var(--surface); border:1px solid var(--line); border-radius:16px;
             padding:6px 8px 6px 14px; display:flex; align-items:center; box-shadow:0 1px 2px rgba(0,0,0,.04);}
  textarea{flex:1; border:0; outline:0; resize:none; background:transparent; color:var(--text);
           font:inherit; font-size:15px; max-height:140px; padding:6px 0;}
  .send{border:0; border-radius:12px; background:var(--accent); color:var(--accent-ink);
        width:38px; height:38px; font-size:17px; cursor:pointer; flex:none;}
  .send:disabled{opacity:.45; cursor:wait;}
  .hint{max-width:760px; margin:0 auto; padding:0 20px 12px; font-size:11px; color:var(--muted); text-align:center;}
  strong{font-weight:650;}
  .links{margin-top:8px; font-size:13px;}
  a{color:var(--accent); text-decoration:none;}
  a:hover{text-decoration:underline;}
  #authbar{max-width:760px; margin:0 auto; padding:8px 20px; display:flex; justify-content:flex-end;
           gap:8px; align-items:center; font-size:13px; color:var(--muted); border-bottom:1px solid var(--line);}
  #authbar form{display:flex; gap:8px; align-items:center;}
  #authbar input{padding:6px 10px; border-radius:8px; border:1px solid var(--line);
                 background:var(--surface); color:var(--text); font-size:13px; width:140px;}
  #authbar button{padding:6px 12px; border:0; border-radius:8px; background:var(--accent);
                  color:#fff; cursor:pointer; font-size:13px;}
  #loginmsg{color:#c8871f;}
  .agentbadge{background:var(--user); border-radius:10px; padding:1px 8px; font-size:11px;}
</style>
</head>
<body>
  <header>
    <h1>Proact Service Desk Assistant</h1>
    <p>Lokale RAG-chatbot · antwoorden uit de interne kennisbank · 100% on-prem</p>
  </header>
  <div id="authbar" style="display:none">
    <form id="loginform">
      <input id="u" placeholder="gebruikersnaam" autocomplete="username">
      <input id="p" type="password" placeholder="wachtwoord" autocomplete="current-password">
      <button type="submit">Inloggen</button>
      <span id="loginmsg"></span>
    </form>
    <div id="loggedin" style="display:none">
      Ingelogd als <strong id="whoami"></strong> <span id="agentbadge"></span>
      · <a href="#" id="logout">uitloggen</a>
    </div>
  </div>
  <div id="scroll"><div id="chat">
    <div class="row bot"><div class="who">Assistent</div>
      <div class="bubble">Hoi! Vraag me iets over wachtwoorden, MFA, VPN, licenties, printers of onboarding — of laat me een wachtwoordreset starten of een ticket aanmaken.</div>
    </div>
  </div></div>
  <footer>
    <div class="composer">
      <div class="inputwrap">
        <textarea id="q" rows="1" placeholder="Typ je bericht…"></textarea>
      </div>
      <button class="send" id="send" title="Verstuur">➤</button>
    </div>
    <div class="hint">Probeer: &ldquo;Hoe reset ik mijn wachtwoord?&rdquo; · &ldquo;Reset mijn wachtwoord&rdquo; · &ldquo;Maak een ticket voor een kapotte printer&rdquo;</div>
  </footer>

<script>
const scroll = document.getElementById('scroll');
const chat = document.getElementById('chat');
const input = document.getElementById('q');
const sendBtn = document.getElementById('send');

let sessionId = localStorage.getItem('sd_session');
if (!sessionId){ sessionId = 'sess-' + Math.random().toString(36).slice(2); localStorage.setItem('sd_session', sessionId); }

function esc(s){ return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function fmt(t){
  let h = esc(t).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  // markdown [tekst](url) -> één link (voorkomt dubbele weergave)
  h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  // losse URL die nog niet in een link zit
  h = h.replace(/(^|[^"'>=])(https?:\/\/[^\s<]+)/g,'$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  return h;
}
function toBottom(){ scroll.scrollTop = scroll.scrollHeight; }

function addRow(who, cls){
  const row = document.createElement('div');
  row.className = 'row ' + (who==='me'?'me':'bot') + (cls?(' '+cls):'');
  const label = document.createElement('div'); label.className='who';
  label.textContent = who==='me' ? 'Jij' : 'Assistent';
  const bubble = document.createElement('div'); bubble.className='bubble';
  row.appendChild(label); row.appendChild(bubble);
  chat.appendChild(row); toBottom();
  return {row, bubble};
}

function autoresize(){ input.style.height='auto'; input.style.height=Math.min(input.scrollHeight,140)+'px'; }
input.addEventListener('input', autoresize);
input.addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); submit(); }});
sendBtn.addEventListener('click', submit);

async function submit(){
  const q = input.value.trim();
  if(!q) return;
  addRow('me').bubble.textContent = q;
  input.value=''; autoresize(); sendBtn.disabled=true;

  const {row, bubble} = addRow('bot');
  bubble.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
  let acc=''; let firstToken=false;
  const render = ()=>{ bubble.innerHTML=fmt(acc); toBottom(); };

  try{
    const res = await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:q, session_id:sessionId})});
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf='';
    while(true){
      const {value,done} = await reader.read(); if(done) break;
      buf += dec.decode(value,{stream:true});
      const parts = buf.split('\n\n'); buf = parts.pop();
      for(const part of parts){
        const line = part.replace(/^data: /,'').trim(); if(!line) continue;
        const ev = JSON.parse(line);
        if(ev.type==='start'){ /* bolletjes blijven staan tot het eerste woord */ }
        else if(ev.type==='token'){
          if(!firstToken){ bubble.innerHTML=''; firstToken=true; }
          acc+=ev.text; render();
        }
        else if(ev.type==='message'){
          acc=ev.text;
          const k=ev.kind;
          if(['ticket','reset','reset_ask','notfound','error','info'].includes(k)){
            row.className='row bot card '+k;
          }
          render();
        }
        else if(ev.type==='links'){
          const b=document.createElement('div'); b.className='links';
          b.innerHTML='Meer info: '+ev.links.map(l=>'<a href="'+l.url+'" target="_blank" rel="noopener">'+l.label+'</a>').join(' · ');
          bubble.appendChild(b); toBottom();
        }
        else if(ev.type==='error'){ row.className='row bot card error'; acc=ev.text; render(); }
      }
    }
    if(!acc) bubble.textContent='(geen antwoord ontvangen)';
  }catch(err){ row.className='row bot card error'; bubble.textContent='Verbindingsfout: '+err; }
  finally{ sendBtn.disabled=false; input.focus(); }
}

// ---- Login (optioneel, via Active Directory) ----
const authbar=document.getElementById('authbar');
const loginform=document.getElementById('loginform');
const loggedin=document.getElementById('loggedin');
const loginmsg=document.getElementById('loginmsg');

async function post(url, body){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(Object.assign({session_id:sessionId}, body||{}))});
  return r.json();
}
function showLoggedIn(name, agent){
  loginform.style.display='none'; loggedin.style.display='block';
  document.getElementById('whoami').textContent=name;
  document.getElementById('agentbadge').innerHTML = agent ? '<span class="agentbadge">agent</span>' : '';
  authbar.style.display='flex';
}
function showLoginForm(){
  loggedin.style.display='none'; loginform.style.display='flex'; authbar.style.display='flex';
}
async function refreshAuth(){
  const d=await post('/me');
  if(d.loggedin){ showLoggedIn(d.name, d.agent); }
  else if(d.login_available){ showLoginForm(); }
  else { authbar.style.display='none'; }   // AD niet geconfigureerd -> geen inlogbalk
}
loginform.addEventListener('submit', async (e)=>{
  e.preventDefault(); loginmsg.textContent='';
  const u=document.getElementById('u').value.trim();
  const p=document.getElementById('p').value;
  const d=await post('/login',{username:u, password:p});
  if(d.ok){ document.getElementById('p').value=''; showLoggedIn(d.name, d.agent); }
  else { loginmsg.textContent = d.error || 'Inloggen mislukt'; }
});
document.getElementById('logout').addEventListener('click', async (e)=>{
  e.preventDefault(); await post('/logout'); showLoginForm();
});
refreshAuth();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
