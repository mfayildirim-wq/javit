import { useEffect } from 'react';
import { api } from '../api/rest';
import { JarvisSocket, wsUrl } from '../api/socket';
import { ZUSTAENDE } from '../api/types';
import type { Nachricht } from './reducer';
import { useJarvis } from './store';

/** Stellt die WebSocket-Verbindung her und hält den Status aktuell. */
export function useKernVerbindung(): void {
  useEffect(() => {
    const st = useJarvis.getState();
    const socket = new JarvisSocket({
      url: wsUrl(),
      onEvent: (ev) => useJarvis.getState().verarbeiten(ev),
      onStatus: (v, versuche) => {
        useJarvis.getState().setVerbindung(v, versuche);
        if (v === 'offen') {
          void statusLaden(true);
          void verlaufLaden();
        }
      },
    });
    useJarvis.setState({ sender: (n) => socket.senden(n) });
    socket.start();

    const statusTimer = setInterval(() => {
      if (useJarvis.getState().verbindung === 'offen' && !document.hidden) void statusLaden();
    }, 15_000);

    // Bei Integrationsänderung Status (Zähler) neu laden.
    let stand = st.integrationsStand;
    const abmelden = useJarvis.subscribe((s) => {
      if (s.integrationsStand !== stand) {
        stand = s.integrationsStand;
        void statusLaden();
      }
    });

    return () => {
      socket.stop();
      clearInterval(statusTimer);
      abmelden();
      useJarvis.setState({ sender: () => false });
    };
  }, []);
}

export async function statusLaden(erstmals = false): Promise<void> {
  try {
    const status = await api.status();
    const st = useJarvis.getState();
    st.setStatus(status);
    // Nach (Wieder-)Verbindung den Orb auf den Zustand des Kerns setzen.
    if (erstmals && status.zustand && ZUSTAENDE.includes(status.zustand)) st.verarbeiten({ typ: 'zustand', zustand: status.zustand });
  } catch {
    /* Status bleibt beim alten Wert */
  }
}

async function verlaufLaden(): Promise<void> {
  try {
    const eintraege = await api.verlauf(12);
    const nachrichten: Nachricht[] = eintraege
      .map((e) => ({ ...e, text: typeof e?.inhalt === 'string' ? e.inhalt : typeof e?.text === 'string' ? e.text : '' }))
      .filter((e) => e.text.trim() && (e.rolle === 'nutzer' || e.rolle === 'user' || e.rolle === 'jarvis' || e.rolle === 'assistent' || e.rolle === 'assistant'))
      .map((e, i) => ({
        id: `verlauf-${i}`,
        rolle: e.rolle === 'user' || e.rolle === 'nutzer' ? ('nutzer' as const) : ('jarvis' as const),
        text: e.text,
        fertig: true,
        zeit: e.zeit ? Date.parse(e.zeit) || 0 : 0,
      }));
    useJarvis.getState().verarbeiten({ typ: 'lokal_verlauf', nachrichten });
  } catch {
    /* kein Verlauf */
  }
}
