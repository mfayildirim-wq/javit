"""Text für die Sprachausgabe aufbereiten: Markdown, Emojis, URLs, Code, Steuerbefehle."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

_CODEBLOCK = re.compile(r"```.*?(?:```|$)", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_BILD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]*)[^)]*\)")
_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.I)
_HTML = re.compile(r"</?[a-zA-Z][^>\n]{0,200}>")
_UEBERSCHRIFT = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*(.*?)[ \t]*#*[ \t]*$", re.M)
_ZITAT = re.compile(r"^[ \t]{0,3}>[ \t]?", re.M)
_AUFZAEHLUNG = re.compile(r"^[ \t]*(?:[-*+•]|\d{1,3}[.)])\s+(?=\S)", re.M)
_TRENNLINIE = re.compile(r"^[ \t]*(?:[-*_][ \t]*){3,}$", re.M)
_TABELLEN_TRENNER = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$", re.M)
_FETT = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_KURSIV_STERN = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_KURSIV_STRICH = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_DURCHGESTRICHEN = re.compile(r"~~(.+?)~~", re.S)
_SAY_BEFEHL = re.compile(r"\[\[.*?\]\]", re.S)  # eingebettete say-Befehle wie [[slnc 500]]


def _ist_emoji(zeichen: str) -> bool:
    cp = ord(zeichen)
    if cp in (0x200D, 0xFE0F, 0xFE0E, 0x20E3):  # ZWJ, Variantenselektoren, Tastenkappe
        return True
    if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x1F1E6 <= cp <= 0x1F1FF:
        return True
    if 0xE0020 <= cp <= 0xE007F:  # Tag-Zeichen (Flaggen)
        return True
    if 0x2B00 <= cp <= 0x2BFF or 0x2190 <= cp <= 0x21FF and cp not in (0x2192,):
        return True
    return unicodedata.category(zeichen) == "So" and cp > 0x2000


def emojis_entfernen(text: str) -> str:
    text = text.replace("→", " zu ").replace("⇒", " zu ")
    return "".join(z for z in text if not _ist_emoji(z))


def url_kurz(url: str) -> str:
    """https://www.example.com/pfad?x=1 → „example.com“."""
    roh = url if "://" in url else "http://" + url
    try:
        host = urlparse(roh).hostname or ""
    except ValueError:
        host = ""
    host = host.removeprefix("www.")
    return host or "Link"


def fuer_sprache(text: str, max_zeichen: int | None = None) -> str:
    """Bereitet Text (oft Markdown) zum Vorlesen auf. Zahlen bleiben unverändert."""
    if not text:
        return ""
    t = unicodedata.normalize("NFC", str(text))
    t = _CODEBLOCK.sub(" (Code siehe Bildschirm.) ", t)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _BILD.sub(r"\1", t)
    t = _LINK.sub(lambda m: m.group(1) if not _URL.fullmatch(m.group(1)) else url_kurz(m.group(1)), t)
    t = _AUTOLINK.sub(lambda m: url_kurz(m.group(1)), t)
    t = _URL.sub(lambda m: url_kurz(m.group(0).rstrip(".,;:!?")), t)
    t = _HTML.sub(" ", t)
    t = _SAY_BEFEHL.sub(" ", t)
    t = t.replace("[[", " ").replace("]]", " ")
    t = _TABELLEN_TRENNER.sub("", t)
    t = _TRENNLINIE.sub("", t)
    t = _UEBERSCHRIFT.sub(lambda m: (m.group(1).rstrip(".:!?") + ".") if m.group(1) else "", t)
    t = _ZITAT.sub("", t)
    t = _AUFZAEHLUNG.sub("", t)
    t = _FETT.sub(r"\2", t)
    t = _DURCHGESTRICHEN.sub(r"\1", t)
    t = _KURSIV_STERN.sub(r"\1", t)
    t = _KURSIV_STRICH.sub(r"\1", t)
    # Tabellenzeilen: | a | b | → a, b
    t = re.sub(r"^[ \t]*\|(.*)\|[ \t]*$", lambda m: ", ".join(z.strip() for z in m.group(1).split("|") if z.strip()) + ".", t, flags=re.M)
    t = emojis_entfernen(t)
    t = t.replace("*", " ").replace("#", " ").replace("|", ", ")
    # Zeilen ohne Satzzeichen am Ende bekommen einen Punkt → natürliche Pausen beim Vorlesen
    zeilen = [z.strip() for z in t.splitlines()]
    zeilen = [z for z in zeilen if z]
    zeilen = [z if re.search(r"[.!?:;,…][\"'»“”)]?$", z) else z + "." for z in zeilen]
    t = " ".join(zeilen)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    t = re.sub(r"([.!?])\.+", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if max_zeichen and len(t) > max_zeichen:
        schnitt = t[:max_zeichen]
        ende = max(schnitt.rfind(". "), schnitt.rfind("! "), schnitt.rfind("? "))
        t = (schnitt[: ende + 1] if ende > max_zeichen // 2 else schnitt.rstrip() + " …")
    return t


def in_saetze(text: str, max_laenge: int = 300) -> list[str]:
    """Teilt Text in vorlesbare Stücke (Satzgrenzen), damit die Ausgabe früh beginnen kann."""
    saetze = re.split(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ0-9\"„(])", text.strip())
    # Das erste Stück bleibt kurz (schneller Start), danach wird zusammengefasst.
    stuecke: list[str] = []
    aktuell = ""
    for s in saetze:
        s = s.strip()
        if not s:
            continue
        if not aktuell:
            aktuell = s
        elif len(aktuell) + 1 + len(s) <= max_laenge and len(stuecke) > 0:
            aktuell += " " + s
        else:
            stuecke.append(aktuell)
            aktuell = s
    if aktuell:
        stuecke.append(aktuell)
    return stuecke
