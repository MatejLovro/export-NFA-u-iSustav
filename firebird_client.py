"""
firebird_client.py

Sve firebird-specificne operacije potrebne za uvoz:
  - spajanje na bazu
  - dohvat sljedece vrijednosti generatora (GENIDTVRTKE, GENIDVPRZG, GENIDVPRST, GENIDROBE)
  - find-or-create za TVRTKE (po OIB-u) i ROBA (po BARCODE+IDFIRME)
  - provjera je li racun vec uvezen (VPRZG: BRDOK+VK)
  - insert za VPRZG i VPRST

NAPOMENA o BARCODE prefiksu: FB:ROBA ima unique index na (IDFIRME, BARCODE)
BEZ polja TIP. Buduci da se iste sifre znaju pojaviti i u ARTIKLI.DBF i u
USLUGE.DBF za posve razlicite proizvode/usluge (potvrdeno na stvarnim
podacima - 25 poznatih preklapanja), BARCODE se sprema s prefiksom ovisno
o izvoru:
    artikl (TIP=2)  -> BARCODE = "A-" + sifra
    usluga (TIP=3)  -> BARCODE = "U-" + sifra
Ovo garantira jedinstvenost bez obzira na tip.
"""

from __future__ import annotations

from typing import Callable, Optional

from firebird.driver import connect as fb_connect
from firebird.driver import Connection

from config import Config


class FirebirdError(Exception):
    """Podignuto za sve ocekivane greske pri radu s Firebird bazom."""


# ------------------------------------------------------------------
# Konekcija
# ------------------------------------------------------------------

def connect(cfg: Config) -> Connection:
    """Spaja se na Firebird bazu koristeci postavke iz Config objekta."""
    try:
        return fb_connect(cfg.firebird_dsn, user=cfg.fb_user, password=cfg.fb_password)
    except Exception as e:
        raise FirebirdError(f"Ne mogu se spojiti na Firebird bazu ({cfg.firebird_dsn}): {e}") from e


# ------------------------------------------------------------------
# Generatori
# ------------------------------------------------------------------

def next_id(con: Connection, generator_name: str) -> int:
    """Vraca sljedecu vrijednost imenovanog generatora (sekvence)."""
    cur = con.cursor()
    cur.execute(f"SELECT NEXT VALUE FOR {generator_name} FROM RDB$DATABASE")
    row = cur.fetchone()
    return row[0]


# ------------------------------------------------------------------
# Generalni insert helper
# ------------------------------------------------------------------

def _insert_row(con: Connection, table: str, fields: dict) -> None:
    """
    Izvrsava INSERT INTO table (...) VALUES (...) za dani rjecnik polje->vrijednost.
    Ne radi commit - to je odgovornost pozivatelja (transakcija = 1 cijeli racun).
    """
    columns = list(fields.keys())
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    values = [fields[c] for c in columns]
    cur = con.cursor()
    try:
        cur.execute(sql, values)
    except Exception as e:
        raise FirebirdError(f"Greska pri insertu u {table}: {e}\nSQL: {sql}\nVrijednosti: {values}") from e


# ------------------------------------------------------------------
# TVRTKE - find-or-create po OIB-u
# ------------------------------------------------------------------

def find_tvrtka_by_oib(con: Connection, oib: str) -> Optional[int]:
    """Vraca IDTVRTKE ako partner s danim OIB-om vec postoji, inace None."""
    cur = con.cursor()
    cur.execute("SELECT IDTVRTKE FROM TVRTKE WHERE OIB = ?", (oib,))
    row = cur.fetchone()
    return row[0] if row else None


def create_tvrtka(con: Connection, fields: dict) -> int:
    """
    Kreira novi zapis u TVRTKE. 'fields' NE smije sadrzavati IDTVRTKE - ovaj
    ce ga sam dodijeliti preko GENIDTVRTKE i vratiti novi ID.
    """
    new_id = next_id(con, "GENIDTVRTKE")
    fields = dict(fields)
    fields["IDTVRTKE"] = new_id
    _insert_row(con, "TVRTKE", fields)
    return new_id


def get_or_create_tvrtka(con: Connection, oib: str, build_fields: Callable[[], dict]) -> int:
    """
    Trazi tvrtku po OIB-u. Ako ne postoji, gradi polja preko build_fields()
    (poziva se samo ako je stvarno potrebno) i kreira novi zapis.
    Vraca IDTVRTKE (postojeci ili novododijeljeni).
    """
    existing = find_tvrtka_by_oib(con, oib)
    if existing is not None:
        return existing
    return create_tvrtka(con, build_fields())


# ------------------------------------------------------------------
# ROBA - find-or-create po BARCODE (s prefiksom) + IDFIRME
# ------------------------------------------------------------------

def roba_barcode(source: str, sifra: str) -> str:
    """
    Gradi BARCODE vrijednost za ROBA s prefiksom ovisno o izvoru, da se
    izbjegne sukob sifri artikala i usluga (vidi napomenu na vrhu datoteke).

    source: 'artikl' ili 'usluga'
    """
    if source == "artikl":
        prefix = "A-"
    elif source == "usluga":
        prefix = "U-"
    else:
        raise ValueError(f"Nepoznat source: {source!r} (ocekivano 'artikl' ili 'usluga')")
    return f"{prefix}{sifra}"


