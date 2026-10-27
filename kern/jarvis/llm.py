"""Einzige Fassade zu LiteLLM: Streaming mit Werkzeugaufrufen, Einbettungen, Modell-Liste.

- Gestreamte tool_call-Deltas werden korrekt zusammengesetzt (pro index/id).
- Modelle ohne natives Tool-Calling bekommen einen Fallback-Prompt mit JSON-Werkzeugformat;
  die JSON-Antwort wird geparst und wie native Werkzeugaufrufe zurückgegeben.
- Kein anbieterspezifisches SDK – alles über LiteLLM; Ollama-Modelle über /api/tags.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import anbieter as anbieter_register
from .konfig import Einstellungen


class LLMFehler(RuntimeError):
    """Fehler beim Modellaufruf mit nutzerfreundlicher Meldung."""


@dataclass
class WerkzeugAufruf:
    id: str
    name: str
    argumente: dict[str, Any] = field(default_factory=dict)
    roh: str = ""
    fehler: str | None = None

    def als_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.roh or json.dumps(self.argumente, ensure_ascii=False)},
        }


def _feld(obj: Any, name: str) -> Any:
    """Zugriff auf Felder von LiteLLM-Objekten oder dicts."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def argumente_parsen(roh: Any) -> tuple[dict[str, Any], str | None]:
    """Parst Werkzeugargumente; gibt (argumente, fehler) zurück."""
    if isinstance(roh, dict):
        return roh, None
    text = (roh or "").strip()
    if not text:
        return {}, None
    try:
        wert = json.loads(text)
    except json.JSONDecodeError:
        # Reparaturversuch: Codeblock / Text drumherum entfernen
        kandidat = re.sub(r"^```(?:json)?|```$", "", text).strip()
        start, ende = kandidat.find("{"), kandidat.rfind("}")
        try:
            wert = json.loads(kandidat[start : ende + 1]) if start >= 0 and ende > start else None
        except json.JSONDecodeError:
            wert = None
        if wert is None:
            return {}, f"Argumente sind kein gültiges JSON: {text[:200]}"
    if not isinstance(wert, dict):
        return {}, "Argumente müssen ein JSON-Objekt sein."
    return wert, None


class ToolCallSammler:
    """Setzt gestreamte tool_call-Deltas zu vollständigen Aufrufen zusammen."""

    def __init__(self) -> None:
        self._eintraege: dict[Any, dict[str, Any]] = {}
        self._reihenfolge: list[Any] = []

    def hinzufuegen(self, tool_calls: Any) -> None:
        for tc in tool_calls or []:
            index = _feld(tc, "index")
            tc_id = _feld(tc, "id")
            schluessel: Any = index
            if schluessel is None:
                schluessel = tc_id if tc_id else (self._reihenfolge[-1] if self._reihenfolge else 0)
            vorhanden = self._eintraege.get(schluessel)
            if vorhanden and tc_id and vorhanden["id"] and tc_id != vorhanden["id"]:
                # gleicher Index, aber neue ID → neuer Aufruf (manche Anbieter setzen index immer 0)
                schluessel = f"{schluessel}:{tc_id}"
                vorhanden = self._eintraege.get(schluessel)
            if vorhanden is None:
                vorhanden = {"id": None, "name": "", "argumente": ""}
                self._eintraege[schluessel] = vorhanden
                self._reihenfolge.append(schluessel)
            if tc_id:
                vorhanden["id"] = tc_id
            funktion = _feld(tc, "function")
            name = _feld(funktion, "name")
            if name:
                if not vorhanden["name"] or vorhanden["name"] == name:
                    vorhanden["name"] = name
                else:
                    vorhanden["name"] += name
            argumente = _feld(funktion, "arguments")
            if isinstance(argumente, dict):
                vorhanden["argumente"] = json.dumps(argumente, ensure_ascii=False)
            elif argumente:
                vorhanden["argumente"] += argumente

    def ergebnis(self) -> list[WerkzeugAufruf]:
        aufrufe = []
        for schluessel in self._reihenfolge:
            e = self._eintraege[schluessel]
            if not e["name"]:
                continue
            argumente, fehler = argumente_parsen(e["argumente"])
            aufrufe.append(
                WerkzeugAufruf(
                    id=e["id"] or f"aufruf_{uuid.uuid4().hex[:12]}",
                    name=e["name"],
                    argumente=argumente,
                    roh=e["argumente"],
                    fehler=fehler,
                )
            )
        return aufrufe


