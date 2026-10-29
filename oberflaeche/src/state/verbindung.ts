import { useEffect } from 'react';
import { api } from '../api/rest';
import { JarvisSocket, wsUrl } from '../api/socket';
import { BrowserAudio } from '../lib/audio';
import { ZUSTAENDE } from '../api/types';
import type { Nachricht } from './reducer';
import { useJarvis } from './store';
import { useBuehne } from '../buehne/store';

/** Stellt die WebSocket-Verbindung her und hält den Status aktuell. */
export function useKernVerbindung(): void {
  useEffect(() => {
    const st = useJarvis.getState();
    let audio: BrowserAudio | null = null;
    const socket = new JarvisSocket({
      url: wsUrl(),
      onEvent: (ev) => {
        const vorher = useJarvis.getState().unterhaltung?.id;
        useJarvis.getState().verarbeiten(ev);
        if (ev.typ === 'unterhaltung' && ev.id !== vorher) void verlaufLaden();
        if (ev.typ === 'sprachausgabe' && ev.zustand === 'gestoppt') audio?.leeren();
        if (ev.typ === 'buehne') useBuehne.getState().verarbeiten(ev.nachricht);
      },
      onBinaer: (daten) => {
        audio?.abspielen(daten);
      },
      onStatus: (v, versuche) => {
        useJarvis.getState().setVerbindung(v, versuche);
        if (v === 'offen') {
          void statusLaden(true);
          void verlaufLaden();
          void buehneLaden();
        }
      },
    });
    audio = new BrowserAudio({
      senden: (daten) => socket.sendeBinaer(daten),
      onPegel: (wert) => {
        if (useJarvis.getState().zustand === 'hoert') useJarvis.getState().verarbeiten({ typ: 'pegel', wert });
      },
    });
    const aufnahme = audio;
    useJarvis.setState({
      sender: (n) => socket.senden(n),
      audioStarten: async () => {
        try {
          return await aufnahme.start();
        } catch {
          return null;
        }
      },
      audioStoppen: () => aufnahme.stop(),
    });
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
      audio?.stop();
      clearInterval(statusTimer);
      abmelden();
      useJarvis.setState({ sender: () => false, audioStarten: async () => null, audioStoppen: () => undefined });
    };
  }, []);
}

export async function statusLaden(erstmals = false): Promise<void> {
  try {
    const status = await api.status();
    const st = useJarvis.getState();
    st.setStatus(status);
    if (status.unterhaltung) {
      const bekannt = st.unterhaltung;
      if (!bekannt) st.verarbeiten({ typ: 'lokal_unterhaltung', id: status.unterhaltung.id, titel: status.unterhaltung.titel });
      else if (bekannt.id !== status.unterhaltung.id) {
        st.verarbeiten({ typ: 'unterhaltung', id: status.unterhaltung.id, titel: status.unterhaltung.titel, grund: 'gewechselt' });
        void verlaufLaden();
      }
    }
    // Nach (Wieder-)Verbindung den Orb auf den Zustand des Kerns setzen.
    if (erstmals && status.zustand && ZUSTAENDE.includes(status.zustand)) st.verarbeiten({ typ: 'zustand', zustand: status.zustand });
  } catch {
    /* Status bleibt beim alten Wert */
  }
}

export async function verlaufLaden(): Promise<void> {
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

/** Offene Flächen, Stile, Schnellaktionen und Varianten der Bühne laden (nach jedem Verbinden). */
export async function buehneLaden(): Promise<void> {
  try {
    const stand = await api.buehne();
    useBuehne.getState().ausServer(stand?.flaechen ?? [], stand?.stile ?? [], stand?.schnellaktionen, stand?.varianten);
  } catch {
    /* älterer Kern ohne Bühne */
  }
}

/** Neue Unterhaltung beginnen (Knopf, Palette, Alt+N): Kern anlegen lassen, Konsole leeren und anzeigen. */
export async function neueUnterhaltung(titel?: string): Promise<void> {
  const st = useJarvis.getState();
  try {
    const u = await api.unterhaltungNeu(titel);
    useJarvis.getState().verarbeiten({ typ: 'unterhaltung', id: u.id, titel: u.titel, grund: 'neu' });
    st.setAnsicht('konsole');
  } catch (e) {
    st.verarbeiten({ typ: 'lokal_hinweis', text: `Neue Unterhaltung nicht möglich: ${(e as Error).message}` });
  }
}

/** Frühere Unterhaltung wieder aktivieren und in der Konsole zeigen. */
export async function unterhaltungOeffnen(id: number): Promise<void> {
  const st = useJarvis.getState();
  try {
    const u = await api.unterhaltungAktivieren(id);
    const vorher = useJarvis.getState().unterhaltung?.id;
    useJarvis.getState().verarbeiten({ typ: 'unterhaltung', id: u.id, titel: u.titel, grund: 'gewechselt' });
    if (vorher !== u.id) await verlaufLaden();
    st.setAnsicht('konsole');
  } catch (e) {
    st.verarbeiten({ typ: 'lokal_hinweis', text: `Unterhaltung nicht gefunden: ${(e as Error).message}` });
  }
}
