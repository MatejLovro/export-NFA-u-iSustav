"""
dbf_reader.py

Cita Clipper DBF izvorne tablice i priprema ih za uvoz:
  - RACUNI.DBF   - glave racuna, filtrirano po rasponu BROJ_RACUN
  - SUR.DBF      - stavke racuna, indeksirano po BROJ_RACUN (jedan racun -> vise stavki)
  - PARTNERI.DBF - kupci, indeksirano po SIF_KUPCA (PK)
  - ARTIKLI.DBF  - artikli, indeksirano po KONTO (PK)
  - USLUGE.DBF   - usluge, indeksirano po SIF_USLU (PK)
  - EIU_1.DBF    - dodatni opisni tekst, indeksirano po SIFRA_VEZE

Sve tekstualne vrijednosti se automatski prolaze kroz convert_yuscii() pri
citanju, OSIM polja PARTNERI.DBF:TELEFON2 (email adrese - '@' mora ostati
doslovni znak). PARTNERI.DBF:KONT_OSOB koristi pametnu convert_yuscii_smart()
koja stiti prepoznate email adrese, ali i dalje konvertira '@' u imenima.

Tablice su relativno male (nekoliko stotina do nekoliko tisuca zapisa), pa se
u cijelosti ucitavaju u memoriju - nema potrebe za DBF indeksnim (.NTX/.CDX)
datotekama.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dbfread import DBF

from text_utils import convert_yuscii, convert_yuscii_smart


class DbfReadError(Exception):
    """Podignuto kad ocekivano polje/zapis nedostaje u DBF datoteci."""


# Polja u kojima se '@' NE smije konvertirati u 'Ž' (sadrze email adrese i sl.)
# Kljuc je (naziv_tablice, naziv_polja).
_NO_AT_CONVERSION_FIELDS = {
    ("PARTNERI", "TELEFON2"),
}

# Polja koja MIJESAJU slobodan tekst (gdje '@' moze biti zamjena za 'Ž')
# s prigodno upisanim email adresama (gdje '@' mora ostati doslovan) -
# koristi se pametno prepoznavanje email obrasca umjesto grubog iskljucenja.
_SMART_AT_FIELDS = {
    ("PARTNERI", "KONT_OSOB"),
}


def _convert_record(table_name: str, record: dict) -> dict:
    """Vraca kopiju zapisa s konvertiranim tekstualnim poljima (YUSCII -> hrvatska slova)."""
    result = {}
    for key, value in record.items():
        if isinstance(value, str):
            field_key = (table_name, key)
            if field_key in _SMART_AT_FIELDS:
                result[key] = convert_yuscii_smart(value)
            else:
                convert_at = field_key not in _NO_AT_CONVERSION_FIELDS
                result[key] = convert_yuscii(value, convert_at=convert_at)
        else:
            result[key] = value
    return result


def _read_dbf(path: str, encoding: str) -> DBF:
    try:
        return DBF(path, encoding=encoding, ignore_missing_memofile=True)
    except FileNotFoundError as e:
        raise DbfReadError(f"DBF datoteka nije pronadena: {path}") from e


# ------------------------------------------------------------------
# RACUNI.DBF - glave racuna
# ------------------------------------------------------------------

def load_racuni(path: str, broj1: int, broj2: int, encoding: str = "cp852") -> list[dict]:
    """
    Cita RACUNI.DBF i vraca listu zapisa gdje je broj1 <= BROJ_RACUN <= broj2,
    sortiranu uzlazno po BROJ_RACUN.

    Iterira kroz stvarne zapise (ne pretpostavlja uzastopne brojeve).
    """
    table = _read_dbf(path, encoding)
    result = []
    for rec in table:
        broj = rec.get("BROJ_RACUN")
        if broj is None:
            continue
        if broj1 <= broj <= broj2:
            result.append(_convert_record("RACUNI", rec))
    result.sort(key=lambda r: r["BROJ_RACUN"])
    return result


# ------------------------------------------------------------------
# SUR.DBF - stavke racuna
# ------------------------------------------------------------------

def load_sur_index(path: str, encoding: str = "cp852") -> dict[int, list[dict]]:
    """
    Cita SUR.DBF i vraca rjecnik {BROJ_RACUN: [stavka1, stavka2, ...]}.

    Redoslijed stavki unutar racuna je onakav kakav je u izvornoj DBF datoteci
    (dbfread cita zapise redom kako su fizicki zapisani).
    """
    table = _read_dbf(path, encoding)
    index: dict[int, list[dict]] = {}
    for rec in table:
        broj = rec.get("BROJ_RACUN")
        if broj is None:
            continue
        index.setdefault(broj, []).append(_convert_record("SUR", rec))
    return index


def get_stavke_za_racun(sur_index: dict[int, list[dict]], broj_racun: int) -> list[dict]:
    """Vraca stavke za dani broj racuna (prazna lista ako ih nema)."""
    return sur_index.get(broj_racun, [])


# ------------------------------------------------------------------
# PARTNERI.DBF - kupci
# ------------------------------------------------------------------

def load_partneri_index(path: str, encoding: str = "cp852") -> dict[str, dict]:
    """Cita PARTNERI.DBF i vraca rjecnik {SIF_KUPCA: zapis}."""
    table = _read_dbf(path, encoding)
    index: dict[str, dict] = {}
    for rec in table:
        sif = rec.get("SIF_KUPCA")
        if sif is None:
            continue
        index[sif] = _convert_record("PARTNERI", rec)
    return index


# ------------------------------------------------------------------
# ARTIKLI.DBF - artikli
# ------------------------------------------------------------------

def load_artikli_index(path: str, encoding: str = "cp852") -> dict[str, dict]:
    """Cita ARTIKLI.DBF i vraca rjecnik {KONTO: zapis}."""
    table = _read_dbf(path, encoding)
    index: dict[str, dict] = {}
    for rec in table:
        konto = rec.get("KONTO")
        if konto is None:
            continue
        index[konto] = _convert_record("ARTIKLI", rec)
    return index


# ------------------------------------------------------------------
# USLUGE.DBF - usluge
# ------------------------------------------------------------------

def load_usluge_index(path: str, encoding: str = "cp852") -> dict[str, dict]:
    """
    Cita USLUGE.DBF i vraca rjecnik {SIF_USLU: zapis}.

    NAPOMENA: SIF_USLU bi trebao biti PK, ali u praksi se zna dogoditi da je
    ista sifra ponovno iskoristena za posve drugu uslugu (stara ocito
    izbrisana/zamijenjena, ali fizicki zapis ostao u DBF-u). Po dogovoru,
    kod duplikata pobjeduje ZADNJI zapis u datoteci - a kako iteriramo kroz
    zapise redom i svaki novi upis prepisuje prethodni u rjecniku, to je
    upravo ono sto se ovdje prirodno dogada (nema potrebe za posebnom logikom).
    """
    table = _read_dbf(path, encoding)
    index: dict[str, dict] = {}
    for rec in table:
        sif = rec.get("SIF_USLU")
        if sif is None:
            continue
        index[sif] = _convert_record("USLUGE", rec)
    return index


# ------------------------------------------------------------------
# EIU_1.DBF - dodatni opisni tekst vezan uz stavke racuna (SUR.DBF:SIFRA_VEZE)
# ------------------------------------------------------------------

def load_eiu1_index(path: str, encoding: str = "cp852") -> dict[str, list[str]]:
    """
    Cita EIU_1.DBF i vraca rjecnik {SIFRA_VEZE: [NAZIV1, NAZIV2, ...]}.

    Jedna SIFRA_VEZE moze imati VISE redaka dodatnog teksta (potvrdeno na
    stvarnim podacima - najcesce 1 redak, ali zna ih biti i do 5) - svi se
    cuvaju redom kako su fizicki zapisani u DBF-u, jer se pri spajanju u
    VPRST:OPISROBE moraju nadovezati tim redoslijedom.
    """
    table = _read_dbf(path, encoding)
    index: dict[str, list[str]] = {}
    for rec in table:
        sifra = (rec.get("SIFRA_VEZE") or "").strip()
        if not sifra:
            continue
        naziv = convert_yuscii(rec.get("NAZIV"), convert_at=True)
        index.setdefault(sifra, []).append(naziv)
    return index


# ------------------------------------------------------------------
# Objedinjeni kontejner - ucita sve izvorne tablice odjednom
# ------------------------------------------------------------------

@dataclass
class DbfSourceData:
    """Drzi sve ucitane/indeksirane DBF podatke potrebne za jedan prolaz uvoza."""
    racuni: list[dict]
    sur_index: dict[int, list[dict]]
    partneri_index: dict[str, dict]
    artikli_index: dict[str, dict]
    usluge_index: dict[str, dict]
    eiu1_index: dict[str, list[str]]


def load_all(
    dir_rac: str,
    dir_baze: str,
    broj1: int,
    broj2: int,
    encoding: str = "cp852",
    path_join=None,
) -> DbfSourceData:
    """
    Ucitava sve potrebne DBF tablice odjednom.

    path_join: opcionalna funkcija (dir, filename) -> puna putanja.
               Ako nije zadana, koristi os.path.join.
    """
    if path_join is None:
        import os
        path_join = os.path.join

    racuni = load_racuni(path_join(dir_rac, "RACUNI.DBF"), broj1, broj2, encoding)
    sur_index = load_sur_index(path_join(dir_rac, "SUR.DBF"), encoding)
    partneri_index = load_partneri_index(path_join(dir_baze, "PARTNERI.DBF"), encoding)
    artikli_index = load_artikli_index(path_join(dir_baze, "ARTIKLI.DBF"), encoding)
    usluge_index = load_usluge_index(path_join(dir_baze, "USLUGE.DBF"), encoding)
    eiu1_index = load_eiu1_index(path_join(dir_rac, "EIU_1.DBF"), encoding)

    return DbfSourceData(
        racuni=racuni,
        sur_index=sur_index,
        partneri_index=partneri_index,
        artikli_index=artikli_index,
        usluge_index=usluge_index,
        eiu1_index=eiu1_index,
    )