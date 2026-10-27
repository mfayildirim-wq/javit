# Anbieter und Modellwahl – Design (27.10.2026)

## Ziel

Die Modellwahl in den Einstellungen wird zweistufig: oben der **Anbieter**, darunter die
**Modelle dieses Anbieters**. OpenRouter, DeepSeek, Kimi (Moonshot), GLM (Z.AI), OpenCode, Groq,
Mistral und xAI sind von Haus aus dabei; eigene OpenAI-kompatible Anbieter lassen sich hinzufügen.
Modelllisten kommen live vom Anbieter, sobald ein Schlüssel hinterlegt ist, sonst aus einer
festen Vorschlagsliste. Kostenlose Modelle (OpenRouter „:free“) werden gekennzeichnet.

Nicht enthalten: Preise, Kontextgrößen, Fähigkeiten je Modell; OpenCode-Gratismodelle (laut
OpenCode-Doku nur in OpenCode selbst nutzbar, nicht über die API).

## Kern

### Neues Modul `kern/jarvis/anbieter.py`

```python
@dataclass(frozen=True)
class Anbieter:
    id: str                 # "openrouter"
    name: str               # "OpenRouter"
    praefix: str            # LiteLLM-Präfix: "openrouter" → Modell-ID "openrouter/<modell>"
    schluessel: str | None  # Name des Geheimnisses, z. B. "OPENROUTER_API_KEY"; None bei Ollama
    api_base: str | None    # nur für OpenAI-kompatible Anbieter ohne LiteLLM-Präfix (OpenCode, eigene)
    modelle_url: str | None # Live-Liste; None = nur Vorschläge
    vorschlaege: tuple[tuple[str, str], ...]  # (Modell ohne Präfix, Anzeigename)
    eigen: bool = False
```

Eingebaute Anbieter (Reihenfolge = Anzeige):

| id | praefix | schluessel | api_base | modelle_url |
|---|---|---|---|---|
| ollama | ollama | – | – | (bestehende Ollama-Abfrage) |
| anthropic | anthropic | ANTHROPIC_API_KEY | – | https://api.anthropic.com/v1/models (Header `x-api-key`, `anthropic-version`) |
| openai | openai | OPENAI_API_KEY | – | https://api.openai.com/v1/models |
| gemini | gemini | GEMINI_API_KEY | – | https://generativelanguage.googleapis.com/v1beta/models?key=… |
| openrouter | openrouter | OPENROUTER_API_KEY | – | https://openrouter.ai/api/v1/models (ohne Schlüssel abrufbar) |
| deepseek | deepseek | DEEPSEEK_API_KEY | – | https://api.deepseek.com/models |
| moonshot | moonshot | MOONSHOT_API_KEY | – | https://api.moonshot.ai/v1/models |
| zai | zai | ZAI_API_KEY | – | https://api.z.ai/api/paas/v4/models |
| opencode | openai (übersetzt) | OPENCODE_API_KEY | https://opencode.ai/inference/openai/v1 | https://opencode.ai/inference/v1/models (öffentlich; „-free“/„big-pickle“ ausgefiltert) |
| groq | groq | GROQ_API_KEY | – | https://api.groq.com/openai/v1/models |
| mistral | mistral | MISTRAL_API_KEY | – | https://api.mistral.ai/v1/models |
| xai | xai | XAI_API_KEY | – | https://api.x.ai/v1/models |

Die bisherigen `CLOUD_VORSCHLAEGE` in `llm.py` werden aus den Vorschlagslisten der Anbieter
erzeugt (gleiche IDs, gleiche Namen – keine Änderung für bestehende Einstellungen).

**Modell-IDs** bleiben `anbieter/modell`. Für OpenCode und eigene Anbieter lautet die ID
`opencode/<modell>` bzw. `<eigene-id>/<modell>`; die LLM-Fassade übersetzt beim Aufruf nach
`openai/<modell>` mit `api_base` und `api_key` aus dem Geheimnis (`anbieter.aufruf_parameter(modell)`
→ `{"model": …, "api_base": …, "api_key": …}`). Alles andere geht unverändert an LiteLLM.

**Eigene Anbieter** in `einstellungen.json`:

```json
"anbieter_eigene": [
  {"id": "mein-server", "name": "Mein Server", "api_base": "http://127.0.0.1:1234/v1", "schluessel": "MEIN_SERVER_API_KEY"}
]
```

`id`: `[a-z0-9][a-z0-9_-]{0,30}`, darf keinen eingebauten Anbieter überdecken. `schluessel`
optional (lokale Server ohne Schlüssel). Live-Liste: `<api_base>/models`.

### Live-Modelllisten (`anbieter.modelle_laden(anbieter, schluessel_wert, http)`)

* Zeitlimit 8 s, Fehler → leere Liste + Rückfall auf Vorschläge; Ergebnis 10 Minuten im Speicher
  gecacht (je Anbieter), „neu laden“ umgeht den Cache.
* Antwortformate: OpenAI-Stil `{"data":[{"id":…}]}` (alle außer Gemini/Anthropic); Gemini
  `{"models":[{"name":"models/…","supportedGenerationMethods":[…]}]}` (nur `generateContent`);
  Anthropic `{"data":[{"id":…,"display_name":…}]}`.
