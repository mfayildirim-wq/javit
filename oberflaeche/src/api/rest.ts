import type {
  Einstellungen,
  Erinnerung,
  Integration,
  IntegrationAnlegen,
  KatalogEintrag,
  Modelle,
  Status,
  VerlaufEintrag,
  Werkzeug,
} from './types';

export class ApiFehler extends Error {
  constructor(
    public readonly status: number,
    nachricht: string,
  ) {
    super(nachricht);
  }
}

async function anfrage<T>(methode: string, pfad: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${pfad}`, {
      method: methode,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiFehler(0, 'Kern nicht erreichbar');
  }
  const text = await res.text();
  let daten: unknown = null;
  if (text) {
    try {
      daten = JSON.parse(text);
    } catch {
      daten = text;
    }
  }
  if (!res.ok) {
    const detail =
      daten && typeof daten === 'object' && 'detail' in daten
        ? String((daten as { detail: unknown }).detail)
        : typeof daten === 'string' && daten
          ? daten
          : `HTTP ${res.status}`;
    throw new ApiFehler(res.status, detail);
  }
  return daten as T;
}

/** Akzeptiert sowohl `[...]` als auch `{schluessel: [...]}`. */
function liste<T>(daten: unknown, ...schluessel: string[]): T[] {
  if (Array.isArray(daten)) return daten as T[];
  if (daten && typeof daten === 'object') {
    for (const s of schluessel) {
      const v = (daten as Record<string, unknown>)[s];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

export const api = {
  status: () => anfrage<Status>('GET', '/status'),
  modelle: () => anfrage<Modelle>('GET', '/modelle'),
  modellSetzen: (modell: string) => anfrage<unknown>('PUT', '/modelle', { modell }),
  einstellungen: () => anfrage<Einstellungen>('GET', '/einstellungen'),
  einstellungenSpeichern: (teil: Partial<Einstellungen>) => anfrage<Einstellungen>('PUT', '/einstellungen', teil),
  geheimnisSetzen: (name: string, wert: string) =>
    anfrage<unknown>('PUT', `/geheimnisse/${encodeURIComponent(name)}`, { wert }),
  werkzeuge: async () => liste<Werkzeug>(await anfrage<unknown>('GET', '/werkzeuge'), 'werkzeuge'),
  integrationen: async () => liste<Integration>(await anfrage<unknown>('GET', '/integrationen'), 'integrationen'),
  katalog: async () => liste<KatalogEintrag>(await anfrage<unknown>('GET', '/integrationen/katalog'), 'katalog'),
  integrationAnlegen: (body: IntegrationAnlegen) => anfrage<Integration>('POST', '/integrationen', body),
  integrationEntfernen: (id: string) => anfrage<unknown>('DELETE', `/integrationen/${encodeURIComponent(id)}`),
  integrationNeuVerbinden: (id: string) =>
    anfrage<unknown>('POST', `/integrationen/${encodeURIComponent(id)}/neu-verbinden`),
  verlauf: async (limit = 20) =>
    liste<VerlaufEintrag>(await anfrage<unknown>('GET', `/verlauf?limit=${limit}`), 'verlauf', 'nachrichten'),
  gedaechtnis: async () =>
    liste<Erinnerung>(await anfrage<unknown>('GET', '/gedaechtnis'), 'erinnerungen', 'gedaechtnis'),
  gedaechtnisLoeschen: () => anfrage<unknown>('DELETE', '/gedaechtnis'),
};

export type Api = typeof api;
