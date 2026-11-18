"""Motore di prenotazione delle barche del circolo.

Le docstring descrivono il comportamento richiesto e costituiscono la
specifica del modulo.
"""

import json
from datetime import date, timedelta

# Regole del circolo. Il codice deve usare queste costanti, non i valori
# scritti direttamente: se cambiano le regole, si modifica solo qui.
APERTURA = "07:00"
CHIUSURA = "19:00"
PASSO_MINUTI = 30
ORIZZONTE_GIORNI = 21
# Giorno di chiusura, con la numerazione di date.weekday():
# 0 = lunedì, 1 = martedì, ..., 6 = domenica.
GIORNO_CHIUSURA = 1  # martedì


# ---------------------------------------------------------------------------
# Eccezioni
# ---------------------------------------------------------------------------


class ErroreRegistro(Exception):
    """Classe base per le richieste rifiutate dal registro."""


class BarcaNonTrovata(ErroreRegistro):
    """Il codice non corrisponde ad alcuna barca registrata."""


class UscitaNonTrovata(ErroreRegistro):
    """L'identificativo non corrisponde ad alcuna uscita."""


class DataNonAmmessa(ErroreRegistro):
    """La data non è prenotabile secondo le regole del circolo."""


class EquipaggioEccessivo(ErroreRegistro):
    """L'equipaggio supera i posti della barca."""


class BarcaImpegnata(ErroreRegistro):
    """La richiesta si sovrappone a un'uscita esistente."""


# ---------------------------------------------------------------------------
# Funzioni di utilità sugli orari
# ---------------------------------------------------------------------------


def orario_in_minuti(orario):
    """Converte un orario "HH:MM" nel numero di minuti dalla mezzanotte.

    Esempio: "09:30" -> 570.

    Il formato è rigido: esattamente 5 caratteri, due cifre, il carattere ":",
    due cifre. Ore tra 00 e 23, minuti tra 00 e 59.

    Solleva:
        TypeError: se `orario` non è una stringa.
        ValueError: se il formato non è rispettato o l'orario non esiste
            (es. "9:30", "09.30", "24:00", "12:60").
    """
    if not isinstance(orario, str):
        raise TypeError("L'orario deve essere una stringa nel formato HH:MM")
    if len(orario) != 5 or orario[2] != ":":
        raise ValueError(f"Orario non valido: '{orario}' (formato atteso HH:MM)")
    ore_testo, minuti_testo = orario[:2], orario[3:]
    if not (ore_testo.isdigit() and minuti_testo.isdigit()):
        raise ValueError(f"Orario non valido: '{orario}' (formato atteso HH:MM)")
    ore, minuti = int(ore_testo), int(minuti_testo)
    if ore > 23 or minuti > 59:
        raise ValueError(f"Orario inesistente: '{orario}'")
    return ore * 60 + minuti


def minuti_in_orario(minuti):
    """Converte i minuti dalla mezzanotte nella stringa "HH:MM".

    Esempio: 570 -> "09:30". Ore e minuti hanno sempre due cifre.

    Solleva:
        TypeError: se `minuti` non è un intero.
        ValueError: se `minuti` non è compreso tra 0 e 1439.
    """
    if not isinstance(minuti, int) or isinstance(minuti, bool):
        raise TypeError("I minuti devono essere un numero intero")
    if not 0 <= minuti <= 1439:
        raise ValueError(f"Minuti fuori intervallo: {minuti} (ammessi 0-1439)")
    return f"{minuti // 60:02d}:{minuti % 60:02d}"


# ---------------------------------------------------------------------------
# Barca
# ---------------------------------------------------------------------------


