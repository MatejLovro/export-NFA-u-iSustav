"""
import_engine.py

Glavna procedura uvoza. Povezuje dbf_reader, firebird_client i config u
tijek opisan u proceduri:

  1. Ucitaj RACUNI.DBF u rasponu broj1-broj2, i sve pomocne DBF tablice.
  2. Za svaki racun:
     a. Ako vec postoji u VPRZG (BRDOK+VK=260) - preskoci.
     b. Nadi/kreiraj kupca u TVRTKE (po OIB-u iz PARTNERI.DBF).
        Ako kupac nema OIB - PREKINI CIJELI IMPORT (ImportAbortError).
     c. Kreiraj zaglavlje u VPRZG.
     d. Za svaku stavku iz SUR.DBF:
        - nadi/kreiraj artikl/uslugu u ROBA
        - kreiraj stavku u VPRST (ukljucujuci dodatni opis iz EIU_1.DBF)
     e. Commit cijelog racuna (glava+stavke = 1 transakcija).
        Ako bilo sto u koraku (b)-(d) pukne (osim nedostajuceg OIB-a) -
        rollback SAMO tog racuna, upisi u log, nastavi na sljedeci racun.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

import dbf_reader
import firebird_client
from config import Config


class ImportAbortError(Exception):
    """Greska koja prekida CIJELI import (npr. kupac bez OIB-a)."""


class ImportRecordError(Exception):
    """Greska vezana uz jedan racun - taj racun se preskace, import se nastavlja."""


@dataclass
class ImportStats:
    uvezeno: int = 0
    preskoceno_postojeci: int = 0
    gresaka: int = 0
    poruke: list[str] = field(default_factory=list)


def _log(stats: ImportStats, log_callback: Callable[[str], None], msg: str) -> None:
    stats.poruke.append(msg)
    log_callback(msg)


# ------------------------------------------------------------------
# Mapiranje sifrarnika (porez, jedinica mjere)
# ------------------------------------------------------------------

def map_porez_sifra(cfg: Config, sif_porez_raw: str) -> str:
    """Mapira DBF sifru poreza u FB sifru poreza. Nestandardne vrijednosti (ne '25' ni '00') tretiraju se kao 25%."""
    sif = (sif_porez_raw or "").strip()
    if sif == cfg.dbfpdv0:
        return cfg.fbpdv0
    return cfg.fbpdv25


def map_porez_stopa(cfg: Config, sif_porez_raw: str) -> int:
    """Mapira DBF sifru poreza u brojcanu stopu (0 ili 25) za VPRST.PORPOS."""
    sif = (sif_porez_raw or "").strip()
    return 0 if sif == cfg.dbfpdv0 else 25


def map_jedinica_mjere(cfg: Config, jed_mjere_raw: str) -> int:
    """Mapira DBF jedinicu mjere u IDMJERE. Sve nepoznato/prazno -> KOM."""
    v = (jed_mjere_raw or "").strip().upper()
    if v == "KOM":
        return cfg.idmjerekom
    if v in ("H", "SAT"):
        return cfg.idmjeresat
    if v == "M":
        return cfg.idmjerem
    if v == "KM":
        return cfg.idmjerekm
    return cfg.idmjerekom


def _safe_int(value: str) -> Optional[int]:
    """Pokusava pretvoriti tekst u int (npr. PTT/postbroj); vraca None ako nije cist broj."""
    v = (value or "").strip()
    return int(v) if v.isdigit() else None


def _to_decimal(value) -> Decimal:
    """Sigurna konverzija DBF numericke vrijednosti (moze biti None) u Decimal."""
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


# ------------------------------------------------------------------
# Korak: kupac (TVRTKE)
# ------------------------------------------------------------------

def resolve_kupac(con, cfg: Config, data: dbf_reader.DbfSourceData, racun: dict) -> int:
    sif_kupca = racun["SIF_KUPCA"]
    partner = data.partneri_index.get(sif_kupca)
    if partner is None:
        raise ImportAbortError(
            f"Racun {racun['BROJ_RACUN']}: kupac sa sifrom '{sif_kupca}' ne postoji u PARTNERI.DBF"
        )

    oib = (partner["KONTO"] or "").strip()
    if not oib:
        raise ImportAbortError(
            f"Racun {racun['BROJ_RACUN']}: kupac '{sif_kupca}' ({partner['NAZIV']}) nema OIB - import zaustavljen."
        )

    def build_fields() -> dict:
        return {
            "IDFIRME": cfg.idfirme,
            "NAZIV1": partner["NAZIV"],
            "NAZIV2": partner["NAZIV2"] or None,
            "OIB": oib,
            "POSTBROJ": _safe_int(partner["PTT"]),
            "POSTMJESTO": partner["MJESTO"] or None,
            "DRZAVA": "Hrvatska",
            "EMAIL": partner["TELEFON2"] or None,
            "KONTAKT": partner["KONT_OSOB"] or None,
            "KUPAC": "T",
            "ERACUN_TIP": "3",
            "TIP": 1,
            "ROKPLACANJA": 7,
            "NAKASI": "T",
            "SISDATE": datetime.now(),
            "SISUSER": cfg.sisuser,
        }

    return firebird_client.get_or_create_tvrtka(con, oib, build_fields)


# ------------------------------------------------------------------
# Korak: artikl/usluga (ROBA)
# ------------------------------------------------------------------

def resolve_stavka_roba(con, cfg: Config, data: dbf_reader.DbfSourceData, stavka: dict) -> tuple[int, str, str]:
    """Vraca (idrobe, naziv, sif_porez) za danu stavku racuna (artikl ili usluga)."""
    sif_uslu = stavka["SIF_USLU"]
    tip_usluge = stavka["TIP_USLU"]

    if tip_usluge == "R":
        source, tip_roba = "artikl", 2
        rec = data.artikli_index.get(sif_uslu)
        if rec is None:
            raise ImportRecordError(f"Artikl sa sifrom '{sif_uslu}' ne postoji u ARTIKLI.DBF")
    elif tip_usluge == "U":
        source, tip_roba = "usluga", 3
        rec = data.usluge_index.get(sif_uslu)
        if rec is None:
            raise ImportRecordError(f"Usluga sa sifrom '{sif_uslu}' ne postoji u USLUGE.DBF")
    else:
        raise ImportRecordError(f"Nepoznat TIP_USLU='{tip_usluge}' u stavci racuna (ocekivano 'R' ili 'U')")

    naziv = rec["NAZIV"]
    jed_mjere = rec["JED_MJERE"]
    sif_porez = rec["SIF_POREZ"]

    def build_fields() -> dict:
        return {
            "IDFIRME": cfg.idfirme,
            "BARCODE": firebird_client.roba_barcode(source, sif_uslu),
            "NAZIVROBE": naziv[:40],
            "SKRNAZIVROBE": naziv[:17],
            "OPISROBE": naziv[:512],
            "IDROBAGRUPE": cfg.idrobagrupe,
            "IDMJERE": map_jedinica_mjere(cfg, jed_mjere),
            "IDROBAFILTER": cfg.idrobafilter,
            "IDRABGRUPE": cfg.idrabgrupe,
            "SIFPOR": map_porez_sifra(cfg, sif_porez),
            "TIP": tip_roba,
            "ZAWEB": "F",
            "AMBALAZA": "F",
            "DEKLARACIJE": "T",
            "NALJEPNICE": "T",
            "NORMATIVZA": 1,
            "SISDATE": datetime.now(),
        }

    idrobe = firebird_client.get_or_create_roba(con, cfg.idfirme, source, sif_uslu, build_fields)
    return idrobe, naziv, sif_porez


# ------------------------------------------------------------------
# Korak: zaglavlje racuna (VPRZG)
# ------------------------------------------------------------------

def create_vprzg(con, cfg: Config, racun: dict, idkupca: int, stavke_dbf: list[dict]) -> int:
    brrac = racun["BROJ_RACUN"]
    danas = date.today()
    sada = datetime.now()

    dan_plac = racun["DAN_PLAC"] or 0
    datval = danas + timedelta(days=dan_plac)

    godina = racun["DATUM"].year if racun["DATUM"] else danas.year
    poziv = f"{brrac}-{godina}"

    iznrab = sum((_to_decimal(s["RABA"]) for s in stavke_dbf), Decimal("0"))
    iznpor = sum((_to_decimal(s["PORE"]) for s in stavke_dbf), Decimal("0"))
    iznos = _to_decimal(racun["IZNOS"])
    iznbezpor = iznos - iznpor

    fields = {
        "IDFIRME": cfg.idfirme,
        "VK": 260,
        "BRDOK": brrac,
        "IDTVRTKE": idkupca,
        "DATDOK": danas,
        "DATDANA": dan_plac,
        "DATVAL": datval,
        "DATISP": racun["DATUM"],
        "IDPOSJED": cfg.idposjed,
        "IDSKLAD": cfg.idsklad,
        "IDROBACJENIK": cfg.idrobacjenik,
        "ZASTAMPU": "F",
        "KNJIZENO": "T",
        "STORNO": "F",
        "MODEL": "02",
        "POZIV": poziv,
        "TIPIFE": 1,
        "KOLONAIFE": 1,
        "IDPLACANJA": 2,
        "DEVIZNI": "F",
        "DATTEC": danas,
        "TECAJ": 1,
        "FISKALNIDATUM": sada,
        "ERACUN_STATUS": -20,
        "ERACUN_TPP": 3,
        "IZMJENA": "T",
        "SISUSER": cfg.sisuser,
        "SISDATE": sada,
        "IZNSAPOR": iznos,
        "IZNRAB": iznrab,
        "IZNPOR": iznpor,
        "IZNBEZPOR": iznbezpor,
    }
    return firebird_client.insert_vprzg(con, fields)


# ------------------------------------------------------------------
# Dodatni opisni tekst iz EIU_1.DBF (vezano preko SUR.DBF:SIFRA_VEZE)
# ------------------------------------------------------------------

def build_opis_robe(naziv: str, stavka: dict, eiu1_index: dict[str, list[str]]) -> str:
    """
    Gradi VPRST:OPISROBE - naziv artikla/usluge, s dodatnim tekstom iz
    EIU_1.DBF nadovezanim preko CR+LF ako SUR.DBF:SIFRA_VEZE nije prazan.

    Ako SIFRA_VEZE postoji ali odgovarajuci EIU_1 zapis ne postoji (poznat
    slucaj - racun 357), po dogovoru se nastavlja SAMO s nazivom, bez
    dodatnog teksta.
    """
    sifra_veze = (stavka.get("SIFRA_VEZE") or "").strip()
    if not sifra_veze:
        return naziv

    dodatni_redovi = eiu1_index.get(sifra_veze)
    if not dodatni_redovi:
        return naziv

    dijelovi = [naziv] + dodatni_redovi
    opis = "\r\n".join(dijelovi)
    return opis[:512]  # VPRST.OPISROBE je VARCHAR(512)


# ------------------------------------------------------------------
# Korak: stavka racuna (VPRST)
# ------------------------------------------------------------------

def create_vprst(con, cfg: Config, data: dbf_reader.DbfSourceData, idvprzg: int, brrac: int, idkupca: int, stavka: dict) -> None:
    idrobe, naziv, sif_porez = resolve_stavka_roba(con, cfg, data, stavka)
    opis_robe = build_opis_robe(naziv, stavka, data.eiu1_index)

    kol = _to_decimal(stavka["KOLICINA"])
    fakcijena = _to_decimal(stavka["PROD_CIJEN"])
    rabpos = _to_decimal(stavka["RABAT"])
    rabcijena = round(fakcijena * rabpos / 100, 3)
    prodcijena = fakcijena - rabcijena

    porpos = map_porez_stopa(cfg, sif_porez)
    prodporcijena = round(prodcijena * (1 + Decimal(porpos) / 100), 2)
    prodporizn = round(kol * prodporcijena, 2)

    fields = {
        "IDVPRZG": idvprzg,
        "IDROBE": idrobe,
        "OPISROBE": opis_robe,
        "IDSKLAD": cfg.idsklad,
        "VK": 260,
        "BRDOK": brrac,
        "DATDOK": date.today(),
        "IDTVRTKE": idkupca,
        "KOL": kol,
        "KOLPAK": 100,
        "FAKCIJENA": fakcijena,
        "RABPOS": rabpos,
        "RABCIJENA": rabcijena,
        "PRODCIJENA": prodcijena,
        "SIFPOR": map_porez_sifra(cfg, sif_porez),
        "PORPOS": porpos,
        "PRODPORCIJENA": prodporcijena,
        "PRODPORIZN": prodporizn,
        "DEVIZNACIJENA": fakcijena,
    }
    firebird_client.insert_vprst(con, fields)


# ------------------------------------------------------------------
# Glavna procedura
# ------------------------------------------------------------------

def run_import(cfg: Config, broj1: int, broj2: int, log_callback: Callable[[str], None] = print) -> ImportStats:
    if broj1 > broj2:
        raise ValueError("broj1 mora biti <= broj2")

    stats = ImportStats()
    _log(stats, log_callback, f"Ucitavam DBF podatke za racune {broj1}-{broj2}...")
    data = dbf_reader.load_all(cfg.dir_rac, cfg.dir_baze, broj1, broj2, cfg.dbf_encoding)
    _log(stats, log_callback, f"Pronadeno {len(data.racuni)} racuna u rasponu.")

    con = firebird_client.connect(cfg)
    try:
        for racun in data.racuni:
            brrac = racun["BROJ_RACUN"]
            try:
                if firebird_client.racun_postoji(con, brrac, vk=260):
                    _log(stats, log_callback, f"Racun {brrac}: vec postoji, preskacem.")
                    stats.preskoceno_postojeci += 1
                    continue

                idkupca = resolve_kupac(con, cfg, data, racun)
                stavke_dbf = dbf_reader.get_stavke_za_racun(data.sur_index, brrac)

                idvprzg = create_vprzg(con, cfg, racun, idkupca, stavke_dbf)
                for stavka in stavke_dbf:
                    create_vprst(con, cfg, data, idvprzg, brrac, idkupca, stavka)

                con.commit()
                stats.uvezeno += 1
                _log(stats, log_callback, f"Racun {brrac}: uvezen (IDVPRZG={idvprzg}, {len(stavke_dbf)} stavki).")

            except ImportAbortError as e:
                con.rollback()
                _log(stats, log_callback, f"PREKID IMPORTA: {e}")
                raise
            except ImportRecordError as e:
                con.rollback()
                _log(stats, log_callback, f"Racun {brrac}: PRESKACEM - {e}")
                stats.gresaka += 1
                continue
            except Exception as e:
                con.rollback()
                _log(stats, log_callback, f"Racun {brrac}: NEOCEKIVANA GRESKA, preskacem - {type(e).__name__}: {e}")
                stats.gresaka += 1
                continue

        _log(
            stats, log_callback,
            f"\nGotovo. Uvezeno: {stats.uvezeno}, preskoceno (vec postoje): {stats.preskoceno_postojeci}, greske: {stats.gresaka}"
        )
        return stats
    finally:
        con.close()