# ---------------------------------------------------------------------------
# Fallback-Format für Modelle ohne Tool-Calling
# ---------------------------------------------------------------------------
def werkzeug_prompt(werkzeuge: list[dict[str, Any]]) -> str:
    zeilen = [
        "## Werkzeuge",
        "Du kannst die folgenden Werkzeuge verwenden:",
    ]
    for w in werkzeuge:
        f = w.get("function", w)
        parameter = json.dumps(f.get("parameters", {}).get("properties", {}), ensure_ascii=False)
        pflicht = f.get("parameters", {}).get("required", [])
        zeilen.append(f"- {f['name']}: {f.get('description', '')}\n  Parameter: {parameter}"
                      + (f" (Pflicht: {', '.join(pflicht)})" if pflicht else ""))
    zeilen += [
        "",
        "Wenn du ein Werkzeug benutzen willst, antworte AUSSCHLIESSLICH mit einem JSON-Objekt "
        "in genau diesem Format und ohne weiteren Text:",
        '{"werkzeug": "<name>", "argumente": {<parameter>}}',
        "Für mehrere Werkzeuge gleichzeitig: eine JSON-Liste solcher Objekte.",
        "Du erhältst das Ergebnis danach als Nachricht „[Ergebnis von <name>]“. "
        "Wenn du kein Werkzeug brauchst, antworte ganz normal in Textform.",
    ]
    return "\n".join(zeilen)


_NAME_SCHLUESSEL = ("werkzeug", "tool", "name", "function", "funktion")
_ARG_SCHLUESSEL = ("argumente", "arguments", "parameters", "parameter", "args", "input")


