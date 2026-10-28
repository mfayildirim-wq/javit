"""Startet Fake-LLM und einen echten Jarvis-Server als Unterprozesse (für E2E-Tests und Screenshots).

    python3 -m tests.e2e.umgebung [jarvis_port] [llm_port]   # aus kern/, läuft bis Strg+C
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

KERN = Path(__file__).resolve().parents[2]
FAKE_LLM = Path(__file__).resolve().parent / "fake_llm.py"
MINI_MCP = KERN / "tests" / "mini_mcp_server.py"


def freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _warten(url: str, prozess: subprocess.Popen, sekunden: float = 60) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if prozess.poll() is not None:
            raise RuntimeError(f"Prozess beendet (Code {prozess.returncode}): {url}")
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"{url} nicht erreichbar")


class E2EUmgebung:
    def __init__(self, jarvis_port: int | None = None, llm_port: int | None = None, home: Path | None = None):
        self.jarvis_port = jarvis_port or freier_port()
        self.llm_port = llm_port or freier_port()
        self._tmp = None if home else tempfile.TemporaryDirectory(prefix="jarvis-e2e-")
        self.basis = Path(home or self._tmp.name)  # type: ignore[union-attr]
        self.home = self.basis / "jarvis_home"
        self.prozesse: list[subprocess.Popen] = []
        self.logs: list[Path] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.jarvis_port}"

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.jarvis_port}/ws"

    def _starten(self, name: str, befehl: list[str], env: dict[str, str]) -> subprocess.Popen:
        log = self.basis / f"{name}.log"
        self.logs.append(log)
        p = subprocess.Popen(
            befehl, cwd=KERN, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.prozesse.append(p)
        return p

    def starten(self) -> "E2EUmgebung":
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "einstellungen.json").write_text(json.dumps({
            "modell": "openai/fake",
            "api_basen": {"openai/fake": f"http://127.0.0.1:{self.llm_port}/v1"},
            "einbettungs_modell": None,
            "ollama_url": "http://127.0.0.1:9",  # kein Ollama im Test
            "port": self.jarvis_port,
            "freigabe_timeout": 60,
            "gedaechtnis_automatisch": False,  # keine Titel-/Nachbereitungsaufrufe an das Fake-LLM
            "stimme": {"aktiv": False},
        }), encoding="utf-8")
        env = {
            **os.environ,
            "PYTHONPATH": str(KERN),
            "JARVIS_HOME": str(self.home),
            "JARVIS_GEHEIMNIS_BACKEND": "datei",
            "OPENAI_API_KEY": "sk-fake-e2e",
            "XDG_DATA_HOME": str(self.basis / "xdg"),
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        }
        fake = self._starten("fake_llm", [sys.executable, str(FAKE_LLM), str(self.llm_port)], env)
        _warten(f"http://127.0.0.1:{self.llm_port}/v1/models", fake)
        jarvis = self._starten(
            "jarvis", [sys.executable, "-m", "jarvis", "start", "--kein-browser", "--port", str(self.jarvis_port)], env
        )
        _warten(f"{self.url}/api/status", jarvis, 90)
        return self

    def protokolle(self) -> str:
        return "\n".join(f"--- {p.name}\n{p.read_text(errors='replace')[-4000:]}" for p in self.logs if p.exists())

    def stoppen(self) -> None:
        for p in reversed(self.prozesse):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for p in self.prozesse:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        self.prozesse.clear()
        if self._tmp:
            self._tmp.cleanup()

    def __enter__(self) -> "E2EUmgebung":
        return self.starten()

    def __exit__(self, *a: object) -> None:
        self.stoppen()


if __name__ == "__main__":
    jp = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    lp = int(sys.argv[2]) if len(sys.argv) > 2 else 8790
    u = E2EUmgebung(jp, lp).starten()
    print(f"Jarvis: {u.url}  Fake-LLM: http://127.0.0.1:{lp}  Daten: {u.basis}", flush=True)
    try:
        signal.sigwait({signal.SIGINT, signal.SIGTERM})
    finally:
        u.stoppen()
