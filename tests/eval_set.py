"""
Kleine evaluatieset voor de Proact Service Desk Assistant.

Draait de dispatcher (rag.prepare) met een nep-sessie en vervangt de acties door stubs,
dus er wordt niets in Active Directory, per mail of in data/ gewijzigd. Het taalmodel in
LM Studio wordt wel echt gebruikt (routering, ja/nee lezen, verwoording).

Gebruik:  python tests/eval_set.py
"""
import os, sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
for k in ("AD_SERVER", "AD_URI", "AD_HOST"):
    os.environ.pop(k, None)

import actions, rag, responder, router   # noqa: E402

actions.create_ticket = lambda **kw: {"id": "PRO-99999", "subject": kw.get("subject", ""),
    "naam": kw.get("naam", ""), "bedrijf": kw.get("bedrijf", ""),
    "telefoon": kw.get("telefoon", ""), "status": "Nieuw"}
actions.send_ticket_email = lambda *a, **k: {"sent": False}
actions.request_password_reset = lambda ident: {"found": True, "method": "ad", "unlocked": False,
    "sent": True, "email_masked": "l•••@proact.nl", "simulated": False, "valid_minutes": 30}

AUTH = {"sam": "ljansen", "name": "Lisa Jansen", "first": "Lisa", "company": "Proact", "mail": "l@x.nl"}
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))

def new(): return {"auth": dict(AUTH), "history": []}

def say(s, msg):
    plan = rag.prepare(msg, s)
    text = plan.get("text") or plan.get("user_prompt", "")
    rag.remember(s, "user", msg); rag.remember(s, "assistant", text)
    return plan

# 1. Routering: bericht -> verwachte soort antwoord
for msg, kind in [("hoi", "greeting"), ("goedemorgen", "greeting"),
                  ("ik ben mijn wachtwoord vergeten", "reset_ask"),
                  ("ik wil mijn wachtwoord aanpassen", "reset_ask"),
                  ("hoe wijzig ik mijn wachtwoord", "answer"),
                  ("kun je mijn wachtwoord resetten", "reset_ask"),
                  ("ik wil geen wachtwoord reset", None),
                  ("hoe stel ik MFA in", "answer"),
                  ("outlook start niet op", "answer"),
                  ("maak een ticket aan", "ticket"),
                  ("wat is de hoofdstad van Frankrijk", "notfound")]:
    s = new(); p = say(s, msg)
    if kind is None:
        check(f"route '{msg}' is geen reset", p["kind"] != "reset", p["kind"])
    else:
        check(f"route '{msg}' -> {kind}", p["kind"] == kind, p["kind"])

# 2. Voornaam en afwisseling
s = new(); a = say(s, "hoi")["text"]; b = say(s, "hoi")["text"]
check("begroeting noemt Lisa", "Lisa" in a, a)
check("tweede 'hoi' herhaalt niet", a != b and "welkom" not in b.lower(), b)
check("spiegelt goedemiddag", "Goedemiddag" in say(new(), "goedemiddag")["text"])

# 3. Antwoorden lezen (C)
for msg, want in [("ja", "yes"), ("jazeker, doe maar", "yes"), ("nee laat maar", "no"),
                  ("liever niet, bedankt", "no"), ("pas aan", "adjust"),
                  ("hoe laat is het", "other")]:
    s = new(); s["history"] = [{"role": "assistant", "content": "Wil je dat ik een ticket aanmaak? (ja / nee)"}]
    got = rag._reply_kind(s, msg, msg.lower())
    check(f"antwoord '{msg}' -> {want}", got == want, got)

# 4. Ticketflow met bevestiging
s = new(); say(s, "ik krijg geen verbinding met de vpn")
p = say(s, "maak een ticket aan"); check("ticket vraagt bevestiging", s.get("ticket_confirm") is True, p["text"])
p = say(s, "ja, graag"); check("bevestiging gaat door", "telefoon" in p["text"].lower(), p["text"])
p = say(s, "06-12345678"); check("ticket aangemaakt", "PRO-99999" in p["text"], p["text"])

# 5. Verwoording (B): feiten moeten kloppen, anders valt het terug
t0 = time.time(); p = rag._do_reset("ljansen", new()); dt = time.time() - t0
check("reset noemt gemaskeerd adres", "l•••@proact.nl" in p["text"], p["text"])
check("reset zegt nooit het wachtwoord", "nooit in de chat" in p["text"])
print(f"     reset antwoord ({dt:.1f}s): {p['text']!r}")
src = "Ik heb een ticket aangemaakt: **PRO-00017**"
check("validatie wijst verzonnen zin af", responder.check(src, src + ". U kunt het ticket volgen op het portaal.") is not None)
check("validatie wijst ontbrekend ticketnummer af", responder.check(src, "Het ticket is aangemaakt, je hoort snel iets.") is not None)
check("validatie accepteert goede zin", responder.check(src, "Gelukt, je ticket is aangemaakt: **PRO-00017**") is None)
check("validatie wijst nieuw getal af", responder.check(src, "Gelukt: **PRO-00017**, binnen 4 uur reactie.") is not None)

# 6. Onderwerp en correcties bij tickets, telefoon, maskering
HIST = [{"role": "user", "content": "kun je mijn wachtwoord resetten"},
        {"role": "assistant", "content": "Je account is ontgrendeld. Een tijdelijk wachtwoord is gemaild."}]
