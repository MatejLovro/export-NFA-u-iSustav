"""
config.py

Cita param.ini datoteku i izlaze strukturirani, validirani objekt s postavkama
aplikacije. Sve u aplikaciji koje treba postavku iz param.ini, treba je citati
preko ovog modula (a ne direktno preko configparser-a), tako da su greske u
konfiguraciji (nedostajuci kljucevi, krivi tipovi) uhvacene na jednom mjestu,
odmah pri pokretanju aplikacije.

Upotreba:

    from config import load_config

    cfg = load_config("param.ini")
    print(cfg.idposjed)
    print(cfg.dir_rac)
    print(cfg.fdb_path)          # cijela putanja do .FDB datoteke (dir_fdb + fdb_file)
    print(cfg.firebird_dsn)      # host/port:putanja - spremno za firebird.driver.connect()
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Podignuto kad param.ini nedostaje, ne moze se procitati, ili nedostaje
    obavezan kljuc/sekcija."""


@dataclass(frozen=True)
class Config:
    # [fiksne_vrijednosti]
    idposjed: int
    idsklad: int
    sisuser: int
    idfirme: int
    idrobacjenik: int

    idrobagrupe: int
    idrobafilter: int
    idrabgrupe: int

    idmjerekom: int
    idmjeresat: int
    idmjerem: int
    idmjerekm: int

    dbfpdv25: str
    dbfpdv0: str
    fbpdv25: str
    fbpdv0: str

    dir_rac: str
    dir_baze: str
    dir_fdb: str
    fdb_file: str

    dbf_encoding: str

    # [firebird]
    fb_host: str
    fb_port: int
    fb_user: str
    fb_password: str

    # [import]
    batch_size: int

    @property
    def fdb_path(self) -> str:
        """Puna putanja do .FDB datoteke (spaja dir_fdb i fdb_file)."""
        return os.path.join(self.dir_fdb, self.fdb_file)

    @property
    def firebird_dsn(self) -> str:
        """DSN string pogodan za firebird.driver.connect(database=...)."""
        return f"{self.fb_host}/{self.fb_port}:{self.fdb_path}"

    def dbf_path(self, group: str, filename: str) -> str:
        """
        Vraca punu putanju do DBF datoteke.

        group: 'rac' za datoteke iz dir_rac (RACUNI, SUR, EIU_1)
               'baze' za datoteke iz dir_baze (PARTNERI, ARTIKLI, USLUGE)
        filename: npr. 'RACUNI.DBF'
        """
        if group == "rac":
            base = self.dir_rac
        elif group == "baze":
            base = self.dir_baze
        else:
            raise ValueError(f"Nepoznata grupa DBF direktorija: {group!r} (ocekivano 'rac' ili 'baze')")
        return os.path.join(base, filename)


# Obavezni kljucevi po sekciji - ako nesto od ovoga nedostaje u param.ini,
# aplikacija ce odmah javiti jasnu gresku umjesto da pukne kasnije usred uvoza.
_REQUIRED_INT_KEYS_FIKSNE = [
    "idposjed", "idsklad", "sisuser", "idfirme", "idrobacjenik",
    "idrobagrupe", "idrobafilter", "idrabgrupe",
    "idmjerekom", "idmjeresat", "idmjerem", "idmjerekm",
]
_REQUIRED_STR_KEYS_FIKSNE = [
    "dbfpdv25", "dbfpdv0", "fbpdv25", "fbpdv0",
    "dir_rac", "dir_baze", "dir_fdb", "fdb_file",
]


