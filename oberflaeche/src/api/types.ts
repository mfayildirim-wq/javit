// Typen gemäß docs/VERTRAEGE.md (bindend).

export type Zustand = 'bereit' | 'hoert' | 'denkt' | 'spricht' | 'arbeitet';
export const ZUSTAENDE: readonly Zustand[] = ['bereit', 'hoert', 'denkt', 'spricht', 'arbeitet'];

export type Risiko = 'lesen' | 'aendern' | 'kritisch';

// ---------- Server → Client ----------
export interface EvZustand { typ: 'zustand'; zustand: Zustand }
export interface EvPegel { typ: 'pegel'; wert: number }
export interface EvTranskript { typ: 'transkript'; text: string; final: boolean }
export interface EvAntwortStart { typ: 'antwort_start'; id: string }
export interface EvAntwortText { typ: 'antwort_text'; id: string; delta: string }
export interface EvAntwortEnde { typ: 'antwort_ende'; id: string; text: string }
export interface EvWerkzeugStart {
  typ: 'werkzeug_start';
  id: string;
  name: string;
  argumente: unknown;
  integration?: string | null;
}
export interface EvWerkzeugEnde { typ: 'werkzeug_ende'; id: string; ok: boolean; ergebnis: unknown }
export interface EvFreigabeNoetig {
  typ: 'freigabe_noetig';
  id: string;
  werkzeug: string;
  argumente: unknown;
  grund: string;
  risiko: Risiko | string;
  /** Optional (Erweiterung): Sekunden bis zur automatischen Ablehnung (Einstellung freigabe_timeout). */
  timeout?: number;
}
export interface EvIntegrationGeaendert { typ: 'integration_geaendert'; integration: unknown }
export interface EvFehler { typ: 'fehler'; text: string }

export type ServerEvent =
  | EvZustand
  | EvPegel
  | EvTranskript
  | EvAntwortStart
  | EvAntwortText
  | EvAntwortEnde
  | EvWerkzeugStart
  | EvWerkzeugEnde
  | EvFreigabeNoetig
  | EvIntegrationGeaendert
  | EvFehler;

export const SERVER_EVENT_TYPEN = [
  'zustand',
  'pegel',
  'transkript',
  'antwort_start',
  'antwort_text',
  'antwort_ende',
  'werkzeug_start',
  'werkzeug_ende',
  'freigabe_noetig',
  'integration_geaendert',
  'fehler',
] as const satisfies readonly ServerEvent['typ'][];

// ---------- Client → Server ----------
export type ClientNachricht =
  | { typ: 'nachricht'; text: string; sprechen?: boolean }
  | { typ: 'freigabe'; id: string; erlaubt: boolean }
  | { typ: 'abbrechen' }
  | { typ: 'stimme'; aktiv: boolean }
  | { typ: 'zuhoeren' };

// ---------- REST ----------
export interface Status {
  version: string;
  /** Name des Assistenten (optional, ab 0.2; Standard „Javit“). */
  name?: string;
  modell: string;
  /** `engine` (optional): tatsächlich verwendete Weckwort-Erkennung. */
  stimme: { aktiv: boolean; weckwort: string | boolean; hoert: boolean; engine?: 'openwakeword' | 'vosk' | string };
  integrationen: number;
  werkzeuge: number;
  /** Vom Kern zusätzlich geliefert: aktueller Agent-Zustand. */
  zustand?: Zustand;
  /** Betriebssystem des Kerns (optional, ab 0.2): steuert plattformabhängige Optionen. */
  plattform?: 'mac' | 'windows' | 'linux';
}

export interface ModellVorschlag {
  id: string;
  name: string;
  lokal: boolean;
  verfuegbar: boolean;
  /** Anbieter-Kennung (Kern ab Anbieter-Register; sonst aus dem Präfix der ID ableitbar). */
  anbieter?: string;
  /** Kostenlos laut Anbieter (OpenRouter „:free“); null/undefined = unbekannt. */
  kostenlos?: boolean | null;
  /** Werkzeugaufrufe laut Anbieter; null/undefined = unbekannt. */
  werkzeuge?: boolean | null;
  /** Eintrag stammt aus der Live-Liste des Anbieters (sonst fester Vorschlag). */
  live?: boolean;
}
export interface AnbieterInfo {
  id: string;
  name: string;
  /** Name des Geheimnisses (API-Schlüssel); null bei Ollama oder Anbietern ohne Schlüssel. */
  schluessel: string | null;
  /** Schlüssel hinterlegt bzw. Ollama erreichbar. */
  verfuegbar: boolean;
  lokal: boolean;
  /** Vom Nutzer angelegter OpenAI-kompatibler Anbieter. */
  eigen: boolean;
}
export interface Modelle { aktuell: string; vorschlaege: ModellVorschlag[]; anbieter?: AnbieterInfo[] }
/** Eintrag in einstellungen.anbieter_eigene (Kern: jarvis/anbieter.py eigener_anbieter). */
export interface EigenerAnbieter { id: string; name?: string; api_base: string; schluessel?: string | null; modelle?: string[] }

