import type { Risiko, ServerEvent, Zustand } from '../api/types';

export interface Nachricht {
  id: string;
  rolle: 'nutzer' | 'jarvis';
  text: string;
  fertig: boolean;
  zeit: number;
}

export interface WerkzeugAufruf {
  id: string;
  name: string;
  argumente: unknown;
  integration: string | null;
  start: number;
  ende: number | null;
  ok: boolean | null;
  ergebnis: unknown;
}

export interface FreigabeAnfrage {
  id: string;
  werkzeug: string;
  argumente: unknown;
  grund: string;
  risiko: Risiko | string;
  empfangen: number;
  /** Sekunden bis zur automatischen Ablehnung (vom Kern; sonst 120). */
  timeout?: number;
}

export interface Hinweis {
  id: number;
  text: string;
  zeit: number;
}

export interface KernZustand {
  zustand: Zustand;
  pegel: number;
  /** Laufendes (noch nicht finales) Transkript. */
  transkript: string;
  nachrichten: Nachricht[];
  aktiveAntwort: string | null;
  werkzeuge: WerkzeugAufruf[];
  freigaben: FreigabeAnfrage[];
  hinweise: Hinweis[];
  /** Wird bei `integration_geaendert` erhöht, damit Ansichten neu laden. */
  integrationsStand: number;
  /** Laufende OAuth-Anmeldung (Browserfenster), bis die Integration verbunden ist oder der Hinweis geschlossen wird. */
  oauthAnmeldung: { integration: string; url: string; zeit: number } | null;
}

export const MAX_NACHRICHTEN = 60;
export const MAX_WERKZEUGE = 80;

export const anfangsZustand: KernZustand = {
  zustand: 'bereit',
  pegel: 0,
  transkript: '',
  nachrichten: [],
  aktiveAntwort: null,
  werkzeuge: [],
  freigaben: [],
  hinweise: [],
  integrationsStand: 0,
  oauthAnmeldung: null,
};

let hinweisZaehler = 0;
let nutzerZaehler = 0;

function begrenzen<T>(liste: T[], max: number): T[] {
  return liste.length > max ? liste.slice(liste.length - max) : liste;
}

function klemmen(x: number): number {
  if (!Number.isFinite(x)) return 0;
  return Math.min(1, Math.max(0, x));
}

export function nutzerNachricht(text: string, jetzt = Date.now()): Nachricht {
  nutzerZaehler += 1;
  return { id: `nutzer-${jetzt}-${nutzerZaehler}`, rolle: 'nutzer', text, fertig: true, zeit: jetzt };
}

/** Lokale Aktionen der Oberfläche (zusätzlich zu Server-Events). */
export type LokaleAktion =
  | { typ: 'lokal_gesendet'; text: string }
  | { typ: 'lokal_freigabe_erledigt'; id: string }
  | { typ: 'lokal_hinweis_weg'; id: number }
  | { typ: 'lokal_hinweis'; text: string }
  | { typ: 'lokal_abgebrochen' }
  | { typ: 'lokal_aktivitaet_leeren' }
  | { typ: 'lokal_oauth_weg' }
  | { typ: 'lokal_verlauf'; nachrichten: Nachricht[] };

export type Aktion = ServerEvent | LokaleAktion;

