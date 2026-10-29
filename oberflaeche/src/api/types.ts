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
  /** technisch | fachlich – warum gefragt wird (fachliche Aktion bzw. geschütztes technisches Werkzeug). */
  bereich?: Bereich | string;
  /** Optional (Erweiterung): Sekunden bis zur automatischen Ablehnung (Einstellung freigabe_timeout). */
  timeout?: number;
}
export type Bereich = 'technisch' | 'fachlich';
export interface EvIntegrationGeaendert { typ: 'integration_geaendert'; integration: unknown }
/** OAuth-Anmeldung im Browser gestartet (Kern: integrationen/oauth.py); `url` = Anmeldeseite. */
export interface EvOauthAnmeldung { typ: 'oauth_anmeldung'; integration: string; url: string }
export interface EvFehler { typ: 'fehler'; text: string }
/** Aktuelle Unterhaltung hat gewechselt (neu, gewechselt, geloescht) oder ihren Titel geändert (titel). */
export interface EvUnterhaltung { typ: 'unterhaltung'; id: number; titel: string; grund: 'neu' | 'gewechselt' | 'titel' | 'geloescht' | string }
/** Sprachausgabe (Streaming): `start` (danach PCM-Binärframes int16 mono mit `rate`), `ende`, `gestoppt` (Stoppwort, Abbruch). */
export interface EvSprachausgabe { typ: 'sprachausgabe'; zustand: 'start' | 'ende' | 'gestoppt' | string; rate?: number; grund?: string }
/** Bühne: eine A2UI-Nachricht (v0.9.1-Teilmenge) bzw. Stilwerte, siehe {@link A2uiNachricht}. */
export interface EvBuehne { typ: 'buehne'; nachricht: A2uiNachricht }

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
  | EvOauthAnmeldung
  | EvFehler
  | EvUnterhaltung
  | EvSprachausgabe
  | EvBuehne;

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
  'oauth_anmeldung',
  'fehler',
  'unterhaltung',
  'sprachausgabe',
  'buehne',
] as const satisfies readonly ServerEvent['typ'][];

// ---------- Client → Server ----------
export type ClientNachricht =
  | { typ: 'nachricht'; text: string; sprechen?: boolean }
  | { typ: 'freigabe'; id: string; erlaubt: boolean }
  | { typ: 'abbrechen' }
  | { typ: 'stimme'; aktiv: boolean }
  | { typ: 'zuhoeren' }
  /** Audio im Browser: danach Binärframes (int16 mono, `rate`) bis `audio_stop`. */
  | { typ: 'audio_start'; rate: number }
  | { typ: 'audio_stop' }
  /** Bühne: Klick auf eine Aktion (Button, Karte, Tabellenzeile, Formular). */
  | { typ: 'buehne_aktion'; name: string; surfaceId: string; sourceComponentId: string; timestamp: string; context: Record<string, unknown> }
  /** Bühne: Eingabefeld geändert (zweiseitige Bindung; gesendet bei Blur/Enter). */
  | { typ: 'buehne_daten'; surfaceId: string; path: string; value: unknown }
  /** Bühne: Klick auf eine Schnellaktion/Variante – Vorlage mit diesen Argumenten erneut zeigen (ohne Modell). */
  | { typ: 'buehne_erneut'; vorlage: string; argumente?: Record<string, unknown>; titel?: string };