class Barca:
    """Una barca prenotabile del circolo.

    Attributi pubblici:
        codice (str): identificativo univoco, es. "O8".
        nome (str): nome leggibile, es. "Otto".
        posti (int): numero di posti a bordo, timoniere compreso.
        dotazioni (list[str]): attrezzature presenti, es. ["timone"].
    """

    def __init__(self, codice, nome, posti, dotazioni=None):
        """Crea una barca validando i dati.

        - `codice` e `nome` vengono privati degli spazi iniziali e finali
          (strip) e non possono risultare vuoti.
        - `posti` deve essere un intero maggiore o uguale a 1.
        - `dotazioni` è facoltativo (None equivale a lista vuota); ogni voce
          viene memorizzata con strip() e in minuscolo, nell'ordine dato.
          La lista memorizzata è una copia: modificare quella passata non
          deve modificare la barca.

        Solleva:
            ValueError: codice o nome vuoti, posti minore di 1.
            TypeError: posti non intero.
        """
        if not isinstance(codice, str) or not codice.strip():
            raise ValueError("Il codice della barca non può essere vuoto")
        if not isinstance(nome, str) or not nome.strip():
            raise ValueError("Il nome della barca non può essere vuoto")
        if not isinstance(posti, int) or isinstance(posti, bool):
            raise TypeError("Il numero di posti deve essere un numero intero")
        if posti < 1:
            raise ValueError("Il numero di posti deve essere almeno 1")
        self.codice = codice.strip()
        self.nome = nome.strip()
        self.posti = posti
        if dotazioni is None:
            dotazioni = []
        self.dotazioni = [d.strip().lower() for d in dotazioni]

    def ha_dotazioni(self, richieste):
        """Restituisce True se la barca dispone di TUTTE le dotazioni richieste.

        Il confronto ignora maiuscole/minuscole e spazi esterni.
        Una lista di richieste vuota restituisce True.
        """
        return all(r.strip().lower() in self.dotazioni for r in richieste)

    def to_dict(self):
        """Restituisce un dizionario con le chiavi
        "codice", "nome", "posti", "dotazioni".
        """
        return {
            "codice": self.codice,
            "nome": self.nome,
            "posti": self.posti,
            "dotazioni": list(self.dotazioni),
        }

    @classmethod
    def from_dict(cls, dati):
        """Costruttore alternativo: crea una barca dal dizionario prodotto da
        to_dict(). La chiave "dotazioni" è facoltativa.
        """
        return cls(
            dati["codice"],
            dati["nome"],
            dati["posti"],
            dati.get("dotazioni", []),
        )

    def __str__(self):
        """Formato esatto: "O8 - Otto (9 posti)"."""
        return f"{self.codice} - {self.nome} ({self.posti} posti)"


# ---------------------------------------------------------------------------
# Uscita
# ---------------------------------------------------------------------------


