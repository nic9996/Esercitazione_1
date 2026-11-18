"""Interfaccia web per il motore di prenotazione.

Avvio:  python server.py
Poi aprire nel browser l'indirizzo stampato nel terminale.

Il server usa solo la libreria standard. Riceve le richieste dal browser,
chiama i metodi del motore (prenotazioni.py) e compone la pagina HTML a partire
dal modello modelli/pagina.html, sostituendo i segnaposto $nome.
Dopo ogni modifica a prenotazioni.py il server va fermato (Ctrl+C) e riavviato.
"""

import html
import json
import os
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from string import Template
from urllib.parse import parse_qs, urlencode, urlparse

import prenotazioni as motore

CARTELLA = os.path.dirname(os.path.abspath(__file__))
FILE_DATI = os.path.join(CARTELLA, "dati", "registro.json")
FILE_INIZIALI = os.path.join(CARTELLA, "dati", "barche_iniziali.json")
FILE_MODELLO = os.path.join(CARTELLA, "modelli", "pagina.html")
FILE_STILE = os.path.join(CARTELLA, "static", "stile.css")
INDIRIZZO = "127.0.0.1"
PORTA = 8000

NOMI_GIORNI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
NOMI_MESI = [
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
]

esc = html.escape


class MotoreIncompleto(Exception):
    """Una funzione indispensabile del motore non è ancora implementata."""


# ---------------------------------------------------------------------------
# Preparazione del registro
# ---------------------------------------------------------------------------


def prepara_registro():
    """Carica il registro dal file dati o lo crea con le barche iniziali."""
    if os.path.exists(FILE_DATI):
        return motore.Registro.carica(FILE_DATI)
    registro = motore.Registro()
    with open(FILE_INIZIALI, encoding="utf-8") as f:
        for dati_barca in json.load(f):
            registro.aggiungi_barca(motore.Barca.from_dict(dati_barca))
    registro.salva(FILE_DATI)
    return registro


# ---------------------------------------------------------------------------
# Funzioni di composizione HTML
# ---------------------------------------------------------------------------


def data_estesa(giorno):
    return f"{giorno.day} {NOMI_MESI[giorno.month - 1]} {giorno.year}"


def durata_leggibile(minuti):
    ore, resto = divmod(minuti, 60)
    if ore and resto:
        return f"{ore} h {resto} min"
    if ore:
        return f"{ore} h"
    return f"{resto} min"


def orari_della_sede():
    """Elenco degli orari "HH:MM" da APERTURA a CHIUSURA, passo PASSO_MINUTI."""
    inizio = motore.orario_in_minuti(motore.APERTURA)
    fine = motore.orario_in_minuti(motore.CHIUSURA)
    return [
        motore.minuti_in_orario(m) for m in range(inizio, fine + 1, motore.PASSO_MINUTI)
    ]


def opzioni(valori, selezionato):
    righe = []
    for valore in valori:
        attributo = " selected" if valore == selezionato else ""
        righe.append(f'<option value="{esc(valore)}"{attributo}>{esc(valore)}</option>')
    return "\n".join(righe)


def collegamento(indirizzo, **parametri):
    parametri = {k: v for k, v in parametri.items() if v not in (None, "")}
    if not parametri:
        return indirizzo
    return f"{indirizzo}?{urlencode(parametri)}"


def html_messaggio(testo, tipo):
    if not testo:
        return ""
    tipo = "errore" if tipo == "errore" else "ok"
    ruolo = "alert" if tipo == "errore" else "status"
    return f'<p class="messaggio {tipo}" role="{ruolo}">{esc(testo)}</p>'


def html_schede(registro, barca_attiva, lunedi):
    voci = []
    for barca in registro.elenco_barche():
        url = collegamento(
            "/calendario", settimana=lunedi.isoformat(), barca=barca.codice
        )
        attivo = barca.codice == barca_attiva.codice
        classe = "scheda attiva" if attivo else "scheda"
        corrente = ' aria-current="page"' if attivo else ""
        voci.append(
            f'<a class="{classe}" href="{esc(url)}"{corrente}>'
            f'<span class="codice">{esc(barca.codice)}</span> {esc(barca.nome)}</a>'
        )
    return "\n".join(voci)