// ---------- Bühne (A2UI v0.9.1-Teilmenge, Katalog jarvis:buehne/1) ----------
/** Eine Komponente der flachen Liste: `id`, `component` (Bausteinname) und Eigenschaften laut Katalog. */
export interface BuehnenKomponente { id: string; component: string; [eigenschaft: string]: unknown }
export interface A2uiNachricht {
  version: string;
  /** `art` (ab Stufe 2): daten (Vorlage, Standard) oder werkzeug (Werkzeugfläche: Browser, Shell …); `symbol`: lucide-Name für den Reiter. */
  createSurface?: { surfaceId: string; catalogId?: string; theme?: { stil?: string; [k: string]: unknown }; titel?: string; vorlage?: string | null; art?: 'daten' | 'werkzeug'; symbol?: string | null };
  updateComponents?: { surfaceId: string; components: BuehnenKomponente[] };
  /** path "/" = ganzes Modell; ohne `value` wird der Pfad gelöscht. */
  updateDataModel?: { surfaceId: string; path?: string; value?: unknown };
  deleteSurface?: { surfaceId: string };
  /** Werte eines Stils (vor `createSurface`, wenn der Client ihn nicht kennt). */
  stil?: Stil;
  /** Schnellaktionen (global) und Varianten (je Vorlage); ersetzt den Stand aus GET /api/buehne. */
  aktionen?: { schnell: Schnellaktion[]; varianten: Record<string, Schnellaktion[]> };
}
/** Eine gemerkte Anzeige der Bühne (Verlauf): Vorlage + Argumente des Datenwerkzeugs. */
export interface Schnellaktion { id: string; titel: string; vorlage: string; werkzeug: string; argumente: Record<string, unknown>; zaehler: number; zuletzt: string }
export interface StilWerte { schema: 'hell' | 'dunkel'; farben: { primaer: string; akzent: string; hintergrund: string; flaeche: string; text: string; dezent: string; ok: string; warn: string; fehler: string }; schrift: { familie: string; basisgroesse: number }; rundung: number; abstand: number; dichte: 'dicht' | 'normal' | 'luftig'; schatten: 'keiner' | 'weich' | 'stark' }
export interface Stil { id: string; name: string; beschreibung?: string; quelle: { art: 'vordefiniert' | 'url' | 'datei' | 'klassen' | 'werte'; wert?: string }; werte: StilWerte; vorlieben: { liste: 'kacheln' | 'zeilen' | 'tabelle'; bildgroesse: 'klein' | 'mittel' | 'gross'; kennzahlenOben: boolean }; eigen?: boolean }
export interface Vorlage { id: string; name: string; zweck: string; version: number; protokollVersion: string; katalogId: string; komponenten?: unknown[]; datenschema?: unknown; datenquelle: { werkzeug: string; argumente: Record<string, unknown>; abbildung: Record<string, string> }; aktionen: Record<string, string>; stil: string | null; signatur: { werkzeug: string; schluessel: string[] }; erstellt: string; geaendert: string; modell?: string; versionen?: number }
export interface Rezept { id: string; name: string; art: 'werkzeug' | 'agent' | 'zeigen'; werkzeug?: string; argumentAbbildung?: Record<string, string>; auftrag?: string; bestaetigung?: string; risiko: 'lesen' | 'aendern' | 'kritisch'; vorlage: string; /** Art `zeigen`: Titel der neuen Fläche (mit `{feld}`). */ titel?: string; /** Art `zeigen`: beim ersten Mal gebaute Vorlage der Zielfläche. */ vorlageZiel?: string }
export interface Flaeche { surfaceId: string; titel: string; catalogId: string; stil: string; components: unknown[]; daten: Record<string, unknown>; vorlage: string | null; art?: 'daten' | 'werkzeug'; symbol?: string | null; werkzeug?: string }
/** GET /api/buehne */
export interface BuehnenStand { flaechen: Flaeche[]; stile: Stil[]; zuordnung: Record<string, string>; /** fehlt bei älterem Kern */ schnellaktionen?: Schnellaktion[]; /** fehlt bei älterem Kern */ varianten?: Record<string, Schnellaktion[]> }
/** POST /api/buehne/stile – Stil ableiten (url/datei/klassen) oder aus Werten anlegen. */
export interface StilAnlegen { name: string; quelle: { art: 'url' | 'datei' | 'klassen' | 'werte'; wert?: string; inhalt_base64?: string; werte?: StilWerte } }

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
  /** Aktuelle Unterhaltung (optional, ab 0.3). */
  unterhaltung?: { id: number; titel: string };
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
  bereich?: Bereich | string;
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
  /** OAuth-Modus („entdeckung“ | „manuell“) oder null – Anmeldung im Browser. */
  oauth?: string | null;
  /** „offiziell“ (vom Anbieter betrieben) oder „community“. */
  vertrauen?: 'offiziell' | 'community' | string;
  /** technisch (ohne Rückfrage) oder fachlich (Änderungen bestätigen). */
  bereich?: Bereich | string;
  /** Doku-Seite des Anbieters. */
  quelle?: string | null;
  /** Zusammengehörige Einträge, z. B. google-workspace. */
  gruppe?: string | null;
}
/** Ein Verzeichnis (MCP-Registry, Smithery, eigene Registry) – GET /api/verzeichnisse. */
export interface VerzeichnisQuelle { id: string; name: string; url: string; eigen: boolean }
/** Angabe, die vor der Installation eines Verzeichnis-Treffers nötig ist. */
export interface VerzeichnisFeld { name: string; titel: string; geheim: boolean; optional: boolean; beschreibung: string; standard?: string | null }
/** Treffer aus GET /api/verzeichnisse/suche bzw. /api/verzeichnisse/{quelle}/{kennung}. */
export interface VerzeichnisTreffer {
  quelle: string;
  kennung: string;
  name: string;
  beschreibung: string;
  webseite?: string | null;
  repository?: string | null;
  herausgeber: string;
  verifiziert: boolean;
  nutzungen?: number | null;
  art?: 'mcp_http' | 'mcp_stdio' | null;
  laufzeit?: 'fern' | 'npx' | 'uvx' | null;
  oauth: boolean;
  felder: VerzeichnisFeld[];
  warnungen: string[];
  installierbar: boolean;
  /** false: Felder erst nach dem Laden der Details bekannt (Smithery). */
  vollstaendig: boolean;
  aktualisiert?: string | null;
}
export interface VerzeichnisSuche { treffer: VerzeichnisTreffer[]; fehler: Record<string, string> }
export interface VerzeichnisInstallieren { quelle: string; kennung: string; werte?: Record<string, string>; name?: string }
/** Eigene Registry in den Einstellungen (API des offiziellen MCP-Registry). */
export interface EigenesVerzeichnis { id: string; name: string; url: string }

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
  oauth?: { modus: string; angemeldet: boolean } | null;
  /** Herkunft aus einem Verzeichnis (Phase 2b). */
  verzeichnis?: { quelle: string; kennung: string } | null;
  /** Wirksamer Bereich: technisch (ohne Rückfrage) oder fachlich (Änderungen bestätigen). */
  bereich?: Bereich | string;
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
  verzeichnisse_eigene?: EigenesVerzeichnis[];
  /** Technische Werkzeuge (Shell, Dateien, Installationen) vor dem Ausführen bestätigen (Standard aus). */
  freigabe_technisch?: boolean;
  /** Fachliche Werkzeuge: ab „aendern“ (Standard), nur „kritisch“ oder „nie“ bestätigen. */
  freigabe_fachlich?: 'aendern' | 'kritisch' | 'nie' | string;
  /** Unterhaltungen beim Verlassen zusammenfassen und Fakten automatisch merken (Standard an). */
  gedaechtnis_automatisch?: boolean;
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
    stt?: 'auto' | 'lokal' | 'openrouter' | 'cloud' | string;
    stt_openrouter_modell?: string;
    tts?: 'auto' | 'openrouter' | 'say' | 'sapi' | 'piper' | 'espeak' | 'cloud' | 'aus' | string;
    tts_stimme?: string;
    tts_openrouter_modell?: string;
    /** Stoppwörter (Komma-getrennt), beenden die Sprachausgabe; leer = aus. */
    stoppwort?: string;
    [schluessel: string]: unknown;
  };
  [schluessel: string]: unknown;
}

export interface Erinnerung {
  id: string | number;
  text: string;
  zeit?: string;
  /** „nutzer“ (ausdrücklich gemerkt) oder „auto“ (aus der Nachbereitung einer Unterhaltung). */
  quelle?: 'nutzer' | 'auto' | string;
  aktualisiert?: string | null;
}
export interface Unterhaltung {
  id: number;
  titel: string;
  titel_fest: boolean;
  erstellt: string;
  aktualisiert: string;
  zusammenfassung: string | null;
  nachbereitet: string | null;
  nachrichten: number;
  aktuell: boolean;
}
/** Kern liefert `{id, zeit, rolle, inhalt}`; `text` wird ebenfalls akzeptiert. */
export interface VerlaufEintrag { rolle: string; inhalt?: string; text?: string; zeit?: string }

/** GET /api/stimme/modelle */
export interface StimmModelle {
  tts: { id: string; name: string; stimmen: string[]; preis_je_1m_zeichen: number | null; standard_stimme: string }[];
  stt: { id: string; name: string }[];
  fehler: string | null;
}
/** POST /api/stimme/probe */
export interface StimmProbe { ok: boolean; art: string; modell: string; stimme: string; ziel: 'browser' | 'lautsprecher' | string }