class Uscita:
    """Una richiesta di utilizzo di una barca in un giorno e in una fascia oraria.

    Attributi pubblici:
        id (int | None): assegnato da Registro; None finché non registrata.
        barca_codice (str)
        giorno (datetime.date)
        inizio (str): "HH:MM"
        fine (str): "HH:MM"
        capobarca (str): socio responsabile dell'uscita.
        equipaggio (int): numero di persone a bordo.
        percorso (str): percorso previsto, può essere vuoto.
    """

    def __init__(
        self, barca_codice, giorno, inizio, fine, capobarca, equipaggio, percorso=""
    ):
        """Crea un'uscita validando i dati che dipendono solo da essa.

        Non verifica l'esistenza della barca, i posti, i conflitti o le regole
        sulle date: questi controlli spettano a Registro.prenota().

        Regole:
        - `barca_codice`, `capobarca`, `percorso`: si applica strip();
          barca_codice e capobarca non possono risultare vuoti.
        - `giorno` deve essere un oggetto datetime.date.
        - `inizio` e `fine` devono essere orari validi (vedi orario_in_minuti),
          con minuti multipli di PASSO_MINUTI, inizio >= APERTURA,
          fine <= CHIUSURA, inizio strettamente precedente a fine.
        - `equipaggio` deve essere un intero maggiore o uguale a 1.
        - `id` vale None.

        Solleva:
            TypeError: giorno non di tipo date, equipaggio non intero.
            ValueError: ogni altra violazione delle regole.
        """
        if not isinstance(barca_codice, str) or not barca_codice.strip():
            raise ValueError("Il codice della barca non può essere vuoto")
        if not isinstance(giorno, date):
            raise TypeError("Il giorno deve essere un oggetto datetime.date")

        minuto_inizio = orario_in_minuti(inizio)
        minuto_fine = orario_in_minuti(fine)
        for minuto, testo in ((minuto_inizio, inizio), (minuto_fine, fine)):
            if minuto % PASSO_MINUTI != 0:
                raise ValueError(
                    f"L'orario {testo} non è multiplo di {PASSO_MINUTI} minuti"
                )
        if minuto_inizio <= orario_in_minuti(APERTURA):
            raise ValueError(f"Il circolo apre alle {APERTURA}")
        if minuto_fine > orario_in_minuti(CHIUSURA):
            raise ValueError(f"Il circolo chiude alle {CHIUSURA}")
        if minuto_inizio >= minuto_fine:
            raise ValueError("L'orario di inizio deve precedere quello di fine")

        if not isinstance(capobarca, str) or not capobarca.strip():
            raise ValueError("Il capobarca non può essere vuoto")
        if not isinstance(equipaggio, int) or isinstance(equipaggio, bool):
            raise TypeError("L'equipaggio deve essere un numero intero")
        if equipaggio < 1:
            raise ValueError("L'equipaggio deve contare almeno una persona")

        self.id = None
        self.barca_codice = barca_codice.strip()
        self.giorno = giorno
        self.inizio = inizio
        self.fine = fine
        self.capobarca = capobarca.strip()
        self.equipaggio = equipaggio
        self.percorso = percorso.strip()

    def intervallo_minuti(self):
        """Restituisce la tupla (minuto_inizio, minuto_fine).

        Esempio: 07:30-09:00 -> (450, 540).
        """
        return orario_in_minuti(self.inizio), orario_in_minuti(self.fine)

    def durata_minuti(self):
        """Restituisce la durata in minuti. Esempio: 07:30-09:00 -> 90."""
        inizio, fine = self.intervallo_minuti()
        return fine - inizio

    def si_sovrappone(self, altra):
        """True se `altra` riguarda la stessa barca, lo stesso giorno e
        un intervallo che ha almeno un minuto in comune con questo.

        Due uscite contigue (07:30-08:30 e 08:30-09:30) NON si
        sovrappongono.
        """
        if self.barca_codice != altra.barca_codice or self.giorno != altra.giorno:
            return False
        inizio_a, fine_a = self.intervallo_minuti()
        inizio_b, fine_b = altra.intervallo_minuti()
        return inizio_a < fine_b and inizio_b < fine_a

    def to_dict(self):
        """Restituisce un dizionario con le chiavi:
        "id", "barca", "giorno", "inizio", "fine", "capobarca",
        "equipaggio", "percorso".
        Il giorno è una stringa ISO ("2026-11-11").
        """
        return {
            "id": self.id,
            "barca": self.barca_codice,
            "giorno": self.giorno.isoformat(),
            "inizio": self.inizio,
            "fine": self.fine,
            "capobarca": self.capobarca,
            "equipaggio": self.equipaggio,
            "percorso": self.percorso,
        }

    @classmethod
    def from_dict(cls, dati):
        """Costruttore alternativo, inverso di to_dict().

        Ripristina anche l'id. Le chiavi "id" e "percorso" sono facoltative.
        """
        uscita = cls(
            dati["barca"],
            date.fromisoformat(dati["giorno"]),
            dati["inizio"],
            dati["fine"],
            dati["capobarca"],
            dati["equipaggio"],
            dati.get("percorso", ""),
        )
        uscita.id = dati.get("id")
        return uscita

    def __str__(self):
        """Formato esatto:
        "3 | O8 | 2026-11-11 07:30-09:00 | Mario Rossi (2 a bordo)"
        Se l'id è None, al posto del numero compare "-".
        """
        identificativo = "-" if self.id is None else self.id
        return (
            f"{identificativo} | {self.barca_codice} | "
            f"{self.giorno.isoformat()} {self.inizio}-{self.fine} | "
            f"{self.capobarca} ({self.equipaggio} a bordo)"
        )


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