s = new(); s["history"] = list(HIST)
p = say(s, "kan een ticket gemaakt worden voor een onedrive probleem")
check("eigen onderwerp wint van het gesprek", "onedrive" in p["text"].lower() and "wachtwoord" not in p["text"].lower(), p["text"])
s = new(); s["history"] = list(HIST)
say(s, "maak een ticket aan")
p = say(s, "nee dat klopt niet ik zei maak een onedrive ticket")
subj = (s.get("ticket") or {}).get("onderwerp", "")
check("correctie wordt het onderwerp", "onedrive" in subj.lower() and "klopt" not in subj.lower(), subj)
check("correctie wordt opnieuw bevestigd", s.get("ticket_confirm") is True, p["text"])
say(s, "ja"); p = say(s, "06 44")
check("te kort telefoonnummer wordt geweigerd", "8 cijfers" in p["text"], p["text"])
p = say(s, "06-12345678"); check("geldig nummer maakt ticket", "PRO-99999" in p["text"], p["text"])
check("maskering zonder sterretjes", "*" not in actions.mask_email("jan@gmail.com"), actions.mask_email("jan@gmail.com"))
src2 = "Je account is ontgrendeld. Er is een wachtwoord gemaild naar **j•••@gmail.com**."
check("validatie wijst backticks af", responder.check(src2, "Account ontgrendeld, mail naar `j•••@gmail.com`.", must=("ontgrendeld",)) is not None)
check("validatie eist 'ontgrendeld'", responder.check(src2, "Je account is vrijgegeven, mail naar **j•••@gmail.com**.", must=("ontgrendeld",)) is not None)

# 7. Wachtwoord vergeten, verwijzingen naar het gesprek, links
s = new(); p = say(s, "ik ben mijn wachtwoord vergeten")
check("vergeten vraagt eerst bevestiging", s.get("pending") == "reset_confirm", p["text"])
p = say(s, "ja doe maar"); check("ja start de reset", p["kind"] == "reset_ask" and "account" in p["text"].lower(), p["text"])
s = new(); say(s, "ik ben mijn wachtwoord vergeten"); p = say(s, "nee laat maar")
check("nee laat het wachtwoord met rust", p["kind"] == "info", p["text"])
H2 = [{"role": "user", "content": "hoe reset ik mijn wachtwoord"},
      {"role": "assistant", "content": "Ga naar aka.ms/sspr en volg de stappen. Wil je dat ik het nu voor je doe? (ja / nee)"}]
for msg in ["kan jij het voor me veranderen en mailen naar me", "ik wil dat jij dit voor me doet"]:
    s = new(); s["history"] = list(H2); p = say(s, msg)
    check(f"verwijzing '{msg}' -> reset", s.get("pending") == "reset_confirm", p["text"][:80])
H3 = [{"role": "user", "content": "outlook start niet op"},
      {"role": "assistant", "content": "Start Outlook op in veilige modus en probeer opnieuw."}]
s = new(); s["history"] = list(H3); p = say(s, "kun je uitleggen hoe ik teams installeer")
check("uitlegvraag blijft kennisvraag", p["mode"] == "rag", p["kind"])
s = new(); p = say(s, "hoe stel ik mijn wachtwoord opnieuw in")
check("wachtwoord-uitleg biedt de reset aan", p.get("mode") == "rag" and "ja / nee" in p.get("followup", ""), str(p.get("followup")))
hits = [{"score": .703, "source": "02-outlook.md"}, {"score": .694, "source": "01-wachtwoord-en-mfa.md"}]
check("twijfelachtige link wordt weggelaten", rag._confident_links(hits) == [])
hits = [{"score": .72, "source": "01-wachtwoord-en-mfa.md"}, {"score": .64, "source": "05-vpn.md"}]
check("duidelijke hit geeft een link", len(rag._confident_links(hits)) >= 1)

# 8. Relevantie: vragen buiten IT worden afgevangen, echte vragen niet
for msg, want in [("wat is het weer morgen", "notfound"), ("hoe bak ik een pannenkoek", "notfound"),
                  ("vertel een grap", "notfound"), ("mijn printer print niet", "answer"),
                  ("onedrive synchroniseert niet", "answer"), ("wifi verbinding valt steeds weg", "answer"),
                  ("ik krijg geen mail in outlook", "answer"), ("hoe verbind ik met de vpn", "answer")]:
    s = new(); p = say(s, msg)
    check(f"relevantie '{msg}' -> {want}", p["kind"] == want, p["kind"])

# 9. Typfouten, ruis, bedankt en buiten IT
s = new(); p = say(s, "hellop"); check("typfout in groet is een groet", p["kind"] == "greeting", p["kind"] + ": " + p["text"])
for msg in [".", "?", "!!"]:
    s = new(); p = say(s, msg); check(f"ruis '{msg}' geeft geen ticketaanbod", p["kind"] == "info" and "ticket" not in p["text"].lower(), p["text"])
s = new(); p = say(s, "bedankt"); check("bedankt wordt beantwoord", p["kind"] == "info" and "ticket" not in p["text"].lower(), p["text"])
s = new(); p = say(s, "doei"); check("doei wordt beantwoord", p["kind"] == "info", p["text"])
s = new(); p = say(s, "wat is het weer morgen")
check("buiten IT: geen ticketaanbod", p["kind"] == "notfound" and "ticket" not in p["text"].lower() and s.get("pending") != "offer_ticket", p["text"])
s = new(); p = say(s, "ik heb een rare foutcode 0x80070005 bij het updaten van mijn laptop")
print("     (info) foutcode-vraag ->", p["kind"], "|", (p.get("text") or "")[:70])
check("normale woorden zijn geen groet", not router.is_greeting("heeft hij het"), "")

print(f"\n{sum(results)}/{len(results)} geslaagd")
sys.exit(0 if all(results) else 1)