def find_roba(con: Connection, idfirme: int, barcode: str) -> Optional[int]:
    """Vraca IDROBE ako artikl/usluga s danim (IDFIRME, BARCODE) vec postoji, inace None."""
    cur = con.cursor()
    cur.execute("SELECT IDROBE FROM ROBA WHERE IDFIRME = ? AND BARCODE = ?", (idfirme, barcode))
    row = cur.fetchone()
    return row[0] if row else None

def find_roba_with_tip(con: Connection, idfirme: int, barcode: str) -> Optional[tuple[int, int]]:
    """Vraca (IDROBE, TIP) ako zapis s danim (IDFIRME, BARCODE) postoji, inace None."""
    cur = con.cursor()
    cur.execute("SELECT IDROBE, TIP FROM ROBA WHERE IDFIRME = ? AND BARCODE = ?", (idfirme, barcode))
    row = cur.fetchone()
    return (row[0], row[1]) if row else None


def create_roba(con: Connection, fields: dict) -> int:
    """
    Kreira novi zapis u ROBA. 'fields' NE smije sadrzavati IDROBE - ovaj
    ce ga sam dodijeliti preko GENIDROBE i vratiti novi ID.
    """
    new_id = next_id(con, "GENIDROBE")
    fields = dict(fields)
    fields["IDROBE"] = new_id
    _insert_row(con, "ROBA", fields)
    return new_id

def get_or_create_roba(
    con: Connection, idfirme: int, source: str, sifra: str, build_fields: Callable[[], dict]
) -> int:
    """
    Trazi robu u dva koraka, pa ako ne nadje - kreira novu (s prefiksiranim BARCODE):

    1. NAJPRIJE trazi "goli" kod bez prefiksa (BARCODE=sifra) - radi
       kompatibilnosti s postojecim FB:ROBA zapisima koji su nastali PRIJE
       ovog alata (npr. rucno uneseni, bez A-/U- prefiksa). Ako se nade i
       TIP se poklapa s ocekivanim (artikl=2 / usluga=3), koristi taj zapis.
       Ako TIP NE odgovara (goli kod je "zauzet" od strane drugog tipa robe
       - isti problem kao sukob sifri u DBF-u), preskace se i ide na korak 2.
    2. Ako korak 1 ne uspije, trazi/kreira PREFIKSIRANI kod (A-sifra ili
       U-sifra) kao dosad - ovo je "namespace" koji ovaj alat sam kontrolira,
       pa tu sukoba ne moze biti.

    Vraca IDROBE (postojeci ili novododijeljeni).
    """
    tip_roba = 2 if source == "artikl" else 3

    goli = find_roba_with_tip(con, idfirme, sifra)
    if goli is not None:
        idrobe, postojeci_tip = goli
        if postojeci_tip == tip_roba:
            return idrobe
        # goli kod postoji, ali je krivog tipa - pada na prefiksiranu pretragu

    barcode = roba_barcode(source, sifra)
    existing = find_roba(con, idfirme, barcode)
    if existing is not None:
        return existing
    return create_roba(con, build_fields())


# ------------------------------------------------------------------
# VPRZG - provjera duplikata i insert
# ------------------------------------------------------------------

def racun_postoji(con: Connection, brdok: int, vk: int = 260) -> bool:
    """Vraca True ako racun s danim BRDOK i VK vec postoji u VPRZG."""
    cur = con.cursor()
    cur.execute("SELECT IDVPRZG FROM VPRZG WHERE BRDOK = ? AND VK = ?", (brdok, vk))
    return cur.fetchone() is not None


def insert_vprzg(con: Connection, fields: dict) -> int:
    """
    Kreira novi zapis u VPRZG. 'fields' NE smije sadrzavati IDVPRZG - ovaj
    ce ga sam dodijeliti preko GENIDVPRZG i vratiti novi ID.
    """
    new_id = next_id(con, "GENIDVPRZG")
    fields = dict(fields)
    fields["IDVPRZG"] = new_id
    _insert_row(con, "VPRZG", fields)
    return new_id


# ------------------------------------------------------------------
# VPRST - insert stavke
# ------------------------------------------------------------------

def insert_vprst(con: Connection, fields: dict) -> int:
    """
    Kreira novi zapis u VPRST. 'fields' NE smije sadrzavati IDVPRST - ovaj
    ce ga sam dodijeliti preko GENIDVPRST i vratiti novi ID.
    """
    new_id = next_id(con, "GENIDVPRST")
    fields = dict(fields)
    fields["IDVPRST"] = new_id
    _insert_row(con, "VPRST", fields)
    return new_id


if __name__ == "__main__":
    # Rucni test konekcije + generatora - koristi param.ini iz istog foldera.
    # Pokrenite s: python firebird_client.py
    from config import load_config

    cfg = load_config("param.ini")
    con = connect(cfg)
    try:
        print("Spojeno. Testiram generatore:")
        for gen in ("GENIDTVRTKE", "GENIDVPRZG", "GENIDVPRST", "GENIDROBE"):
            print(f"  next_id({gen}) = {next_id(con, gen)}")
        con.rollback()  # generator NEXT VALUE se ne moze "vratiti", ali barem ne diramo podatke
        print("\nTestiram racun_postoji za BRDOK=999999 (ne bi smio postojati):")
        print(" ", racun_postoji(con, 999999))
    finally:
        con.close()