class Registro:
    """Registro delle barche e delle uscite del circolo.

    Attributi pubblici:
        barche (dict[str, Barca]): barche indicizzate per codice.
        uscite (dict[int, Uscita]): uscite indicizzate per id.
    """

    def __init__(self):
        """Crea un registro vuoto. Il primo id assegnato sarà 1."""
        self.barche = {}
        self.uscite = {}
        self._prossimo_id = 1

    # --- barche ------------------------------------------------------------

    def aggiungi_barca(self, barca):
        """Registra una barca.

        Solleva:
            ValueError: se esiste già una barca con lo stesso codice.
        """
        if barca.codice in self.barche:
            raise ValueError(f"Esiste già una barca con codice {barca.codice}")
        self.barche[barca.codice] = barca

    def barca(self, codice):
        """Restituisce la barca con il codice dato.

        Solleva:
            BarcaNonTrovata: se il codice non è registrato.
        """
        if codice not in self.barche:
            raise BarcaNonTrovata(f"La barca {codice} non esiste")
        return self.barche[codice]

    def elenco_barche(self):
        """Restituisce la lista delle barche ordinata per codice."""
        return [self.barche[codice] for codice in sorted(self.barche)]

    # --- uscite ------------------------------------------------------------

    def _verifica_data(self, giorno, oggi):
        """Solleva DataNonAmmessa se `giorno` non è prenotabile rispetto a `oggi`."""
        if giorno < oggi:
            raise DataNonAmmessa("Non si può prenotare una data già trascorsa")
        if giorno.weekday() == GIORNO_CHIUSURA:
            raise DataNonAmmessa("Il circolo è chiuso il martedì")
        if giorno >= oggi + timedelta(days=ORIZZONTE_GIORNI):
            raise DataNonAmmessa(
                f"Si può prenotare al massimo {ORIZZONTE_GIORNI} giorni in anticipo"
            )

    def prenota(self, uscita, oggi=None):
        """Registra un'uscita e ne restituisce l'id.

        `oggi` è la data di riferimento per i controlli sulle date; se None si
        usa date.today(). (Il parametro esiste per rendere il metodo
        verificabile con i test indipendentemente dal giorno di esecuzione.)

        I controlli si eseguono in QUESTO ORDINE e si interrompono al primo
        fallimento; una richiesta rifiutata non modifica il registro.
          1. l'uscita ha già un id                  -> ValueError
          2. la barca non esiste                    -> BarcaNonTrovata
          3. il giorno è precedente a oggi,
             oppure è il giorno di chiusura (GIORNO_CHIUSURA),
             oppure è oltre oggi + ORIZZONTE_GIORNI -> DataNonAmmessa
             (oggi e oggi + ORIZZONTE_GIORNI sono ammessi; si controlla
             solo la data, non l'ora)
          4. equipaggio > posti della barca         -> EquipaggioEccessivo
          5. sovrapposizione con un'uscita
             esistente                              -> BarcaImpegnata

        Se la richiesta è accettata, le viene assegnato l'id progressivo
        successivo (1, 2, 3, ...). Gli id di uscite cancellate non
        vengono riutilizzati.

        Il messaggio di ogni eccezione deve spiegare il motivo in italiano:
        viene mostrato dall'interfaccia web a chi la usa.
        """
        if oggi is None:
            oggi = date.today()
        if uscita.id is not None:
            raise ValueError("L'uscita è già registrata")
        barca = self.barca(uscita.barca_codice)
        self._verifica_data(uscita.giorno, oggi)
        if uscita.equipaggio > barca.posti:
            raise EquipaggioEccessivo(f"La barca {barca.codice} ha {barca.posti} posti")
        for esistente in self.uscite.values():
            if uscita.si_sovrappone(esistente):
                raise BarcaImpegnata(
                    f"La barca {barca.codice} è già impegnata dalle "
                    f"{esistente.inizio} alle {esistente.fine}"
                )
        uscita.id = self._prossimo_id
        self._prossimo_id += 1
        self.uscite[uscita.id] = uscita
        return uscita.id

    def uscita(self, id_uscita):
        """Restituisce l'uscita con l'id dato.

        Solleva:
            UscitaNonTrovata: se l'id non esiste.
        """
        if id_uscita not in self.uscite:
            raise UscitaNonTrovata(f"Nessuna uscita con identificativo {id_uscita}")
        return self.uscite[id_uscita]

    def cancella(self, id_uscita):
        """Rimuove l'uscita e la restituisce.

        Solleva:
            UscitaNonTrovata: se l'id non esiste.
        """
        uscita = self.uscita(id_uscita)
        del self.uscite[id_uscita]
        return uscita

    def uscite_del_giorno(self, giorno, barca_codice=None):
        """Restituisce la lista delle uscite del giorno dato.

        Se `barca_codice` è indicato, solo quelle della barca.
        Ordinamento: per orario di inizio, a parità per codice della barca.

        Solleva:
            BarcaNonTrovata: se `barca_codice` è indicato ma non esiste.
        """
        if barca_codice is not None:
            self.barca(barca_codice)
        risultato = [
            x
            for x in self.uscite.values()
            if x.giorno == giorno
            and (barca_codice is None or x.barca_codice == barca_codice)
        ]
        risultato.sort(key=lambda x: (orario_in_minuti(x.inizio), x.barca_codice))
        return risultato

    def uscite_della_settimana(self, giorno, barca_codice=None):
        """Restituisce le uscite della settimana che contiene `giorno`.

        La settimana va dal lunedì alla domenica: se `giorno` è una domenica,
        è quella che termina con essa. Il risultato è un dizionario con 6
        chiavi di tipo date, una per ogni giorno della settimana escluso il
        giorno di chiusura (GIORNO_CHIUSURA), in ordine di data; ogni valore
        è la lista restituita da uscite_del_giorno() per quel giorno (anche
        vuota).

        Solleva:
            BarcaNonTrovata: se `barca_codice` è indicato ma non esiste.
        """
        lunedi = giorno - timedelta(days=giorno.weekday())
        settimana = {}
        for scarto in range(7):
            corrente = lunedi + timedelta(days=scarto)
            if corrente.weekday() != GIORNO_CHIUSURA:
                settimana[corrente] = self.uscite_del_giorno(corrente, barca_codice)
        return settimana

    def barche_libere(
        self, giorno, inizio, fine, equipaggio=1, dotazioni=None, oggi=None
    ):
        """Restituisce le barche prenotabili per la fascia indicata.

        Una barca è inclusa se ha posti >= `equipaggio`, dispone di tutte
        le `dotazioni` richieste (None equivale a nessuna) e non ha uscite
        sovrapposte alla fascia inizio-fine del giorno indicato.

        Ordinamento: per posti crescente, a parità per codice.
        Se il giorno non è ammesso dalle regole sulle date (vedi prenota),
        restituisce una lista vuota.

        Solleva:
            TypeError, ValueError: alle stesse condizioni di Uscita
                per giorno, inizio e fine; ValueError se equipaggio < 1.
        """
        if oggi is None:
            oggi = date.today()
        if dotazioni is None:
            dotazioni = []
        if not isinstance(equipaggio, int) or isinstance(equipaggio, bool):
            raise TypeError("L'equipaggio deve essere un numero intero")
        if equipaggio < 1:
            raise ValueError("L'equipaggio deve contare almeno una persona")
        # La richiesta di prova valida giorno e orari prima di ogni altra cosa.
        prova = Uscita("-", giorno, inizio, fine, "ricerca", 1)
        try:
            self._verifica_data(giorno, oggi)
        except DataNonAmmessa:
            return []
        libere = []
        for barca in self.elenco_barche():
            if barca.posti < equipaggio or not barca.ha_dotazioni(dotazioni):
                continue
            prova.barca_codice = barca.codice
            occupata = any(prova.si_sovrappone(x) for x in self.uscite.values())
            if not occupata:
                libere.append(barca)
        libere.sort(key=lambda x: (x.posti, x.codice))
        return libere

    def minuti_occupati(self, barca_codice, giorno):
        """Restituisce il totale dei minuti prenotati per la barca nel giorno.

        Solleva:
            BarcaNonTrovata: se la barca non esiste.
        """
        return sum(
            x.durata_minuti() for x in self.uscite_del_giorno(giorno, barca_codice)
        )

    # --- persistenza -------------------------------------------------------

    def salva(self, percorso):
        """Salva il registro in un file JSON (UTF-8) con questa struttura:

        {
          "barche": [ <Barca.to_dict()>, ... ],
          "uscite": [ <Uscita.to_dict()>, ... ],
          "prossimo_id": <int>
        }
        """
        dati = {
            "barche": [x.to_dict() for x in self.elenco_barche()],
            "uscite": [self.uscite[i].to_dict() for i in sorted(self.uscite)],
            "prossimo_id": self._prossimo_id,
        }
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(dati, f, indent=2, ensure_ascii=False)

    @classmethod
    def carica(cls, percorso):
        """Costruttore alternativo: ricostruisce un registro dal file JSON
        prodotto da salva().

        Le uscite caricate non sono sottoposte alle regole sulle
        date (un archivio contiene legittimamente uscite passate).
        Dopo il caricamento, il prossimo id assegnato deve essere quello
        salvato.

        Solleva:
            FileNotFoundError: se il file non esiste.
        """
        with open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
        registro = cls()
        for dati_barca in dati["barche"]:
            registro.aggiungi_barca(Barca.from_dict(dati_barca))
        for dati_uscita in dati["uscite"]:
            uscita = Uscita.from_dict(dati_uscita)
            registro.uscite[uscita.id] = uscita
        registro._prossimo_id = dati["prossimo_id"]
        return registro