def html_navigazione(barca, lunedi, oggi):
    precedente = lunedi - timedelta(days=7)
    successiva = lunedi + timedelta(days=7)
    voci = [
        (precedente, "Settimana precedente"),
        (oggi, "Questa settimana"),
        (successiva, "Settimana successiva"),
    ]
    link = []
    for giorno, etichetta in voci:
        url = collegamento(
            "/calendario", settimana=giorno.isoformat(), barca=barca.codice
        )
        link.append(f'<a href="{esc(url)}">{etichetta}</a>')
    return "\n".join(link)


def html_calendario(registro, barca, settimana, oggi):
    """Griglia settimanale: una colonna per giorno, una riga per fascia."""
    orari = orari_della_sede()[:-1]  # ogni riga è una fascia che inizia qui
    apertura = motore.orario_in_minuti(motore.APERTURA)
    righe_per_ora = max(1, 60 // motore.PASSO_MINUTI)
    primo = next(iter(settimana))
    parti = [
        f'<div class="calendario" style="--fasce: {len(orari)}">',
        '<div class="angolo" aria-hidden="true"></div>',
    ]

    for colonna, giorno in enumerate(settimana, start=2):
        classi = ["intestazione"]
        if giorno == oggi:
            classi.append("oggi")
        try:
            occupati = registro.minuti_occupati(barca.codice, giorno)
            dettaglio = (
                f"occupata {durata_leggibile(occupati)}" if occupati else "libera"
            )
        except NotImplementedError:
            dettaglio = ""
        parti.append(
            f'<div class="{" ".join(classi)}" style="grid-column: {colonna}">'
            f'<span class="nome-giorno">{NOMI_GIORNI[giorno.weekday()]} '
            f"{giorno.day}/{giorno.month}</span>"
            f'<span class="occupazione">{dettaglio}</span></div>'
        )

    for riga, orario in enumerate(orari, start=2):
        if orario.endswith(":00"):
            parti.append(
                f'<div class="ora" style="grid-row: {riga} / span {righe_per_ora}">'
                f"{orario}</div>"
            )
        for colonna, giorno in enumerate(settimana, start=2):
            classi = ["cella"]
            if orario.endswith(":00"):
                classi.append("ora-piena")
            if giorno == oggi:
                classi.append("oggi")
            elif giorno < oggi:
                classi.append("passato")
            stile = f"grid-column: {colonna}; grid-row: {riga}"
            if giorno < oggi:
                parti.append(f'<div class="{" ".join(classi)}" style="{stile}"></div>')
                continue
            fine = motore.minuti_in_orario(
                motore.orario_in_minuti(orario) + 2 * motore.PASSO_MINUTI
            )
            if fine > motore.CHIUSURA:
                fine = motore.CHIUSURA
            url = collegamento(
                "/calendario",
                settimana=primo.isoformat(),
                barca=barca.codice,
                giorno=giorno.isoformat(),
                inizio=orario,
                fine=fine,
            )
            parti.append(
                f'<a class="{" ".join(classi)}" style="{stile}" '
                f'href="{esc(url)}#nuova" '
                f'aria-label="Prenota {NOMI_GIORNI[giorno.weekday()]} '
                f'{giorno.day}/{giorno.month} alle {orario}"></a>'
            )

    for colonna, (giorno, elenco) in enumerate(settimana.items(), start=2):
        for x in elenco:
            inizio, fine = x.intervallo_minuti()
            riga_inizio = (inizio - apertura) // motore.PASSO_MINUTI + 2
            riga_fine = (fine - apertura) // motore.PASSO_MINUTI + 2
            descrizione = (
                f"{x.inizio}-{x.fine} {x.capobarca}, {x.equipaggio} persone a bordo"
            )
            if x.percorso:
                descrizione += f": {x.percorso}"
            posizione = f"grid-column: {colonna}; grid-row: {riga_inizio} / {riga_fine}"
            parti.append(
                f'<div class="prenotazione" style="{posizione}" '
                f'title="{esc(descrizione)}">'
                f'<span class="orario">{x.inizio}–{x.fine}</span>'
                f'<span class="referente">{esc(x.capobarca)}</span>'
                f'<span class="motivo">{esc(x.percorso)}</span></div>'
            )

    parti.append("</div>")
    return "\n".join(parti)


def html_elenco(settimana, barca, lunedi):
    righe = []
    for giorno, elenco in settimana.items():
        for x in elenco:
            righe.append(
                "<tr>"
                f"<td>{NOMI_GIORNI[giorno.weekday()]} {giorno.day}/{giorno.month}</td>"
                f'<td class="numero">{x.inizio}–{x.fine}</td>'
                f"<td>{esc(x.capobarca)}</td>"
                f'<td class="numero">{x.equipaggio}</td>'
                f"<td>{esc(x.percorso)}</td>"
                '<td><form method="post" action="/cancella">'
                f'<input type="hidden" name="id" value="{x.id}">'
                f'<input type="hidden" name="barca" value="{esc(barca.codice)}">'
                f'<input type="hidden" name="settimana" value="{lunedi.isoformat()}">'
                f'<button type="submit" class="secondario">Cancella n. {x.id}</button>'
                "</form></td></tr>"
            )
    if not righe:
        return '<p class="vuoto">Nessuna uscita per questa barca in settimana.</p>'
    return (
        '<div class="tabella-scorrevole"><table class="elenco">'
        "<thead><tr><th>Giorno</th><th>Orario</th><th>Capobarca</th>"
        "<th>Equipaggio</th><th>Percorso</th><th></th></tr></thead>"
        f"<tbody>{''.join(righe)}</tbody></table></div>"
    )


def html_caselle_dotazioni(registro, selezionate):
    tutte = sorted({d for x in registro.elenco_barche() for d in x.dotazioni})
    caselle = []
    for voce in tutte:
        spunta = " checked" if voce in selezionate else ""
        caselle.append(
            f'<label class="casella"><input type="checkbox" name="dotazioni" '
            f'value="{esc(voce)}"{spunta}> {esc(voce)}</label>'
        )
    return "\n".join(caselle)


def html_risultati(barche, giorno, inizio, fine):
    if not barche:
        return (
            '<p class="vuoto">Nessuna barca soddisfa la richiesta. '
            "Prova un'altra fascia oraria o riduci le dotazioni richieste.</p>"
        )
    righe = []
    lunedi = giorno - timedelta(days=giorno.weekday())
    for barca in barche:
        url = collegamento(
            "/calendario",
            settimana=lunedi.isoformat(),
            barca=barca.codice,
            giorno=giorno.isoformat(),
            inizio=inizio,
            fine=fine,
        )
        righe.append(
            f"<li><strong>{esc(barca.codice)}</strong> {esc(barca.nome)}, "
            f"{barca.posti} posti "
            f'<a href="{esc(url)}#nuova">Prenota questa barca</a></li>'
        )
    intestazione = (
        f"Barche libere {NOMI_GIORNI[giorno.weekday()]} {giorno.day}/{giorno.month} "
        f"dalle {esc(inizio)} alle {esc(fine)}"
    )
    return f'<h3>{intestazione}</h3><ul class="risultati">{"".join(righe)}</ul>'


def componi_pagina(registro, parametri, oggi, risultati=""):
    """Compone la pagina del calendario. `parametri` arriva dalla query string."""

    def valore(nome, predefinito=""):
        return parametri.get(nome, [predefinito])[0]

    try:
        riferimento = date.fromisoformat(valore("settimana") or valore("giorno"))
    except ValueError:
        riferimento = oggi
    lunedi = riferimento - timedelta(days=riferimento.weekday())

    barche = registro.elenco_barche()
    if not barche:
        raise MotoreIncompleto("il registro non contiene barche")
    codici = [x.codice for x in barche]
    barca = (
        barche[codici.index(valore("barca"))]
        if valore("barca") in codici
        else barche[0]
    )

    settimana = registro.uscite_della_settimana(lunedi, barca.codice)
    primo, ultimo = min(settimana), max(settimana)

    orari = orari_della_sede()
    giorno_form = valore("giorno")
    if not giorno_form:
        giorno_form = max(primo, oggi).isoformat()

    mappa = {
        "titolo_settimana": f"{data_estesa(primo)} – {data_estesa(ultimo)}",
        "barca_corrente": esc(str(barca)),
        "messaggio": html_messaggio(valore("msg"), valore("tipo")),
        "schede_barche": html_schede(registro, barca, lunedi),
        "navigazione": html_navigazione(barca, lunedi, oggi),
        "calendario": html_calendario(registro, barca, settimana, oggi),
        "elenco_uscite": html_elenco(settimana, barca, lunedi),
        "settimana_corrente": lunedi.isoformat(),
        # modulo di prenotazione
        "opzioni_barche": "\n".join(
            f'<option value="{esc(x.codice)}"'
            f"{' selected' if x is barca else ''}>{esc(str(x))}</option>"
            for x in barche
        ),
        "giorno_min": oggi.isoformat(),
        "giorno_max": (oggi + timedelta(days=motore.ORIZZONTE_GIORNI)).isoformat(),
        "valore_giorno": esc(giorno_form),
        "opzioni_inizio": opzioni(orari[:-1], valore("inizio", orari[2])),
        "opzioni_fine": opzioni(orari[1:], valore("fine", orari[4])),
        "valore_capobarca": esc(valore("capobarca")),
        "valore_equipaggio": esc(valore("equipaggio", "1")),
        "valore_percorso": esc(valore("percorso")),
        # modulo di ricerca
        "valore_giorno_ricerca": esc(valore("giorno_ricerca", giorno_form)),
        "opzioni_inizio_ricerca": opzioni(
            orari[:-1], valore("inizio_ricerca", orari[2])
        ),
        "opzioni_fine_ricerca": opzioni(orari[1:], valore("fine_ricerca", orari[4])),
        "valore_persone_ricerca": esc(valore("persone", "1")),
        "caselle_dotazioni": html_caselle_dotazioni(
            registro, parametri.get("dotazioni", [])
        ),
        "risultati_ricerca": risultati,
    }
    with open(FILE_MODELLO, encoding="utf-8") as f:
        modello = Template(f.read())
    return modello.safe_substitute(mappa)


def pagina_motore_incompleto(dettaglio):
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Motore incompleto</title>
<link rel="stylesheet" href="/static/stile.css"></head>
<body><main class="avviso-motore">
<h1>Il motore di prenotazione non è ancora pronto</h1>
<p>La pagina richiede una funzione non ancora implementata in
<code>prenotazioni.py</code>: <strong>{esc(dettaglio)}</strong>.</p>
<p>Completa la funzione, ferma il server con Ctrl+C e riavvialo.</p>
</main></body></html>"""


# ---------------------------------------------------------------------------
# Gestione delle richieste
# ---------------------------------------------------------------------------


class Gestore(BaseHTTPRequestHandler):
    registro = None

    # --- risposte ------------------------------------------------------------

    def invia(self, corpo, tipo="text/html; charset=utf-8", stato=200):
        dati = corpo.encode("utf-8")
        self.send_response(stato)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dati)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dati)

    def reindirizza(self, url):
        self.send_response(303)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def registro_pronto(self):
        """Restituisce il registro, preparandolo alla prima richiesta utile."""
        if Gestore.registro is None:
            Gestore.registro = prepara_registro()
        return Gestore.registro

    # --- GET -----------------------------------------------------------------

    def do_GET(self):  # noqa: N802 (nome imposto da http.server)
        richiesta = urlparse(self.path)
        parametri = parse_qs(richiesta.query)
        try:
            if richiesta.path == "/":
                self.reindirizza("/calendario")
            elif richiesta.path == "/calendario":
                oggi = date.today()
                pagina = componi_pagina(self.registro_pronto(), parametri, oggi)
                self.invia(pagina)
            elif richiesta.path == "/libere":
                self.cerca_libere(parametri)
            elif richiesta.path == "/static/stile.css":
                with open(FILE_STILE, encoding="utf-8") as f:
                    self.invia(f.read(), "text/css; charset=utf-8")
            else:
                self.invia("<h1>Pagina non trovata</h1>", stato=404)
        except NotImplementedError as errore:
            self.invia(pagina_motore_incompleto(str(errore)), stato=500)
        except MotoreIncompleto as errore:
            self.invia(pagina_motore_incompleto(str(errore)), stato=500)

    def cerca_libere(self, parametri):
        registro = self.registro_pronto()
        oggi = date.today()

        def valore(nome, predefinito=""):
            return parametri.get(nome, [predefinito])[0]

        # I campi di ricerca vengono rinominati per non confondersi con quelli
        # del modulo di prenotazione nella stessa pagina.
        visualizza = dict(parametri)
        visualizza["giorno_ricerca"] = [valore("giorno")]
        visualizza["inizio_ricerca"] = [valore("inizio")]
        visualizza["fine_ricerca"] = [valore("fine")]
        for chiave in ("giorno", "inizio", "fine"):
            visualizza.pop(chiave, None)
        visualizza["settimana"] = [valore("giorno")]
        visualizza["barca"] = [valore("barca")]

        risultati = ""
        try:
            giorno = date.fromisoformat(valore("giorno"))
            persone = int(valore("persone", "1"))
            barche = registro.barche_libere(
                giorno,
                valore("inizio"),
                valore("fine"),
                persone,
                parametri.get("dotazioni", []),
            )
            risultati = html_risultati(barche, giorno, valore("inizio"), valore("fine"))
        except NotImplementedError:
            visualizza["msg"] = ["La ricerca delle barche libere non è implementata."]
            visualizza["tipo"] = ["errore"]
        except (ValueError, TypeError, motore.ErroreRegistro) as errore:
            visualizza["msg"] = [f"Ricerca non valida: {errore}"]
            visualizza["tipo"] = ["errore"]
        self.invia(componi_pagina(registro, visualizza, oggi, risultati))

    # --- POST ----------------------------------------------------------------

    def leggi_modulo(self):
        lunghezza = int(self.headers.get("Content-Length", 0))
        corpo = self.rfile.read(lunghezza).decode("utf-8")
        return {k: v[0] for k, v in parse_qs(corpo, keep_blank_values=True).items()}

    def do_POST(self):  # noqa: N802 (nome imposto da http.server)
        modulo = self.leggi_modulo()
        try:
            if self.path == "/prenota":
                self.prenota(modulo)
            elif self.path == "/cancella":
                self.cancella(modulo)
            else:
                self.invia("<h1>Pagina non trovata</h1>", stato=404)
        except NotImplementedError as errore:
            self.invia(pagina_motore_incompleto(str(errore)), stato=500)

    def prenota(self, modulo):
        registro = self.registro_pronto()
        ritorno = {
            "barca": modulo.get("barca", ""),
            "settimana": modulo.get("settimana", ""),
        }
        try:
            try:
                giorno = date.fromisoformat(modulo.get("giorno", ""))
            except ValueError:
                raise ValueError("La data indicata non è valida") from None
            try:
                equipaggio = int(modulo.get("equipaggio", ""))
            except ValueError:
                raise ValueError("Il numero dell'equipaggio non è valido") from None
            uscita = motore.Uscita(
                modulo.get("barca", ""),
                giorno,
                modulo.get("inizio", ""),
                modulo.get("fine", ""),
                modulo.get("capobarca", ""),
                equipaggio,
                modulo.get("percorso", ""),
            )
            registro.prenota(uscita)
            registro.salva(FILE_DATI)
        except (ValueError, TypeError, motore.ErroreRegistro) as errore:
            # Si torna al modulo conservando i dati inseriti.
            for campo_modulo in ("giorno", "inizio", "fine", "capobarca", "equipaggio"):
                ritorno[campo_modulo] = modulo.get(campo_modulo, "")
            ritorno["percorso"] = modulo.get("percorso", "")
            ritorno["msg"] = f"Uscita non registrata: {errore}"
            ritorno["tipo"] = "errore"
            self.reindirizza(collegamento("/calendario", **ritorno) + "#nuova")
            return
        ritorno["settimana"] = giorno.isoformat()
        ritorno["msg"] = f"Uscita registrata: {uscita}"
        ritorno["tipo"] = "ok"
        self.reindirizza(collegamento("/calendario", **ritorno))

    def cancella(self, modulo):
        registro = self.registro_pronto()
        ritorno = {
            "barca": modulo.get("barca", ""),
            "settimana": modulo.get("settimana", ""),
        }
        try:
            identificativo = int(modulo.get("id", ""))
            registro.cancella(identificativo)
            registro.salva(FILE_DATI)
            ritorno["msg"] = f"Uscita n. {identificativo} cancellata."
            ritorno["tipo"] = "ok"
        except (ValueError, motore.ErroreRegistro) as errore:
            ritorno["msg"] = f"Cancellazione non riuscita: {errore}"
            ritorno["tipo"] = "errore"
        self.reindirizza(collegamento("/calendario", **ritorno))


def main():
    server = HTTPServer((INDIRIZZO, PORTA), Gestore)
    print(f"Interfaccia disponibile su http://{INDIRIZZO}:{PORTA}/")
    print("Per fermare il server: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer fermato.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
