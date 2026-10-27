"""MCP-Hub: verbindet MCP-Server (stdio und Streamable HTTP) über das offizielle Python-SDK `mcp` (2.x).

Jede Verbindung läuft als lange lebende Session in einer eigenen asyncio-Task (AsyncExitStack),
damit die anyio-Cancel-Scopes in derselben Task betreten und verlassen werden.
Die Tools eines Servers werden als Werkzeuge `<integration>__<tool>` registriert.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, TextIO

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp import types as mcp_types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from ..konfig import jarvis_home
from ..werkzeuge import Risiko, Werkzeug, WerkzeugFehler, name_bereinigen, risiko_schaetzen
from ..werkzeuge.prozess import erweiterter_path, programm_aufloesen


class McpFehler(RuntimeError):
    pass


def fehler_text(e: BaseException) -> str:
    """Erste „echte“ Ursache aus (verschachtelten) ExceptionGroups."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    text = str(e) or type(e).__name__
    return f"{type(e).__name__}: {text}" if text != type(e).__name__ else text


def ergebnis_zu_text(ergebnis: Any) -> str:
    """CallToolResult → Text (Textinhalte, sonst strukturierter Inhalt)."""
    teile: list[str] = []
    for block in getattr(ergebnis, "content", None) or []:
        typ = getattr(block, "type", "")
        if typ == "text":
            teile.append(block.text)
        elif typ == "image":
            teile.append(f"[Bild: {getattr(block, 'mime_type', 'image')}]")
        elif typ == "audio":
            teile.append("[Audio]")
        elif typ == "resource_link":
            teile.append(f"[Ressource: {getattr(block, 'uri', '')}]")
        elif typ == "resource":
            res = getattr(block, "resource", None)
            teile.append(getattr(res, "text", None) or f"[Ressource: {getattr(res, 'uri', '')}]")
        else:
            teile.append(str(block))
    if not teile and getattr(ergebnis, "structured_content", None) is not None:
        teile.append(json.dumps(ergebnis.structured_content, ensure_ascii=False, indent=1))
    return "\n".join(teile) if teile else "(kein Inhalt)"