export interface Werkzeug {
  name: string;
  beschreibung: string;
  quelle: string;
  integration?: string | null;
  risiko: Risiko | string;
}

export type IntegrationStatus = 'verbunden' | 'fehler' | 'aus';
export interface Integration {
  id: string;
  name: string;
  art: string;
  status: IntegrationStatus | string;
  werkzeuge: number;
  fehler?: string | null;
}

export type FeldTyp = 'text' | 'geheim' | 'ordner' | 'datei' | 'url' | string;
export interface KatalogFeld {
  name: string;
  titel: string;
  geheim: boolean;
  optional?: boolean;
  typ?: FeldTyp;
  standard?: string | null;
  beschreibung?: string | null;
}
/** Einrichtungsschritt (Kern: katalog.Schritt); `erfuellt` nur bei prüfbaren Schritten (Datei vorhanden). */
export interface Schritt {
  titel: string;
  text?: string;
  link?: string | null;
  datei?: string | null;
  befehl?: string | null;
  erfuellt?: boolean | null;
}
export interface KatalogEintrag {
  id: string;
  name: string;
  beschreibung: string;
  kategorie: string;
  icon: string;
  art: string;
  benoetigt: KatalogFeld[];
  hinweis?: string | null;
  webseite?: string | null;
  einrichtung?: Schritt[];
  installiert?: boolean;
}
/** Stand eines ausgeführten Einrichtungsbefehls. */
export interface SchrittStand { status: 'nie' | 'laeuft' | 'fertig' | 'fehler' | string; rueckgabe: number | null; ausgabe: string[]; sekunden: number }
export interface WerkzeugKurz { name: string; beschreibung: string; risiko: string }
/** GET /api/integrationen/{id} – ohne Geheimnisse („gespeichert“). */
export interface IntegrationDetails extends Integration {
  katalog?: { id: string; name: string; hinweis?: string | null; webseite?: string | null; benoetigt: KatalogFeld[]; einrichtung: Schritt[] };
  werte?: Record<string, string>;
  konfig: {
    befehl?: string[] | null;
    url?: string | null;
    kopfzeilen: Record<string, string>;
    umgebung: Record<string, string>;
    auth?: Record<string, string> | null;
    rest?: RestEndpunkt[] | null;
    geheimnisse: string[];
    risiko_standard: string;
    werkzeug_risiko: Record<string, string>;
    aktiv: boolean;
    hinzugefuegt: string;
  };
  werkzeug_liste: WerkzeugKurz[];
  protokoll: string[];
}

export type RestParamTyp = 'text' | 'zahl' | 'bool' | string;
export interface RestEndpunkt {
  name: string;
  methode: string;
  url: string;
  parameter: Record<string, RestParamTyp>;
  beschreibung: string;
}

export type IntegrationAnlegen =
  | { katalog: string; werte: Record<string, string> }
  | { name: string; mcp_befehl: string; umgebung: Record<string, string> }
  | { name: string; mcp_url: string; kopfzeilen: Record<string, string> }
  | { name: string; openapi_url: string; auth?: { art: string; wert: string } }
  | { name: string; rest: RestEndpunkt[] };

/** Struktur von /api/einstellungen (wie jarvis/konfig.py + jarvis/stimme/einstellungen.py; tolerant gelesen). */
export interface Einstellungen {
  /** Name des Assistenten (Standard „Javit“). */
  name?: string;
  modell?: string;
  anbieter_eigene?: EigenerAnbieter[];
  /** Anrede, z. B. „Sir“. */
  anrede?: string;
  /** Persona „Sir“ an/aus. */
  anrede_verwenden?: boolean;
  /** System-Persona (Freitext, Platzhalter {name}) – wird von der Oberfläche nicht verändert. */
  persona?: string;
  stimme?: {
    aktiv?: boolean;
    /** Weckwort(e), mehrere durch Komma, z. B. „javit, hey javit“. */
    weckwort?: string;
    /** „auto“ (hey_jarvis → openWakeWord, sonst Vosk) | „openwakeword“ | „vosk“ */
    weckwort_engine?: 'auto' | 'openwakeword' | 'vosk' | string;
    weckwort_varianten?: string[];
    weckwort_modell_pfad?: string;
    /** Weckwort-Schwelle 0..1 */
    schwelle?: number;
    stt?: 'lokal' | 'cloud' | string;
    tts?: 'auto' | 'say' | 'sapi' | 'piper' | 'espeak' | 'cloud' | 'aus' | string;
    tts_stimme?: string;
    [schluessel: string]: unknown;
  };
  [schluessel: string]: unknown;
}

export interface Erinnerung { id: string | number; text: string; zeit?: string }
/** Kern liefert `{id, zeit, rolle, inhalt}`; `text` wird ebenfalls akzeptiert. */
export interface VerlaufEintrag { rolle: string; inhalt?: string; text?: string; zeit?: string }
