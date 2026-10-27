"""Aufbereitung von Antworttexten für die Sprachausgabe."""

from __future__ import annotations

import pytest

from jarvis.stimme.text import fuer_sprache, in_saetze, url_kurz


def test_markdown_wird_entfernt():
    text = "# Überschrift\nDas ist **fett**, *kursiv*, __auch fett__ und `code`.\n> Zitat"
    assert fuer_sprache(text) == "Überschrift. Das ist fett, kursiv, auch fett und code. Zitat."


def test_listen_und_tabellen():
    text = "Einkauf:\n- Milch\n- Brot\n1. Erstens\n2) Zweitens\n\n| Tag | Temp |\n|---|:--:|\n| Mo | 3 |"
    assert fuer_sprache(text) == "Einkauf: Milch. Brot. Erstens. Zweitens. Tag, Temp. Mo, 3."


def test_emojis_werden_entfernt():
    assert fuer_sprache("Fertig ✅ 🎉 Super 👍🏽 Familie 👨‍👩‍👧 🇩🇪!") == "Fertig Super Familie!"


def test_urls_werden_gekuerzt():
    assert url_kurz("https://www.example.com/a/b?c=1") == "example.com"
    assert fuer_sprache("Siehe https://docs.python.org/3/library/asyncio.html.") == "Siehe docs.python.org."
    assert fuer_sprache("Quelle: [Tagesschau](https://www.tagesschau.de/x)") == "Quelle: Tagesschau."
    assert fuer_sprache("Link: <https://github.com/x/y>") == "Link: github.com."


def test_codebloecke_werden_nicht_vorgelesen():
    text = "Hier das Skript:\n```bash\nrm -rf /tmp/x\n```\nFertig."
    ergebnis = fuer_sprache(text)
    assert "rm -rf" not in ergebnis
    assert "Code siehe Bildschirm" in ergebnis


@pytest.mark.parametrize(
    "eingabe",
    ["Es kostet 1.299,50 € und hat 3,5 % Rabatt.", "Am 24.12.2026 um 18:30 Uhr.", "Version 3.12 ist da."],
)
def test_zahlen_bleiben_erhalten(eingabe):
    assert fuer_sprache(eingabe) == eingabe


def test_say_steuerbefehle_und_html_werden_entfernt():
    ergebnis = fuer_sprache("Hallo [[slnc 2000]] Welt [[rate 500]]<b>!</b>")
    assert "[[" not in ergebnis and "slnc" not in ergebnis and "<b>" not in ergebnis
    assert ergebnis.startswith("Hallo Welt")


def test_leerer_text():
    assert fuer_sprache("") == ""
    assert fuer_sprache("🎉🎉") == ""
    assert fuer_sprache("---") == ""


def test_max_zeichen_kuerzt_an_satzgrenze():
    text = "Erster Satz ist da. " * 20
    kurz = fuer_sprache(text, max_zeichen=100)
    assert len(kurz) <= 100 and kurz.endswith(".")


def test_in_saetze_erstes_stueck_kurz():
    stuecke = in_saetze("Guten Morgen. Heute wird es sonnig. Am Abend regnet es. Morgen schneit es.")
    assert stuecke[0] == "Guten Morgen."
    assert " ".join(stuecke) == "Guten Morgen. Heute wird es sonnig. Am Abend regnet es. Morgen schneit es."
    assert len(stuecke) == 2
    assert in_saetze("Es kostet 3.5 Euro. Gut.") == ["Es kostet 3.5 Euro.", "Gut."]