export function reduzieren(s: KernZustand, a: Aktion, jetzt: number = Date.now()): KernZustand {
  switch (a.typ) {
    case 'zustand':
      return {
        ...s,
        zustand: a.zustand,
        pegel: a.zustand === 'hoert' || a.zustand === 'spricht' ? s.pegel : 0,
        // Ein neues Zuhören beginnt mit leerem Live-Transkript.
        transkript: a.zustand === 'hoert' && s.zustand !== 'hoert' ? '' : s.transkript,
      };

    case 'pegel':
      return { ...s, pegel: klemmen(a.wert) };

    case 'transkript': {
      if (!a.final) return { ...s, transkript: a.text };
      const text = a.text.trim();
      if (!text) return { ...s, transkript: '' };
      const letzte = s.nachrichten[s.nachrichten.length - 1];
      // Getippter Text wird lokal schon angezeigt; ein Echo des Servers nicht doppeln.
      const doppelt = letzte?.rolle === 'nutzer' && letzte.text === text && jetzt - letzte.zeit < 10_000;
      return {
        ...s,
        transkript: '',
        nachrichten: doppelt ? s.nachrichten : begrenzen([...s.nachrichten, nutzerNachricht(text, jetzt)], MAX_NACHRICHTEN),
      };
    }

    case 'antwort_start': {
      if (s.nachrichten.some((n) => n.id === a.id)) return { ...s, aktiveAntwort: a.id };
      const neu: Nachricht = { id: a.id, rolle: 'jarvis', text: '', fertig: false, zeit: jetzt };
      return { ...s, aktiveAntwort: a.id, nachrichten: begrenzen([...s.nachrichten, neu], MAX_NACHRICHTEN) };
    }

    case 'antwort_text': {
      const vorhanden = s.nachrichten.some((n) => n.id === a.id);
      const nachrichten = vorhanden
        ? s.nachrichten.map((n) => (n.id === a.id ? { ...n, text: n.text + a.delta } : n))
        : begrenzen(
            [...s.nachrichten, { id: a.id, rolle: 'jarvis' as const, text: a.delta, fertig: false, zeit: jetzt }],
            MAX_NACHRICHTEN,
          );
      return { ...s, aktiveAntwort: a.id, nachrichten };
    }

    case 'antwort_ende': {
      const vorhanden = s.nachrichten.some((n) => n.id === a.id);
      const nachrichten = vorhanden
        ? s.nachrichten.map((n) =>
            n.id === a.id ? { ...n, text: a.text !== '' ? a.text : n.text, fertig: true } : n,
          )
        : begrenzen(
            [...s.nachrichten, { id: a.id, rolle: 'jarvis' as const, text: a.text, fertig: true, zeit: jetzt }],
            MAX_NACHRICHTEN,
          );
      return { ...s, nachrichten, aktiveAntwort: s.aktiveAntwort === a.id ? null : s.aktiveAntwort };
    }

    case 'werkzeug_start': {
      const aufruf: WerkzeugAufruf = {
        id: a.id,
        name: a.name,
        argumente: a.argumente,
        integration: a.integration ?? null,
        start: jetzt,
        ende: null,
        ok: null,
        ergebnis: null,
      };
      const ohne = s.werkzeuge.filter((w) => w.id !== a.id);
      return { ...s, werkzeuge: begrenzen([...ohne, aufruf], MAX_WERKZEUGE) };
    }

    case 'werkzeug_ende': {
      const vorhanden = s.werkzeuge.some((w) => w.id === a.id);
      const werkzeuge = vorhanden
        ? s.werkzeuge.map((w) => (w.id === a.id ? { ...w, ende: jetzt, ok: a.ok, ergebnis: a.ergebnis } : w))
        : begrenzen(
            [
              ...s.werkzeuge,
              {
                id: a.id,
                name: 'unbekannt',
                argumente: null,
                integration: null,
                start: jetzt,
                ende: jetzt,
                ok: a.ok,
                ergebnis: a.ergebnis,
              },
            ],
            MAX_WERKZEUGE,
          );
      return { ...s, werkzeuge, freigaben: s.freigaben.filter((f) => f.id !== a.id) };
    }

    case 'freigabe_noetig': {
      const anfrage: FreigabeAnfrage = {
        id: a.id,
        werkzeug: a.werkzeug,
        argumente: a.argumente,
        grund: a.grund,
        risiko: a.risiko,
        empfangen: jetzt,
        ...(typeof a.timeout === 'number' && a.timeout > 0 ? { timeout: a.timeout } : {}),
      };
      return { ...s, freigaben: [...s.freigaben.filter((f) => f.id !== a.id), anfrage] };
    }

    case 'integration_geaendert': {
      const i = a.integration as { id?: string; status?: string } | null;
      const fertig = s.oauthAnmeldung && i && i.id === s.oauthAnmeldung.integration && i.status !== 'verbindet';
      return { ...s, integrationsStand: s.integrationsStand + 1, oauthAnmeldung: fertig ? null : s.oauthAnmeldung };
    }

    case 'oauth_anmeldung':
      return { ...s, oauthAnmeldung: { integration: a.integration, url: a.url, zeit: jetzt } };

    case 'lokal_oauth_weg':
      return { ...s, oauthAnmeldung: null };

    case 'fehler': {
      hinweisZaehler += 1;
      const offen = s.nachrichten.map((n) => (n.id === s.aktiveAntwort ? { ...n, fertig: true } : n));
      return {
        ...s,
        nachrichten: offen,
        aktiveAntwort: null,
        hinweise: [...s.hinweise, { id: hinweisZaehler, text: a.text, zeit: jetzt }].slice(-4),
      };
    }

    case 'lokal_gesendet':
      return {
        ...s,
        transkript: '',
        nachrichten: begrenzen([...s.nachrichten, nutzerNachricht(a.text, jetzt)], MAX_NACHRICHTEN),
      };

    case 'lokal_freigabe_erledigt':
      return { ...s, freigaben: s.freigaben.filter((f) => f.id !== a.id) };

    case 'lokal_hinweis':
      hinweisZaehler += 1;
      return { ...s, hinweise: [...s.hinweise, { id: hinweisZaehler, text: a.text, zeit: jetzt }].slice(-4) };

    case 'lokal_hinweis_weg':
      return { ...s, hinweise: s.hinweise.filter((h) => h.id !== a.id) };

    case 'lokal_abgebrochen':
      return {
        ...s,
        freigaben: [],
        aktiveAntwort: null,
        nachrichten: s.nachrichten.map((n) => (n.fertig ? n : { ...n, fertig: true })),
        werkzeuge: s.werkzeuge.map((w) => (w.ende === null ? { ...w, ende: jetzt, ok: false, ergebnis: 'abgebrochen' } : w)),
      };

    case 'lokal_aktivitaet_leeren':
      return { ...s, werkzeuge: s.werkzeuge.filter((w) => w.ende === null) };

    case 'lokal_verlauf':
      return s.nachrichten.length > 0 ? s : { ...s, nachrichten: a.nachrichten.slice(-MAX_NACHRICHTEN) };

    default: {
      const _nie: never = a;
      void _nie;
      return s;
    }
  }
}
