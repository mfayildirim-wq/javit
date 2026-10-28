import { useEffect } from 'react';
import { create } from 'zustand';
import type { ClientNachricht, Status } from '../api/types';
import type { VerbindungsStatus } from '../api/socket';
import { anfangsZustand, reduzieren, type Aktion, type KernZustand } from './reducer';
import { assistentName, weckwortAnzeige } from '../lib/name';

export type Ansicht = 'konsole' | 'integrationen' | 'einstellungen';

export interface AppZustand extends KernZustand {
  verbindung: VerbindungsStatus;
  verbindungsVersuche: number;
  /** Seit wann der Kern nicht erreichbar ist (ms), null wenn verbunden. */
  getrenntSeit: number | null;
  status: Status | null;
  ansicht: Ansicht;
  paletteOffen: boolean;
  vorlesen: boolean;
  /** Mikrofon und Lautsprecher des Browsers statt des Rechners, auf dem der Kern läuft. */
  audioBrowser: boolean;
  /** Sender wird von der Verbindung gesetzt; in Tests austauschbar. */
  sender: (n: ClientNachricht) => boolean;
  /** Von der Verbindung gesetzt: Browser-Aufnahme starten (liefert Abtastrate oder null) bzw. stoppen. */
  audioStarten: () => Promise<number | null>;
  audioStoppen: () => void;

  verarbeiten: (a: Aktion) => void;
  senden: (n: ClientNachricht) => boolean;
  nachrichtSenden: (text: string) => boolean;
  freigabeBeantworten: (id: string, erlaubt: boolean) => void;
  abbrechen: () => void;
  stimmeSetzen: (aktiv: boolean) => Promise<void>;
  setAudioBrowser: (an: boolean) => void;
  setVerbindung: (v: VerbindungsStatus, versuche: number) => void;
  setStatus: (s: Status | null) => void;
  setAnsicht: (a: Ansicht) => void;
  setPalette: (offen: boolean) => void;
  setVorlesen: (an: boolean) => void;
}

export function audioBrowserStandard(): boolean {
  try {
    const gespeichert = localStorage.getItem('jarvis.audioBrowser');
    if (gespeichert === '1') return true;
    if (gespeichert === '0') return false;
  } catch {
    /* egal */
  }
  // Handy/Tablet: nur das Browser-Mikrofon ist erreichbar
  return typeof navigator !== 'undefined' && (navigator.maxTouchPoints > 1 || /Android|iPhone|iPad/.test(navigator.userAgent));
}

function vorlesenLaden(): boolean {
  try {
    return localStorage.getItem('jarvis.vorlesen') === '1';
  } catch {
    return false;
  }
}

export const useJarvis = create<AppZustand>()((set, get) => ({
  ...anfangsZustand,
  verbindung: 'verbinde',
  verbindungsVersuche: 0,
  getrenntSeit: null,
  status: null,
  ansicht: 'konsole',
  paletteOffen: false,
  vorlesen: vorlesenLaden(),
  audioBrowser: audioBrowserStandard(),
  sender: () => false,
  audioStarten: async () => null,
  audioStoppen: () => undefined,

  verarbeiten: (a) => set((s) => reduzieren(s, a)),

  senden: (n) => {
    const ok = get().sender(n);
    if (!ok) get().verarbeiten({ typ: 'lokal_hinweis', text: 'Keine Verbindung zum Kern – Nachricht nicht gesendet.' });
    return ok;
  },

  nachrichtSenden: (text) => {
    const t = text.trim();
    if (!t) return false;
    const ok = get().senden({ typ: 'nachricht', text: t, sprechen: get().vorlesen });
    if (ok) get().verarbeiten({ typ: 'lokal_gesendet', text: t });
    return ok;
  },

  freigabeBeantworten: (id, erlaubt) => {
    get().senden({ typ: 'freigabe', id, erlaubt });
    get().verarbeiten({ typ: 'lokal_freigabe_erledigt', id });
  },

  abbrechen: () => {
    get().senden({ typ: 'abbrechen' });
    get().verarbeiten({ typ: 'lokal_abgebrochen' });
  },

  stimmeSetzen: async (aktiv) => {
    if (get().audioBrowser) {
      if (aktiv) {
        const rate = await get().audioStarten();
        if (rate === null) {
          get().verarbeiten({ typ: 'lokal_hinweis', text: 'Mikrofon im Browser nicht verfügbar – Zugriff erlauben oder „Audio im Browser“ ausschalten.' });
          return;
        }
        if (!get().senden({ typ: 'audio_start', rate })) {
          get().audioStoppen();
          return;
        }
      } else {
        get().senden({ typ: 'audio_stop' });
        get().audioStoppen();
      }
    }
    if (!get().senden({ typ: 'stimme', aktiv })) return;
    const st = get().status;
    if (st) set({ status: { ...st, stimme: { ...st.stimme, aktiv } } });
  },
  setAudioBrowser: (audioBrowser) => {
    try {
      localStorage.setItem('jarvis.audioBrowser', audioBrowser ? '1' : '0');
    } catch {
      /* egal */
    }
    set({ audioBrowser });
  },

  setVerbindung: (v, versuche) =>
    set((s) => ({
      verbindung: v,
      verbindungsVersuche: versuche,
      getrenntSeit: v === 'offen' ? null : (s.getrenntSeit ?? Date.now()),
    })),
  setStatus: (status) => set({ status }),
  setAnsicht: (ansicht) => set({ ansicht, paletteOffen: false }),
  setPalette: (paletteOffen) => set({ paletteOffen }),
  setVorlesen: (vorlesen) => {
    try {
      localStorage.setItem('jarvis.vorlesen', vorlesen ? '1' : '0');
    } catch {
      /* egal */
    }
    set({ vorlesen });
  },
}));

/** Ob gerade gearbeitet wird (Abbrechen sinnvoll). */
export function istBeschaeftigt(s: Pick<AppZustand, 'zustand' | 'aktiveAntwort'>): boolean {
  return s.zustand !== 'bereit' || s.aktiveAntwort !== null;
}

/** Eingestellter Name des Assistenten (aus /api/status, Standard „Javit“). */
export const useName = (): string => useJarvis((s) => assistentName(s.status));

/** Aktives Weckwort für Anzeigen, z. B. „Javit“ oder „Hey Jarvis“. */
export const useWeckwort = (): string =>
  useJarvis((s) => weckwortAnzeige(s.status?.stimme.weckwort, assistentName(s.status)));

/** Fenstertitel (`document.title`) folgt dem eingestellten Namen. */
export function useFenstertitel(): void {
  const name = useName();
  useEffect(() => {
    document.title = name;
  }, [name]);
}