def load_config(path: str = "param.ini") -> Config:
    if not os.path.isfile(path):
        raise ConfigError(f"Konfiguracijska datoteka nije pronadena: {path}")

    parser = configparser.ConfigParser()
    # sprijeci automatsko pretvaranje kljuceva u lowercase da ne iznenadi korisnika
    # (configparser to inace radi po defaultu; ovdje ga svjesno ostavljamo jer su
    # svi nasi kljucevi vec pisani malim slovima - ako se to ikad promijeni,
    # ovdje je mjesto za parser.optionxform = str)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as e:
        raise ConfigError(f"Greska pri citanju {path}: {e}") from e

    if "fiksne_vrijednosti" not in parser:
        raise ConfigError(f"{path}: nedostaje sekcija [fiksne_vrijednosti]")
    if "firebird" not in parser:
        raise ConfigError(f"{path}: nedostaje sekcija [firebird]")

    fiksne = parser["fiksne_vrijednosti"]
    firebird = parser["firebird"]
    imp = parser["import"] if "import" in parser else {}

    missing = [k for k in _REQUIRED_INT_KEYS_FIKSNE + _REQUIRED_STR_KEYS_FIKSNE if k not in fiksne]
    if missing:
        raise ConfigError(
            f"{path}: nedostaju obavezni kljucevi u [fiksne_vrijednosti]: {', '.join(missing)}"
        )

    def get_int(section, key, default=None):
        try:
            return section.getint(key) if hasattr(section, "getint") else int(section[key])
        except (ValueError, KeyError) as e:
            if default is not None:
                return default
            raise ConfigError(f"{path}: kljuc '{key}' mora biti cijeli broj, procitano: {section.get(key)!r}") from e

    try:
        return Config(
            idposjed=get_int(fiksne, "idposjed"),
            idsklad=get_int(fiksne, "idsklad"),
            sisuser=get_int(fiksne, "sisuser"),
            idfirme=get_int(fiksne, "idfirme"),
            idrobacjenik=get_int(fiksne, "idrobacjenik"),
            idrobagrupe=get_int(fiksne, "idrobagrupe"),
            idrobafilter=get_int(fiksne, "idrobafilter"),
            idrabgrupe=get_int(fiksne, "idrabgrupe"),
            idmjerekom=get_int(fiksne, "idmjerekom"),
            idmjeresat=get_int(fiksne, "idmjeresat"),
            idmjerem=get_int(fiksne, "idmjerem"),
            idmjerekm=get_int(fiksne, "idmjerekm"),
            dbfpdv25=fiksne["dbfpdv25"].strip(),
            dbfpdv0=fiksne["dbfpdv0"].strip(),
            fbpdv25=fiksne["fbpdv25"].strip(),
            fbpdv0=fiksne["fbpdv0"].strip(),
            dir_rac=fiksne["dir_rac"].strip(),
            dir_baze=fiksne["dir_baze"].strip(),
            dir_fdb=fiksne["dir_fdb"].strip(),
            fdb_file=fiksne["fdb_file"].strip(),
            dbf_encoding=fiksne.get("dbf_encoding", "cp852").strip(),
            fb_host=firebird.get("host", "localhost").strip(),
            fb_port=get_int(firebird, "port", default=3050),
            fb_user=firebird.get("user", "SYSDBA").strip(),
            fb_password=firebird.get("password", fallback=None) or firebird.get("password", ""),
            batch_size=int(imp.get("batch_size", 500)) if imp else 500,
        )
    except KeyError as e:
        raise ConfigError(f"{path}: nedostaje ocekivani kljuc {e}") from e


if __name__ == "__main__":
    # brzi rucni test: python config.py
    cfg = load_config("param.ini")
    print("idposjed         =", cfg.idposjed)
    print("idmjerekom        =", cfg.idmjerekom)
    print("dir_rac           =", cfg.dir_rac)
    print("dbf_path(RACUNI)  =", cfg.dbf_path("rac", "RACUNI.DBF"))
    print("dbf_path(PARTNERI)=", cfg.dbf_path("baze", "PARTNERI.DBF"))
    print("fdb_path          =", cfg.fdb_path)
    print("firebird_dsn      =", cfg.firebird_dsn)
    print("dbf_encoding      =", cfg.dbf_encoding)
