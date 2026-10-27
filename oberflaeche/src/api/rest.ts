import type {
  Einstellungen,
  Erinnerung,
  Integration,
  IntegrationAnlegen,
  IntegrationDetails,
  KatalogEintrag,
  Schritt,
  SchrittStand,
  Modelle,
  Status,
  VerlaufEintrag,
  VerzeichnisInstallieren,
  VerzeichnisQuelle,
  VerzeichnisSuche,
  VerzeichnisTreffer,
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
  /** Ohne Anbieter: Ollama live + alle Vorschläge; mit Anbieter: nur dessen Modelle (live, wenn möglich). */
  modelle: (anbieter?: string, neu = false) => {
    const q = new URLSearchParams();
    if (anbieter) q.set('anbieter', anbieter);
    if (neu) q.set('neu', '1');
    const s = q.toString();
    return anfrage<Modelle>('GET', s ? `/modelle?${s}` : '/modelle');
  },
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
  integrationDetails: (id: string) => anfrage<IntegrationDetails>('GET', `/integrationen/${encodeURIComponent(id)}`),
  integrationAendern: (id: string, body: IntegrationAnlegen) =>
    anfrage<IntegrationDetails>('PUT', `/integrationen/${encodeURIComponent(id)}`, body),
  integrationProtokoll: async (id: string, zeilen = 80) =>
    liste<string>(await anfrage<unknown>('GET', `/integrationen/${encodeURIComponent(id)}/protokoll?zeilen=${zeilen}`), 'zeilen'),
  katalogDetail: (id: string) => anfrage<KatalogEintrag>('GET', `/integrationen/katalog/${encodeURIComponent(id)}`),
  einrichtungDatei: (id: string, schritt: number, inhaltBase64: string) =>
    anfrage<{ pfad: string; erfuellt: boolean; einrichtung: Schritt[] }>(
      'POST',
      `/integrationen/katalog/${encodeURIComponent(id)}/einrichtung/${schritt}/datei`,
      { inhalt_base64: inhaltBase64 },
    ),
  einrichtungAusfuehren: (id: string, schritt: number) =>
    anfrage<SchrittStand>('POST', `/integrationen/katalog/${encodeURIComponent(id)}/einrichtung/${schritt}/ausfuehren`),
  einrichtungStand: (id: string, schritt: number) =>
    anfrage<SchrittStand>('GET', `/integrationen/katalog/${encodeURIComponent(id)}/einrichtung/${schritt}/stand`),
  integrationNeuVerbinden: (id: string) =>
    anfrage<unknown>('POST', `/integrationen/${encodeURIComponent(id)}/neu-verbinden`),
  integrationAbmelden: (id: string) => anfrage<Integration>('POST', `/integrationen/${encodeURIComponent(id)}/abmelden`),
  integrationAnmelden: (id: string) => anfrage<Integration>('POST', `/integrationen/${encodeURIComponent(id)}/anmelden`),
  verzeichnisse: async () => liste<VerzeichnisQuelle>(await anfrage<unknown>('GET', '/verzeichnisse'), 'verzeichnisse'),
  verzeichnisSuche: (q: string, quelle?: string, limit = 8) => {
    const p = new URLSearchParams({ q, limit: String(limit) });
    if (quelle) p.set('quelle', quelle);
    return anfrage<VerzeichnisSuche>('GET', `/verzeichnisse/suche?${p.toString()}`);
  },
  verzeichnisDetails: (quelle: string, kennung: string) =>
    anfrage<VerzeichnisTreffer>('GET', `/verzeichnisse/${encodeURIComponent(quelle)}/${kennung.split('/').map(encodeURIComponent).join('/')}`),
  verzeichnisInstallieren: (body: VerzeichnisInstallieren) => anfrage<Integration>('POST', '/verzeichnisse/installieren', body),
  verlauf: async (limit = 20) =>
    liste<VerlaufEintrag>(await anfrage<unknown>('GET', `/verlauf?limit=${limit}`), 'verlauf', 'nachrichten'),
  gedaechtnis: async () =>
    liste<Erinnerung>(await anfrage<unknown>('GET', '/gedaechtnis'), 'erinnerungen', 'gedaechtnis'),
  gedaechtnisLoeschen: () => anfrage<unknown>('DELETE', '/gedaechtnis'),
};

export type Api = typeof api;