class McpVerbindung:
    def __init__(
        self,
        integration_id: str,
        *,
        befehl: list[str] | None = None,
        umgebung: dict[str, str] | None = None,
        url: str | None = None,
        kopfzeilen: dict[str, str] | None = None,
        cwd: str | None = None,
        start_timeout: float = 120.0,
        aufruf_timeout: float = 120.0,
    ):
        if not befehl and not url:
            raise ValueError("Entweder befehl (stdio) oder url (HTTP) angeben")
        self.integration_id = integration_id
        self.befehl = befehl
        self.umgebung = umgebung or {}
        self.url = url
        self.kopfzeilen = kopfzeilen or {}
        self.cwd = cwd
        self.start_timeout = start_timeout
        self.aufruf_timeout = aufruf_timeout
        self.status = "aus"
        self.fehler: str | None = None
        self.tools: list[mcp_types.Tool] = []
        self.session: ClientSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._bereit = asyncio.Event()
        self._stop = asyncio.Event()
        self._protokoll: TextIO | None = None

    @property
    def art(self) -> str:
        return "stdio" if self.befehl else "http"

    def _protokoll_datei(self) -> TextIO:
        ordner = jarvis_home() / "logs"
        ordner.mkdir(parents=True, exist_ok=True)
        return open(Path(ordner) / f"mcp-{self.integration_id}.log", "a", encoding="utf-8")  # noqa: SIM115

    async def start(self) -> list[mcp_types.Tool]:
        if self._task and not self._task.done():
            await self.stop()
        self._bereit = asyncio.Event()
        self._stop = asyncio.Event()
        self.status = "verbindet"
        self.fehler = None
        self._task = asyncio.create_task(self._lauf(), name=f"mcp-{self.integration_id}")
        warten = asyncio.create_task(self._bereit.wait())
        try:
            fertig, _ = await asyncio.wait({warten, self._task}, timeout=self.start_timeout,
                                           return_when=asyncio.FIRST_COMPLETED)
        finally:
            warten.cancel()
        if not fertig:
            await self.stop()
            self.status = "fehler"
            self.fehler = f"Zeitüberschreitung beim Verbinden ({self.start_timeout:.0f} s)"
            raise McpFehler(self.fehler)
        if self.status != "verbunden":
            raise McpFehler(self.fehler or "Verbindung fehlgeschlagen")
        return self.tools

    async def _lauf(self) -> None:
        try:
            async with AsyncExitStack() as stack:
                if self.befehl:
                    pfad = erweiterter_path()
                    # Windows: npx → npx.cmd, uvx → uvx.exe (ohne Endung nicht startbar)
                    programm = programm_aufloesen(self.befehl[0], pfad) or self.befehl[0]
                    self._protokoll = self._protokoll_datei()
                    stack.callback(self._protokoll.close)
                    parameter = StdioServerParameters(
                        command=programm,
                        args=[os.path.expanduser(a) if a.startswith("~") else a for a in self.befehl[1:]],
                        env={"PATH": pfad, **self.umgebung},
                        cwd=self.cwd,
                    )
                    lesen, schreiben = await stack.enter_async_context(
                        stdio_client(parameter, errlog=self._protokoll)
                    )
                else:
                    http_client = create_mcp_http_client(headers=self.kopfzeilen)
                    await stack.enter_async_context(http_client)
                    lesen, schreiben = await stack.enter_async_context(
                        streamable_http_client(self.url or "", http_client=http_client)
                    )
                session = await stack.enter_async_context(ClientSession(lesen, schreiben))
                await session.initialize()
                self.tools = await self._alle_tools(session)
                self.session = session
                self.status = "verbunden"
                self._bereit.set()
                await self._stop.wait()
        except asyncio.CancelledError:
            if not self._stop.is_set():
                self.status = "fehler"
                self.fehler = self.fehler or "abgebrochen"
            raise
        except BaseException as e:  # noqa: BLE001 - ExceptionGroups von anyio
            if not self._stop.is_set():
                self.status = "fehler"
                self.fehler = fehler_text(e)
                if self.befehl:
                    self.fehler += f" (Protokoll: {jarvis_home() / 'logs' / f'mcp-{self.integration_id}.log'})"
        finally:
            self.session = None
            if self._stop.is_set():
                self.status = "aus"
            self._bereit.set()

    @staticmethod
    async def _alle_tools(session: ClientSession) -> list[mcp_types.Tool]:
        ergebnis = await session.list_tools()
        tools = list(ergebnis.tools)
        cursor = ergebnis.next_cursor
        seiten = 0
        while cursor and seiten < 50:
            ergebnis = await session.list_tools(params=mcp_types.PaginatedRequestParams(cursor=cursor))
            tools.extend(ergebnis.tools)
            cursor = ergebnis.next_cursor
            seiten += 1
        return tools

    async def aufrufen(self, name: str, argumente: dict[str, Any]) -> tuple[bool, str]:
        session = self.session
        if session is None or self.status != "verbunden":
            raise WerkzeugFehler(
                f"Integration „{self.integration_id}“ ist nicht verbunden"
                + (f": {self.fehler}" if self.fehler else ".")
            )
        try:
            ergebnis = await asyncio.wait_for(session.call_tool(name, argumente), self.aufruf_timeout)
        except asyncio.TimeoutError as e:
            raise WerkzeugFehler(f"Zeitüberschreitung bei {name} ({self.aufruf_timeout:.0f} s)") from e
        except Exception as e:  # noqa: BLE001
            if self._task is not None and self._task.done():
                self.status = "fehler"
                self.fehler = fehler_text(e)
            raise WerkzeugFehler(f"MCP-Fehler bei {name}: {fehler_text(e)}") from e
        return (not ergebnis.is_error), ergebnis_zu_text(ergebnis)

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001
                    pass
        self.session = None
        self.status = "aus"


def mcp_werkzeugname(integration_id: str, tool_name: str) -> str:
    voll = name_bereinigen(f"{integration_id}__{tool_name}", max_laenge=200)
    if len(voll) <= 64:
        return voll
    kurz = hashlib.sha1(voll.encode()).hexdigest()[:6]
    return f"{voll[:57]}_{kurz}"


class McpWerkzeug(Werkzeug):
    def __init__(self, verbindung: McpVerbindung, tool: mcp_types.Tool, risiko: Risiko):
        schema = dict(tool.input_schema or {"type": "object", "properties": {}})
        schema.pop("title", None)
        schema.pop("$schema", None)
        super().__init__(
            name=mcp_werkzeugname(verbindung.integration_id, tool.name),
            beschreibung=(tool.description or tool.title or tool.name).strip(),
            json_schema=schema,
            risiko=risiko,
            quelle="mcp",
            integration=verbindung.integration_id,
        )
        self.verbindung = verbindung
        self.tool_name = tool.name

    async def ausfuehren(self, **argumente: Any) -> Any:
        ok, text = await self.verbindung.aufrufen(self.tool_name, argumente)
        if not ok:
            raise WerkzeugFehler(text)
        return text


def risiko_fuer_tool(
    tool: mcp_types.Tool, standard: Risiko = "aendern", ueberschreibungen: dict[str, Risiko] | None = None
) -> Risiko:
    if ueberschreibungen and tool.name in ueberschreibungen:
        return ueberschreibungen[tool.name]
    risiko = risiko_schaetzen(tool.name, standard)
    hinweise = tool.annotations
    if hinweise is not None and risiko != "kritisch":
        if hinweise.read_only_hint:
            return "lesen"
    return risiko


def werkzeuge_aus_mcp(
    verbindung: McpVerbindung,
    standard: Risiko = "aendern",
    ueberschreibungen: dict[str, Risiko] | None = None,
) -> list[Werkzeug]:
    return [
        McpWerkzeug(verbindung, tool, risiko_fuer_tool(tool, standard, ueberschreibungen))
        for tool in verbindung.tools
    ]
