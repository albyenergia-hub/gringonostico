"""Aggiorna nuovi_risultati.json con i risultati recenti (ATP e WTA, singolare) dal tabellone pubblico di ESPN.
Gira da solo su GitHub Actions. Servizio non ufficiale: puo' cambiare o fermarsi senza preavviso."""
import datetime as dt, json, sys, unicodedata
from pathlib import Path
import requests

QUI = Path(__file__).parent
DAL = "2026-10-20"          # primo giorno non presente in dati_app.json: aggiornalo quando riesporti i dati
HEAD = {"User-Agent": "gringonostico/1.0 (uso personale)"}
URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={d}"

TERRA = ["monte-carlo", "monte carlo", "madrid", "rome", "italian open", "roland", "french open", "barcelona", "estoril",
         "munich", "geneva", "lyon", "hamburg", "bastad", "gstaad", "umag", "kitzbuhel", "bucharest", "marrakech",
         "houston", "buenos aires", "rio", "santiago", "cordoba", "parma", "rabat", "strasbourg", "bogota", "charleston",
         "palermo", "prague", "lausanne", "warsaw", "budapest", "iasi", "cluj", "montreux", "valencia", "belgrade", "sao paulo"]
ERBA = ["wimbledon", "queen", "halle", "eastbourne", "mallorca", "stuttgart", "hertogenbosch", "newport", "berlin",
        "bad homburg", "birmingham", "nottingham", "surbiton", "ilkley", "libema"]


def norm(s):
    s = unicodedata.normalize("NFD", str(s).lower().replace("đ", "d").replace("ł", "l").replace("ø", "o"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("-", " ").replace(".", "").strip()


def superficie(nome):
    n = norm(nome)
    if any(k in n for k in ERBA):
        return "Grass"
    if any(k in n for k in TERRA):
        return "Clay"
    return "Hard"


dati = json.load(open(QUI / "dati_app.json"))
nomi = [g["n"] for g in dati["giocatori"]]
esatto = {norm(n): n for n in nomi}
per_sigla = {}
for n in nomi:
    p = norm(n).split()
    if len(p) >= 2:
        per_sigla.setdefault((p[-1], p[0][0]), []).append(n)


def risolvi(nome):
    n = norm(nome)
    if n in esatto:
        return esatto[n]
    p = n.split()
    if len(p) >= 2:
        c = per_sigla.get((p[-1], p[0][0]), [])
        if len(c) == 1:
            return c[0]
    return None


def punteggio(c1, c2):
    out = []
    for a, b in zip(c1.get("linescores", []), c2.get("linescores", [])):
        va, vb = int(a.get("value", 0)), int(b.get("value", 0))
        s = f"{va}-{vb}"
        tb = (a.get("tiebreak"), b.get("tiebreak"))
        if va == 7 and vb == 6 and tb[1] is not None:
            s += f"({int(tb[1])})"
        elif va == 6 and vb == 7 and tb[0] is not None:
            s += f"({int(tb[0])})"
        out.append(s)
    return " ".join(out)


file_out = QUI / "nuovi_risultati.json"
vecchie = []
if file_out.exists():
    try:
        vecchie = json.load(open(file_out)).get("partite", [])
    except Exception:
        vecchie = []
presenti = {str(m["id"]): m for m in vecchie}

oggi = dt.datetime.now(dt.timezone.utc).date()
inizio = dt.date.fromisoformat(DAL)
if vecchie:   # ripartiamo da pochi giorni prima dell'ultimo risultato noto
    ultimo = max(m["d"] for m in vecchie)
    inizio = max(inizio, dt.date.fromisoformat(ultimo) - dt.timedelta(days=3))

richieste_ok, nuove, saltati = 0, 0, {}
giorno = inizio
while giorno <= oggi:
    for tour in ("atp", "wta"):
        try:
            r = requests.get(URL.format(tour=tour, d=giorno.strftime("%Y%m%d")), headers=HEAD, timeout=25)
            if r.status_code != 200:
                print("HTTP", r.status_code, tour, giorno)
                continue
            j = r.json()
            richieste_ok += 1
        except Exception as e:
            print("Problema con", tour, giorno, type(e).__name__)
            continue
        for ev in j.get("events", []):
            for gr in ev.get("groupings", []):
                info = gr.get("grouping", {})
                if "double" in (str(info.get("slug", "")) + str(info.get("displayName", ""))).lower():
                    continue
                for c in gr.get("competitions", []):
                    st = c.get("status", {}).get("type", {})
                    if not st.get("completed") or st.get("name") not in ("STATUS_FINAL", "STATUS_RETIRED"):
                        continue
                    cid = str(c.get("id"))
                    giorno_m = str(c.get("date", ""))[:10]
                    if cid in presenti or giorno_m < DAL:
                        continue
                    cs = c.get("competitors", [])
                    vin = [x for x in cs if x.get("winner")]
                    if len(cs) != 2 or len(vin) != 1:
                        continue
                    w = vin[0]
                    l = cs[1] if cs[0] is w else cs[0]
                    nw = risolvi(w.get("athlete", {}).get("displayName", ""))
                    nl = risolvi(l.get("athlete", {}).get("displayName", ""))
                    if not nw or not nl:
                        continue
                    torneo = ev.get("name", "")
                    presenti[cid] = {"id": cid, "d": giorno_m, "w": nw, "l": nl, "s": superficie(torneo), "t": torneo,
                                     "r": c.get("round", {}).get("displayName", ""), "sc": punteggio(w, l)}
                    nuove += 1
    giorno += dt.timedelta(days=1)

if richieste_ok == 0:
    print("Nessuna risposta valida da ESPN: lascio il file com'e'.")
    sys.exit(1)

partite = sorted(presenti.values(), key=lambda m: (m["d"], str(m["id"])))
if partite != vecchie:
    with open(file_out, "w") as f:
        json.dump({"tipo": "live", "generato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "dal": DAL,
                   "partite": partite}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Aggiornato: {nuove} partite nuove, {len(partite)} in totale.")
else:
    print("Nessuna partita nuova.")