* OpenRouter: `kostenlos = pricing.prompt == "0" and pricing.completion == "0"`;
  `werkzeuge = "tools" in supported_parameters`. Andere Anbieter: beides unbekannt (`None`).
* Ausgefiltert: Einbettungs-/Audio-/Bildmodelle nach Namensmustern (`embed`, `tts`, `whisper`,
  `dall-e`, `image`, `moderation`), bei OpenCode zusätzlich `-free` und `big-pickle`.
* Sortierung: Vorschläge zuerst (in Vorschlagsreihenfolge), dann übrige alphabetisch.

### Schnittstelle (nur Erweiterungen, `docs/VERTRAEGE.md` wird ergänzt)

`GET /api/modelle[?anbieter=<id>&neu=1]` →

```json
{
  "aktuell": "gemini/gemini-3.8-flash",
  "anbieter": [{"id": "openrouter", "name": "OpenRouter", "schluessel": "OPENROUTER_API_KEY", "verfuegbar": true, "lokal": false, "eigen": false}],
  "vorschlaege": [{"id": "openrouter/deepseek/deepseek-chat:free", "name": "DeepSeek Chat (free)", "lokal": false, "verfuegbar": true,
                   "anbieter": "openrouter", "kostenlos": true, "werkzeuge": true, "live": true}]
}
```

* Ohne `anbieter`: Verhalten wie bisher (Ollama live + alle Vorschläge), zusätzlich die neuen Felder.
* Mit `anbieter`: nur dieser Anbieter – live, wenn Schlüssel vorhanden (bzw. Liste öffentlich), sonst Vorschläge.
* `verfuegbar` beim Anbieter = Schlüssel gesetzt (Ollama: erreichbar; eigene ohne Schlüssel: true).
* `PUT /api/modelle {modell}` unverändert.
* Eigene Anbieter über `PUT /api/einstellungen {"anbieter_eigene": [...]}` (ganze Liste ersetzt).
  Validierung (ID-Muster, Kollision, URL beginnt mit http) → 400 mit Meldung.

### Fehlermeldung

`_fehler_erklaeren` nennt bei Schlüsselfehlern den Schlüsselnamen des Anbieters aus dem Register
(statt `<PRÄFIX>_API_KEY` zu raten).

## Oberfläche (Einstellungen → Modell)

* **Anbieterleiste** (Chips, `role="radiogroup"`): alle eingebauten + eigenen Anbieter; Chip zeigt
  Punkt grün = Schlüssel da / grau = fehlt; Anbieter des aktiven Modells ist vorausgewählt.
* **Schlüsselfeld** direkt unter der Leiste für den gewählten Anbieter (bestehende `SchluesselZeile`),
  bei Ollama stattdessen Hinweis auf `ollama pull`. Nach dem Speichern wird die Modellliste neu geladen.
* **Modellliste** des gewählten Anbieters (`GET /api/modelle?anbieter=…`), Chips: „lokal“, „Schlüssel
  fehlt“, „kostenlos“, „Werkzeuge“ (nur wenn bekannt); Knopf „Modelle neu laden“ (`&neu=1`);
  Hinweis „Liste vom Anbieter“ bzw. „Vorschläge – Schlüssel hinterlegen für die volle Liste“.
* **Eigene Modell-ID** bleibt (Freitext, beliebiger Anbieter).
* **Anbieter hinzufügen** (aufklappbar): Name, Basis-URL, Schlüsselname (vorbelegt aus dem Namen),
  Schlüssel (optional). Speichern → `PUT /api/einstellungen` + Geheimnis setzen → Chip erscheint und
  wird ausgewählt. Eigene Anbieter haben ein „Entfernen“ am Chip (mit Bestätigung).
* Der Abschnitt „API-Schlüssel“ bleibt für weitere Geheimnisse (z. B. GitHub-Token).

## Tests

* `kern/tests/test_anbieter.py`: Register vollständig und eindeutig; Übersetzung OpenCode/eigene
  Anbieter; Parsen der Antwortformate (OpenAI, Gemini, Anthropic, OpenRouter mit kostenlos/werkzeuge);
  Filter; Cache und „neu“; Fehler → Vorschläge.
* `kern/tests/test_server*.py`: `GET /api/modelle` ohne/mit `anbieter`, neue Felder, Validierung
  `anbieter_eigene`.
* Oberfläche (`einstellungen.test.tsx`): Anbieterwahl lädt gefilterte Liste; Schlüsselstatus;
  „kostenlos“-Chip; Formular eigener Anbieter ruft die API.
* Bestehende Tests zu `CLOUD_VORSCHLAEGE`/`modell_vorschlaege` bleiben grün.

## Dokumentation

README (de/en) Abschnitt „Modelle“: Anbieterwahl, Gratis-Modelle über OpenRouter, OpenCode nur
bezahlte Modelle, eigene Anbieter. `docs/VERTRAEGE.md`, `docs/STAND.md`, `docs/PROTOKOLL.md`.
