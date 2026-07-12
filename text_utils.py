"""
text_utils.py

Stari Clipper podaci koriste povremeno tzv. "YUSCII" konvenciju iz doba
matricnih pisaca, gdje su hrvatska dijakriticka slova zamijenjena obicnim
ASCII znakovima:

    ~ -> c (c kvacica)      ^ -> C (C kvacica)
    { -> s (s kvacica)      [ -> S (S kvacica)
    } -> c (c kvacica dugo) ] -> C (C kvacica dugo)
    ` -> z (z kvacica)      | -> d (d kvacica, "dj")
    @ -> Z (Z kvacica)      [samo kad NIJE doslovni "at" znak]

Napomena: podaci su MIJESANI - dio zapisa vec ima ispravno dekodirana
dijakriticka slova (npr. kroz cp852), a dio koristi gornju zamjensku shemu.
Konverzija je bezopasna za "ispravne" zapise jer se zamjenjuju samo znakovi
~ ^ { } [ ] ` | @ koji se u normalnom hrvatskom poslovnom tekstu inace ne
pojavljuju.

Znak '@' je poseban slucaj: koristi se i kao zamjena za "Z kvacica" (npr.
"@eljko" -> "Zeljko") ALI i kao doslovni "at" znak u tehnickim opisima
(npr. "1600X1200@68Hz"). Po dogovoru s korisnikom aplikacije, '@' se
konvertira SVUGDJE OSIM u polju PARTNERI.DBF:TELEFON2 (gdje se nalaze
email adrese, pa '@' tamo mora ostati doslovni 'at' znak).
"""

from __future__ import annotations

import re

# Osnovna mapa zamjenskih znakova -> ispravna hrvatska slova.
# Redoslijed namjerno ne igra ulogu jer je preslikavanje 1-na-1 po znaku.
_YUSCII_MAP = {
    "~": "č",
    "^": "Č",
    "{": "š",
    "[": "Š",
    "}": "ć",
    "]": "Ć",
    "`": "ž",
    "|": "đ",
}

# '@' je poseban slucaj - drzimo ga odvojeno od osnovne mape jer se
# konverzija za njega moze iskljuciti po pojedinom polju (vidi convert_at
# parametar u convert_yuscii).
_AT_REPLACEMENT = "Ž"

_TRANSLATE_TABLE = str.maketrans(_YUSCII_MAP)
_TRANSLATE_TABLE_WITH_AT = str.maketrans({**_YUSCII_MAP, "@": _AT_REPLACEMENT})


def convert_yuscii(text: str | None, convert_at: bool = True) -> str:
    """
    Konvertira YUSCII zamjenske znakove u ispravna hrvatska dijakriticka slova.

    Args:
        text: ulazni tekst (moze biti None - tada se vraca prazan string)
        convert_at: ako je True (default), '@' se konvertira u 'Ž'.
                    Postavite na False za polja gdje '@' mora ostati doslovni
                    znak (trenutno jedino PARTNERI.DBF:TELEFON2 - email adrese).

    Returns:
        Konvertirani tekst. Ako 'text' nije string (npr. None, broj, datum),
        vraca se nepromijenjen bez greske - korisno jer dbfread ponekad vraca
        None za prazna polja.
    """
    if not isinstance(text, str):
        return text
    table = _TRANSLATE_TABLE_WITH_AT if convert_at else _TRANSLATE_TABLE
    return text.translate(table)


_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def convert_yuscii_smart(text: str | None) -> str:
    """
    Kao convert_yuscii(), ali '@' se konvertira u 'Ž' SAMO ako NIJE dio
    prepoznatljive email adrese (oblika rijec@rijec.tld). Koristi se za
    polja koja mijesaju slobodni tekst (gdje '@' moze biti zamjena za
    slovo Ž, npr. imena) s prigodno upisanim email adresama (gdje '@'
    mora ostati doslovan) - npr. PARTNERI.DBF:KONT_OSOB.
    """
    if not isinstance(text, str):
        return text

    emails: list[str] = []

    def _mask(m: re.Match) -> str:
        emails.append(m.group(0))
        return f"\x00EMAIL{len(emails) - 1}\x00"

    masked = _EMAIL_PATTERN.sub(_mask, text)
    converted = convert_yuscii(masked, convert_at=True)
    for i, email in enumerate(emails):
        converted = converted.replace(f"\x00EMAIL{i}\x00", email)
    return converted