def _normiert(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def werkzeugname_aufloesen(name: str, erlaubt: set[str]) -> str | None:
    """Exakter Name oder – bei kleinen Schreibfehlern des Modells wie ``dateisystem_listallowed_directories``
    statt ``dateisystem__list_allowed_directories`` – der eindeutige Treffer ohne Unterstriche/Groß-Klein."""
    if not name:
        return None
    if not erlaubt or name in erlaubt:
        return name
    treffer = [n for n in erlaubt if _normiert(n) == _normiert(name)]
    return treffer[0] if len(treffer) == 1 else None


# Aufrufformat von DeepSeek/GLM („DSML“), das manche Modelle als Text ausgeben, z. B.
# <｜DSML｜invoke name="x"><｜DSML｜parameter name="a">1</｜DSML｜parameter></｜DSML｜invoke>
_DSML = r"<\s*/?\s*[｜|]\s*DSML\s*[｜|]"
_DSML_INVOKE = re.compile(
    r"<\s*[｜|]\s*DSML\s*[｜|]\s*invoke\s+name=\"([^\"]+)\"\s*>(.*?)(?:<\s*/\s*[｜|]\s*DSML\s*[｜|]\s*invoke\s*>|$)", re.S
)
_DSML_PARAM = re.compile(
    r"<\s*[｜|]\s*DSML\s*[｜|]\s*parameter\s+name=\"([^\"]+)\"\s*>(.*?)<\s*/\s*[｜|]\s*DSML\s*[｜|]\s*parameter\s*>", re.S
)
_DSML_BLOCK = re.compile(r"<\s*[｜|]\s*DSML\s*[｜|]\s*(?:function_)?calls\s*>.*?(?:<\s*/\s*[｜|]\s*DSML\s*[｜|]\s*(?:function_)?calls\s*>|$)", re.S)
_DSML_TAG = re.compile(_DSML + r"[^>]*>")


def enthaelt_dsml(text: str) -> bool:
    return bool(re.search(_DSML, text))


def dsml_aufrufe_parsen(text: str, erlaubt: set[str]) -> tuple[str, list[WerkzeugAufruf]]:
    """Werkzeugaufrufe im DSML-Format aus dem Text; das Markup wird in jedem Fall entfernt."""
    if not enthaelt_dsml(text):
        return text, []
    aufrufe: list[WerkzeugAufruf] = []
    for m in _DSML_INVOKE.finditer(text):
        name = werkzeugname_aufloesen(m.group(1).strip(), erlaubt)
        if not name:
            continue
        argumente: dict[str, Any] = {}
        for pm in _DSML_PARAM.finditer(m.group(2)):
            wert = pm.group(2).strip()
            try:
                argumente[pm.group(1).strip()] = json.loads(wert)
            except json.JSONDecodeError:
                argumente[pm.group(1).strip()] = wert
        aufrufe.append(WerkzeugAufruf(id=f"aufruf_{uuid.uuid4().hex[:12]}", name=name, argumente=argumente,
                                      roh=json.dumps(argumente, ensure_ascii=False)))
    rest = _DSML_BLOCK.sub("", text)
    rest = _DSML_INVOKE.sub("", rest)
    rest = _DSML_TAG.sub("", rest)
    return rest.strip(), aufrufe


def _als_aufruf(obj: Any, erlaubt: set[str]) -> WerkzeugAufruf | None:
    if not isinstance(obj, dict):
        return None
    name = next((obj[k] for k in _NAME_SCHLUESSEL if isinstance(obj.get(k), str)), None)
    if isinstance(obj.get("function"), dict):  # OpenAI-ähnliches Format
        name = obj["function"].get("name")
        obj = {"argumente": obj["function"].get("arguments", {})}
    name = werkzeugname_aufloesen(name or "", erlaubt)
    if not name:
        return None
    argumente: Any = next((obj[k] for k in _ARG_SCHLUESSEL if k in obj), {})
    argumente, fehler = argumente_parsen(argumente) if not isinstance(argumente, dict) else (argumente, None)
    return WerkzeugAufruf(
        id=f"aufruf_{uuid.uuid4().hex[:12]}",
        name=name,
        argumente=argumente,
        roh=json.dumps(argumente, ensure_ascii=False),
        fehler=fehler,
    )


def werkzeug_aufrufe_parsen(text: str, erlaubte_namen: set[str] | None = None) -> tuple[str, list[WerkzeugAufruf]]:
    """Sucht JSON- (oder DSML-)Werkzeugaufrufe im Text. Gibt (Resttext, Aufrufe) zurück."""
    erlaubt = erlaubte_namen or set()
    if enthaelt_dsml(text):
        return dsml_aufrufe_parsen(text, erlaubt)
    kandidaten: list[tuple[int, int, str]] = []
    for m in re.finditer(r"```(?:json|JSON)?\s*(.*?)```", text, re.S):
        kandidaten.append((m.start(), m.end(), m.group(1)))
    decoder = json.JSONDecoder()
    if not kandidaten:
        for start, zeichen in enumerate(text):
            if zeichen in "{[":
                try:
                    _, laenge = decoder.raw_decode(text[start:])
                except json.JSONDecodeError:
                    continue
                kandidaten.append((start, start + laenge, text[start : start + laenge]))
                break
    for start, ende, roh in kandidaten:
        try:
            wert = json.loads(roh.strip())
        except json.JSONDecodeError:
            continue
        objekte = wert if isinstance(wert, list) else [wert]
        aufrufe = [a for a in (_als_aufruf(o, erlaubt) for o in objekte) if a]
        if aufrufe:
            rest = (text[:start] + text[ende:]).strip()
            return rest, aufrufe
    return text, []


def nachrichten_fuer_prompt_modus(
    nachrichten: list[dict[str, Any]], werkzeuge: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Wandelt OpenAI-Nachrichten (mit tool_calls/tool) in reines Textformat um."""
    ergebnis: list[dict[str, Any]] = []
    namen_je_id: dict[str, str] = {}
    prompt = werkzeug_prompt(werkzeuge) if werkzeuge else ""
    system_ergaenzt = False
    for n in nachrichten:
        rolle = n.get("role")
        if rolle == "system" and not system_ergaenzt:
            ergebnis.append({"role": "system", "content": f"{n.get('content', '')}\n\n{prompt}".strip()})
            system_ergaenzt = True
        elif rolle == "assistant" and n.get("tool_calls"):
            aufrufe = []
            for tc in n["tool_calls"]:
                f = tc.get("function", {})
                namen_je_id[tc.get("id", "")] = f.get("name", "")
                argumente, _ = argumente_parsen(f.get("arguments"))
                aufrufe.append({"werkzeug": f.get("name"), "argumente": argumente})
            inhalt = (n.get("content") or "").strip()
            json_text = json.dumps(aufrufe[0] if len(aufrufe) == 1 else aufrufe, ensure_ascii=False)
            ergebnis.append({"role": "assistant", "content": f"{inhalt}\n{json_text}".strip()})
        elif rolle == "tool":
            name = n.get("name") or namen_je_id.get(n.get("tool_call_id", ""), "Werkzeug")
            ergebnis.append({"role": "user", "content": f"[Ergebnis von {name}]\n{n.get('content', '')}"})
        else:
            ergebnis.append({"role": rolle, "content": n.get("content") or ""})
    if prompt and not system_ergaenzt:
        ergebnis.insert(0, {"role": "system", "content": prompt})
    return ergebnis


# ---------------------------------------------------------------------------
# Fassade
# ---------------------------------------------------------------------------
# Cloud-Vorschläge (Modell-ID, Anzeigename, Schlüsselname) – abgeleitet aus dem Anbieter-Register
# (jarvis/anbieter.py, Stand Oktober 2026). Für bestehende Aufrufer unverändert im Format.
CLOUD_VORSCHLAEGE = [
    (a.modell_id(m), n, a.schluessel)
    for a in anbieter_register.EINGEBAUTE
    if not a.lokal
    for m, n in a.vorschlaege
]

# Lokale Vorschläge: nur Modelle mit zuverlässigem Tool-Calling in Ollama.
LOKALE_VORSCHLAEGE = [
    (f"ollama/{m}", n) for m, n in anbieter_register.anbieter_finden("ollama").vorschlaege  # type: ignore[union-attr]
]

# Ollama-Modelle, die keine Chatmodelle sind (Einbettungen) – nicht als Sprachmodell vorschlagen
_KEIN_CHATMODELL = ("embed", "bge-", "minilm", "nomic-embed")

def ist_ollama(modell: str) -> bool:
    return modell.startswith(("ollama/", "ollama_chat/"))


def ollama_name(modell: str) -> str:
    return modell.split("/", 1)[1] if ist_ollama(modell) else modell


def litellm_modell(modell: str) -> str:
    """ollama/x → ollama_chat/x (Chat-Endpunkt mit Tool-Calling)."""
    if modell.startswith("ollama/"):
        return "ollama_chat/" + modell.split("/", 1)[1]
    return modell


class LLMFassade:
    def __init__(
        self,
        einstellungen: Einstellungen | Callable[[], Einstellungen],
        acompletion: Callable[..., Any] | None = None,
        aembedding: Callable[..., Any] | None = None,
        http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
    ):
        self._einstellungen = einstellungen
        self._acompletion = acompletion
        self._aembedding = aembedding
        self._http = http_client_fabrik or (lambda **kw: httpx.AsyncClient(**kw))
        self._werkzeug_cache: dict[str, bool] = {}
        self._einbettung_aus_bis = 0.0
        self.modelllisten = anbieter_register.ModellListen(http_client_fabrik)

    @property
    def einstellungen(self) -> Einstellungen:
        e = self._einstellungen
        return e() if callable(e) else e

    # ---------- LiteLLM-Zugriff (lazy import, da langsam) ----------
    def _completion_funktion(self) -> Callable[..., Any]:
        if self._acompletion is None:
            import litellm

            litellm.drop_params = True
            litellm.suppress_debug_info = True
            self._acompletion = litellm.acompletion
        return self._acompletion

    def _embedding_funktion(self) -> Callable[..., Any]:
        if self._aembedding is None:
            import litellm

            self._aembedding = litellm.aembedding
        return self._aembedding

    def _aufruf_kwargs(self, modell: str) -> dict[str, Any]:
        """``model`` für LiteLLM plus ``api_base``/``api_key``, wo nötig.

        Reihenfolge: Ollama → lokaler Server; ``api_basen`` je Modell-ID (eigener Endpunkt, ohne
        fremden Schlüssel); OpenCode/eigene Anbieter → ``openai/<modell>`` mit eigener Basis und
        eigenem Schlüssel; alles andere unverändert an LiteLLM (Schlüssel aus der Umgebung).
        """
        if ist_ollama(modell):
            return {"model": litellm_modell(modell), "api_base": self.einstellungen.ollama_url}
        basis = (self.einstellungen.api_basen or {}).get(modell)
        if basis:
            return {"model": modell, "api_base": basis}
        return anbieter_register.aufruf_parameter(modell, self.einstellungen.anbieter_eigene)

    # ---------- Fähigkeiten ----------
    async def unterstuetzt_werkzeuge(self, modell: str | None = None) -> bool:
        modell = modell or self.einstellungen.modell
        modus = self.einstellungen.werkzeug_modus
        if modus == "nativ":
            return True
        if modus == "prompt":
            return False
        if modell in self._werkzeug_cache:
            return self._werkzeug_cache[modell]
        ergebnis = True
        if ist_ollama(modell):
            ergebnis = await self._ollama_kann_werkzeuge(ollama_name(modell))
        elif modell.startswith("openrouter/"):
            # LiteLLMs Tabelle kennt die meisten OpenRouter-Modelle nicht (→ fälschlich „keine Werkzeuge“,
            # dann antworten DeepSeek/GLM im Prompt-Modus mit DSML-Markup). Die Live-Liste von OpenRouter
            # weiß es („tools“ in supported_parameters); ohne Angabe gilt: tool-fähig.
            ergebnis = await self._openrouter_kann_werkzeuge(modell.split("/", 1)[1])
        self._werkzeug_cache[modell] = ergebnis
        return ergebnis

    async def _openrouter_kann_werkzeuge(self, kennung: str) -> bool:
        a = anbieter_register.anbieter_finden("openrouter")
        if a is None:
            return True
        try:
            live = await self.modelllisten.laden(a)
        except Exception:  # noqa: BLE001
            return True
        for e in live:
            if e.id == kennung:
                return e.werkzeuge is not False
        return True

    async def _ollama_kann_werkzeuge(self, name: str) -> bool:
        try:
            async with self._http(timeout=5.0) as client:
                r = await client.post(f"{self.einstellungen.ollama_url}/api/show", json={"model": name})
                r.raise_for_status()
                daten = r.json()
        except (httpx.HTTPError, ValueError):
            return False
        faehigkeiten = daten.get("capabilities")
        if isinstance(faehigkeiten, list):
            return "tools" in faehigkeiten
        return ".Tools" in (daten.get("template") or "")

    # ---------- Streaming ----------
    async def antwort_streamen(
        self,
        nachrichten: list[dict[str, Any]],
        werkzeuge: list[dict[str, Any]] | None = None,
        modell: str | None = None,
        temperatur: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streamt die Antwort.

        Liefert {"typ": "text", "delta": str} und zum Schluss
        {"typ": "ende", "text": str, "werkzeug_aufrufe": [WerkzeugAufruf], "modus": "nativ"|"prompt"}.
        """
        modell = modell or self.einstellungen.modell
        werkzeuge = werkzeuge or []
        nativ = not werkzeuge or await self.unterstuetzt_werkzeuge(modell)
        kwargs: dict[str, Any] = {
            "stream": True,
            "temperature": self.einstellungen.temperatur if temperatur is None else temperatur,
            "timeout": self.einstellungen.llm_timeout,
            **self._aufruf_kwargs(modell),
        }
        if nativ:
            kwargs["messages"] = nachrichten
            if werkzeuge:
                kwargs["tools"] = werkzeuge
        else:
            kwargs["messages"] = nachrichten_fuer_prompt_modus(nachrichten, werkzeuge)

        sammler = ToolCallSammler()
        text = ""
        gestreamt = 0  # Anzahl bereits ausgegebener Zeichen
        zurueckhalten = False  # im Prompt-Modus: möglicher JSON-Aufruf → nicht streamen

        try:
            antwort = await self._completion_funktion()(**kwargs)
            async for chunk in antwort:
                auswahl = _feld(chunk, "choices") or []
                if not auswahl:
                    continue
                delta = _feld(auswahl[0], "delta")
                if delta is None:
                    continue
                tcs = _feld(delta, "tool_calls")
                if tcs:
                    sammler.hinzufuegen(tcs)
                inhalt = _feld(delta, "content")
                if not inhalt:
                    continue
                text += inhalt
                if nativ:
                    if zurueckhalten or text.lstrip().startswith(("<｜", "<|")):
                        zurueckhalten = True  # DSML-Markup als Text – wird am Ende geparst
                        continue
                    gestreamt = len(text)
                    yield {"typ": "text", "delta": inhalt}
                    continue
                if not zurueckhalten:
                    neu = text[gestreamt:]
                    if not text.strip():
                        continue
                    if text.lstrip()[0] in "{[`" or text.lstrip().startswith(("<｜", "<|")):
                        zurueckhalten = True
                        continue
                    pos = min((neu.find(z) for z in ("{", "`", "<｜", "<|") if z in neu), default=-1)
                    if pos >= 0:
                        zurueckhalten = True
                        neu = neu[:pos]
                    if neu:
                        gestreamt += len(neu)
                        yield {"typ": "text", "delta": neu}
        except Exception as e:  # noqa: BLE001
            raise LLMFehler(self._fehlertext(e, modell)) from e

        aufrufe = sammler.ergebnis()
        if werkzeuge and (not nativ or (not aufrufe and enthaelt_dsml(text))):
            namen = {(w.get("function") or w).get("name") for w in werkzeuge}
            rest, aufrufe_prompt = werkzeug_aufrufe_parsen(text, namen)
            if aufrufe_prompt or enthaelt_dsml(text):
                aufrufe = aufrufe_prompt or aufrufe
                text = rest
        if not aufrufe and gestreamt < len(text):
            yield {"typ": "text", "delta": text[gestreamt:]}
        yield {
            "typ": "ende",
            "text": text.strip() if aufrufe else text,
            "werkzeug_aufrufe": aufrufe,
            "modus": "nativ" if nativ else "prompt",
        }

    def _fehlertext(self, e: Exception, modell: str) -> str:
        name = type(e).__name__
        meldung = str(e)
        if ist_ollama(modell) and ("Connect" in name or "Connection" in meldung or "connect" in meldung):
            return (
                f"Ollama ist nicht erreichbar ({self.einstellungen.ollama_url}). Läuft „ollama serve“? "
                f"Modell laden mit: ollama pull {ollama_name(modell)}"
            )
        if ist_ollama(modell) and ("not found" in meldung or "404" in meldung):
            return f"Das Ollama-Modell ist nicht installiert. Bitte ausführen: ollama pull {ollama_name(modell)}"
        if "Authentication" in name or "api key" in meldung.lower() or "api_key" in meldung.lower():
            a = anbieter_register.anbieter_von_modell(modell, self.einstellungen.anbieter_eigene)
            schluessel = (a.schluessel if a else None) or f"{modell.split('/', 1)[0].upper()}_API_KEY"
            return (
                f"API-Schlüssel für {modell} fehlt oder ist ungültig. Hinterlegen mit: "
                f"jarvis schluessel {schluessel}"
            )
        if "RateLimit" in name:
            return f"Ratenlimit des Anbieters erreicht ({modell}). Bitte kurz warten."
        return f"Fehler beim Modell {modell}: {name}: {meldung[:500]}"

    # ---------- Einbettungen ----------
    async def einbetten(self, texte: list[str]) -> list[list[float]] | None:
        """Einbettungen über LiteLLM; None, wenn kein Einbettungsmodell verfügbar ist."""
        modell = self.einstellungen.einbettungs_modell
        if not modell or not texte or time.monotonic() < self._einbettung_aus_bis:
            return None
        try:
            antwort = await self._embedding_funktion()(input=texte, **self._aufruf_kwargs(modell))
            daten = _feld(antwort, "data") or []
            vektoren = [list(_feld(d, "embedding")) for d in daten]
            if len(vektoren) != len(texte):
                raise ValueError("Anzahl der Einbettungen passt nicht")
            return vektoren
        except Exception:  # noqa: BLE001 - Fallback auf Schlüsselwortsuche
            self._einbettung_aus_bis = time.monotonic() + 300
            return None

    # ---------- Modelle ----------
    async def ollama_modelle(self) -> list[str]:
        try:
            async with self._http(timeout=3.0) as client:
                r = await client.get(f"{self.einstellungen.ollama_url}/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", []) if m.get("name")]
        except (httpx.HTTPError, ValueError, KeyError):
            return []

    async def modell_vorschlaege(self) -> list[dict[str, Any]]:
        """Alle Vorschläge (Ollama live + Cloud-Vorschläge) – Kurzform von ``modelle_uebersicht``."""
        return (await self.modelle_uebersicht())["vorschlaege"]

    def modelllisten_vergessen(self) -> None:
        """Nach neuem Schlüssel: Live-Listen beim nächsten Abruf neu laden."""
        self.modelllisten.vergessen()

    async def _ollama_eintraege(self) -> list[dict[str, Any]]:
        vorschlaege: list[dict[str, Any]] = []
        lokale = await self.ollama_modelle()
        for name in lokale:
            if any(m in name.lower() for m in _KEIN_CHATMODELL):
                continue
            vorschlaege.append(self._eintrag(f"ollama/{name}", f"{name} (lokal)", "ollama", lokal=True, verfuegbar=True, live=True))
        aktuell = self.einstellungen.modell
        ids = {v["id"] for v in vorschlaege}
        # „ollama/qwen2.5“ und „ollama/qwen2.5:latest“ gelten als gleich
        installiert = {i.removesuffix(":latest") for i in ids}
        kandidaten = [(aktuell, ollama_name(aktuell))] if ist_ollama(aktuell) else []
        kandidaten += [(mid, f"{name}") for mid, name in LOKALE_VORSCHLAEGE]
        for kandidat, name in kandidaten:
            if kandidat in ids or kandidat.removesuffix(":latest") in installiert:
                continue
            vorschlaege.append(self._eintrag(
                kandidat, f"{name} (lokal, nicht installiert – ollama pull {ollama_name(kandidat)})",
                "ollama", lokal=True, verfuegbar=False,
            ))
            ids.add(kandidat)
        return vorschlaege

    @staticmethod
    def _eintrag(
        mid: str, name: str, anbieter: str, *, lokal: bool, verfuegbar: bool, live: bool = False,
        kostenlos: bool | None = None, werkzeuge: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "id": mid, "name": name, "lokal": lokal, "verfuegbar": verfuegbar, "anbieter": anbieter,
            "kostenlos": kostenlos, "werkzeuge": werkzeuge, "live": live,
        }

    async def _anbieter_eintraege(self, a: anbieter_register.Anbieter, neu: bool) -> list[dict[str, Any]]:
        """Live-Liste des Anbieters (wenn möglich), sonst seine Vorschläge."""
        if a.lokal:
            return await self._ollama_eintraege()
        live = await self.modelllisten.laden(a, neu=neu)
        eintraege = anbieter_register.sortiert(a, live) if live else anbieter_register.vorschlaege(a)
        verfuegbar = a.verfuegbar()
        return [
            self._eintrag(a.modell_id(e.id), e.name, a.id, lokal=False, verfuegbar=verfuegbar, live=e.live,
                          kostenlos=e.kostenlos, werkzeuge=e.werkzeuge)
            for e in eintraege
        ]

    async def modelle_uebersicht(self, anbieter_id: str | None = None, neu: bool = False) -> dict[str, Any]:
        """``{aktuell, anbieter, vorschlaege}`` für ``GET /api/modelle``.

        Ohne ``anbieter_id``: Ollama live plus die festen Cloud-Vorschläge aller Anbieter. Mit
        ``anbieter_id``: nur dieser Anbieter – live, wenn Schlüssel/Endpunkt es erlauben.
        """
        eigene = self.einstellungen.anbieter_eigene
        alle = anbieter_register.alle_anbieter(eigene)
        aktuell = self.einstellungen.modell
        if anbieter_id:
            gewaehlt = anbieter_register.anbieter_finden(anbieter_id, eigene)
            if gewaehlt is None:
                raise LLMFehler(f"Unbekannter Anbieter „{anbieter_id}“.")
            vorschlaege = await self._anbieter_eintraege(gewaehlt, neu)
        else:
            vorschlaege = await self._ollama_eintraege()
            for a in alle:
                if a.lokal:
                    continue
                verfuegbar = a.verfuegbar()
                vorschlaege += [
                    self._eintrag(a.modell_id(m), n, a.id, lokal=False, verfuegbar=verfuegbar)
                    for m, n in a.vorschlaege
                ]
        # Das aktive Modell steht immer in der Liste (Freitext-ID oder nicht mehr vorgeschlagen)
        a_aktuell = anbieter_register.anbieter_von_modell(aktuell, eigene)
        gehoert_dazu = not anbieter_id or (a_aktuell is not None and a_aktuell.id == anbieter_id)
        if gehoert_dazu and aktuell not in {v["id"] for v in vorschlaege}:
            vorschlaege.insert(0, self._eintrag(
                aktuell, aktuell, a_aktuell.id if a_aktuell else "", lokal=ist_ollama(aktuell), verfuegbar=True,
            ))
        infos = []
        for a in alle:
            info = a.als_info()
            if a.lokal:
                info["verfuegbar"] = any(v["anbieter"] == "ollama" and v["verfuegbar"] for v in vorschlaege) if not anbieter_id or anbieter_id == "ollama" else True
            infos.append(info)
        return {"aktuell": aktuell, "anbieter": infos, "vorschlaege": vorschlaege}
