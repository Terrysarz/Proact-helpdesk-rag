"""
Web-UI voor de Service Desk Assistant (Flask).

    python src/app.py
    -> open http://127.0.0.1:5000  (of http://<VM-IP>:5000 vanaf je laptop)

De pagina toont een chat; elk antwoord komt met de gebruikte bronnen en de
similarity-scores, zodat je in de demo kunt laten zien dat het antwoord echt
uit je documenten komt (en niet verzonnen is).
"""

from __future__ import annotations
from flask import Flask, request, jsonify, render_template_string

from rag import answer

app = Flask(__name__)

PAGE = """
<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proact Service Desk Assistant</title>
<style>
  :root { --bg:#0f1720; --panel:#17212b; --accent:#2e9e5b; --text:#e8eef3; --muted:#8aa0b2; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background:var(--bg); color:var(--text); height:100vh; display:flex; flex-direction:column; }
  header { padding:16px 20px; background:var(--panel); border-bottom:1px solid #223; }
  header h1 { margin:0; font-size:18px; }
  header p { margin:4px 0 0; font-size:12px; color:var(--muted); }
  #chat { flex:1; overflow-y:auto; padding:20px; display:flex; flex-direction:column; gap:14px; }
  .msg { max-width:760px; padding:12px 16px; border-radius:12px; line-height:1.5; white-space:pre-wrap; }
  .user { align-self:flex-end; background:var(--accent); color:#fff; }
  .bot  { align-self:flex-start; background:var(--panel); border:1px solid #223; }
  .sources { margin-top:8px; font-size:12px; color:var(--muted); }
  form { display:flex; gap:10px; padding:16px 20px; background:var(--panel); border-top:1px solid #223; }
  input { flex:1; padding:12px 14px; border-radius:10px; border:1px solid #2a3a48;
          background:#0c141c; color:var(--text); font-size:15px; }
  button { padding:12px 20px; border:0; border-radius:10px; background:var(--accent);
           color:#fff; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:wait; }
</style>
</head>
<body>
  <header>
    <h1>Proact Service Desk Assistant</h1>
    <p>Lokale RAG-chatbot &middot; antwoorden komen uit de interne kennisbank &middot; 100% on-prem</p>
  </header>
  <div id="chat">
    <div class="msg bot">Hoi! Stel een vraag over wachtwoorden, MFA, VPN, licenties, printers of onboarding.</div>
  </div>
  <form id="form">
    <input id="q" autocomplete="off" placeholder="Typ je vraag..." required>
    <button id="send" type="submit">Verstuur</button>
  </form>

<script>
const chat = document.getElementById('chat');
const form = document.getElementById('form');
const input = document.getElementById('q');
const sendBtn = document.getElementById('send');

function addMessage(text, cls, sources) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  div.textContent = text;
  if (sources && sources.length) {
    const s = document.createElement('div');
    s.className = 'sources';
    s.textContent = 'Bronnen: ' + sources.join(', ');
    div.appendChild(s);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;
  addMessage(q, 'user');
  input.value = '';
  sendBtn.disabled = true;
  const thinking = addMessage('Aan het nadenken...', 'bot');
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q})
    });
    const data = await res.json();
    thinking.remove();
    addMessage(data.answer, 'bot', data.sources);
  } catch (err) {
    thinking.remove();
    addMessage('Er ging iets mis: ' + err, 'bot');
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
});
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(PAGE)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    question = (data or {}).get("question", "").strip()
    if not question:
        return jsonify({"answer": "Stel eerst een vraag.", "sources": []})
    result = answer(question)
    return jsonify({"answer": result["answer"], "sources": result["sources"]})


if __name__ == "__main__":
    # host=0.0.0.0 zodat je de UI ook vanaf je laptop kunt openen op het VM-IP.
    app.run(host="0.0.0.0", port=5000, debug=False)
