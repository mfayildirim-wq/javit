import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Check, KeyRound, MessageSquarePlus, Pencil, Plus, RefreshCw, Trash2, Volume2 } from 'lucide-react';
import { api } from '../api/rest';
import type { AnbieterInfo, EigenerAnbieter, EigenesVerzeichnis, Einstellungen, Erinnerung, Modelle, ModellVorschlag, StimmModelle, Unterhaltung } from '../api/types';
import { useJarvis, useName } from '../state/store';
import { STANDARD_NAME, weckwortAnzeige } from '../lib/name';
import { neueUnterhaltung, statusLaden, unterhaltungOeffnen } from '../state/verbindung';
import { modellAnbieter } from '../lib/format';

export type Reiter = 'modell' | 'stimme' | 'freigaben' | 'gedaechtnis' | 'erweitert';
export const REITER: { id: Reiter; titel: string }[] = [
  { id: 'modell', titel: 'Modell' },
  { id: 'stimme', titel: 'Stimme' },
  { id: 'freigaben', titel: 'Freigaben' },
  { id: 'gedaechtnis', titel: 'Gedächtnis' },
  { id: 'erweitert', titel: 'Erweitert' },
];

function reiterLaden(): Reiter {
  try {
    const r = localStorage.getItem('jarvis.einstellungen.reiter');
    if (r && REITER.some((x) => x.id === r)) return r as Reiter;
  } catch {
    /* egal */
  }
  return 'modell';
}

/** Versionszahl einer Modell-ID für die Sortierung (neueste zuerst): „claude-sonnet-4-5-20250929“ → 4.5,
 * „deepseek-v4.1-flash“ → 4.1, „llama3.1:8b“ → 3.1, „gpt-4o“ → 4; Datumsanhänge (6+ Ziffern) zählen nicht. */
export function versionsZahl(id: string): number {
  const ohneDatum = id.replace(/\d{6,}/g, '');
  const m = ohneDatum.match(/(?<!\d)(\d{1,3})(?:[.-](\d{1,3}))?(?!\d)/);
  if (!m) return 0;
  const major = Number(m[1]);
  const minor = m[2] ? Number(m[2]) : 0;
  return major + (minor < 10 ? minor / 10 : minor / 100);
}

export const MODELLE_SICHTBAR = 8;

export const SCHLUESSEL = [
  { name: 'ANTHROPIC_API_KEY', titel: 'Anthropic (Claude)' },
  { name: 'OPENAI_API_KEY', titel: 'OpenAI (GPT)' },
  { name: 'GEMINI_API_KEY', titel: 'Google Gemini' },
  { name: 'GROQ_API_KEY', titel: 'Groq' },
  { name: 'MISTRAL_API_KEY', titel: 'Mistral' },
  { name: 'OPENROUTER_API_KEY', titel: 'OpenRouter' },
] as const;

function Abschnitt({ titel, text, children, id }: { titel: string; text?: string; children: ReactNode; id: string }) {
  return (
    <section className="abschnitt" aria-labelledby={id}>
      <header>
        <h2 id={id}>{titel}</h2>
        {text && <p>{text}</p>}
      </header>
      <div className="abschnitt-inhalt">{children}</div>
    </section>
  );
}

function Schalter({ an, onChange, label, beschreibung }: { an: boolean; onChange: (v: boolean) => void; label: string; beschreibung?: string }) {
  return (
    <label className="schalter-zeile">
      <span>
        <span className="schalter-label">{label}</span>
        {beschreibung && <span className="schalter-text">{beschreibung}</span>}
      </span>
      <input type="checkbox" role="switch" className="schalter" checked={an} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function Segmente<T extends string>({ wert, optionen, onChange, label }: { wert: T; optionen: [T, string][]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="feld">
      <span className="feld-label">{label}</span>
      <div className="seg-gruppe" role="radiogroup" aria-label={label}>
        {optionen.map(([v, t]) => (
          <button type="button" key={v} role="radio" aria-checked={wert === v} className={wert === v ? 'an' : ''} onClick={() => onChange(v)}>
            {t}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Anbieter des Modells aus der ID („openrouter/x/y“ → „openrouter“); ollama_chat zählt als ollama. */
export function anbieterVonModell(id: string): string {
  const p = id.includes('/') ? (id.split('/')[0] ?? '') : '';
  return p === 'ollama_chat' ? 'ollama' : p;
}

/** Anbieterliste aus der Antwort; ältere Kerne ohne `anbieter` → aus den Vorschlägen abgeleitet. */
export function anbieterAus(m: Modelle): AnbieterInfo[] {
  if (m.anbieter && m.anbieter.length) return m.anbieter;
  const gesehen = new Map<string, AnbieterInfo>();
  for (const v of m.vorschlaege) {
    const id = v.anbieter ?? anbieterVonModell(v.id);
    if (!id || gesehen.has(id)) continue;
    gesehen.set(id, { id, name: modellAnbieter(v.id), schluessel: null, verfuegbar: v.verfuegbar, lokal: v.lokal, eigen: false });
  }
  return [...gesehen.values()];
}

/** Kennung für einen eigenen Anbieter aus dem Namen („LM Studio“ → „lm-studio“). */
export function anbieterKennung(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 31);
}

/** Schlüsselname für einen eigenen Anbieter („lm-studio“ → „LM_STUDIO_API_KEY“). */
export function schluesselName(kennung: string): string {
  const k = kennung.toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return k ? `${k}_API_KEY` : '';
}

function AnbieterNeu({ onAngelegt }: { onAngelegt: (kennung: string) => void }) {
  const [offen, setOffen] = useState(false);
  const [name, setName] = useState('');
  const [basis, setBasis] = useState('');
  const [schluessel, setSchluessel] = useState('');
  const [wert, setWert] = useState('');
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const kennung = anbieterKennung(name);
  const schluesselVorschlag = schluesselName(kennung);
  const schluesselFinal = (schluessel.trim() || schluesselVorschlag).toUpperCase();

  const anlegen = async (e: FormEvent) => {
    e.preventDefault();
    if (!kennung || !basis.trim()) return;
    setLaeuft(true);
    setFehler(null);
    try {
      const aktuell = await api.einstellungen();
      const bisher = (aktuell?.anbieter_eigene ?? []).filter((a) => a.id !== kennung);
      const eintrag: EigenerAnbieter = { id: kennung, name: name.trim(), api_base: basis.trim(), schluessel: wert.trim() ? schluesselFinal : schluessel.trim() ? schluesselFinal : null };
      await api.einstellungenSpeichern({ anbieter_eigene: [...bisher, eintrag] });
      if (wert.trim()) await api.geheimnisSetzen(schluesselFinal, wert.trim());
      setName('');
      setBasis('');
      setSchluessel('');
      setWert('');
      setOffen(false);
      onAngelegt(kennung);
    } catch (err) {
      setFehler((err as Error).message);
    } finally {
      setLaeuft(false);
    }
  };

  if (!offen)
    return (
      <button type="button" className="knopf klein" onClick={() => setOffen(true)}>
        <Plus size={14} aria-hidden="true" /> Anbieter hinzufügen
      </button>
    );
  return (
    <form className="anbieter-neu" onSubmit={anlegen} aria-label="Eigenen Anbieter anlegen">
      <div className="feld">
        <label htmlFor="anbieter-name">Name</label>
        <input id="anbieter-name" placeholder="z. B. LM Studio" value={name} onChange={(e) => setName(e.target.value)} />
        {kennung && <p className="feld-hilfe">Kennung: <code>{kennung}</code> – Modell-IDs lauten dann <code>{kennung}/…</code></p>}
      </div>
      <div className="feld">
        <label htmlFor="anbieter-basis">Basis-URL (OpenAI-kompatibel)</label>
        <input id="anbieter-basis" className="mono" placeholder="http://127.0.0.1:1234/v1" value={basis} onChange={(e) => setBasis(e.target.value)} />
      </div>
      <div className="feld">
        <label htmlFor="anbieter-schluessel">Schlüsselname (optional)</label>
        <input id="anbieter-schluessel" className="mono" placeholder={schluesselVorschlag || 'NAME_API_KEY'} value={schluessel} onChange={(e) => setSchluessel(e.target.value)} />
      </div>
      <div className="feld">
        <label htmlFor="anbieter-wert">API-Schlüssel (optional, Schlüsselbund)</label>
        <input id="anbieter-wert" type="password" autoComplete="new-password" placeholder="leer lassen für Server ohne Schlüssel" value={wert} onChange={(e) => setWert(e.target.value)} />
      </div>
      <div className="feld-reihe">
        <button className="knopf" type="submit" disabled={!kennung || !basis.trim() || laeuft}>
          Anlegen
        </button>
        <button className="knopf klein" type="button" onClick={() => setOffen(false)}>
          Abbrechen
        </button>
      </div>
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </form>
  );
}

function ModellWahl() {
  const [uebersicht, setUebersicht] = useState<Modelle | null>(null);
  const [gewaehlt, setGewaehlt] = useState<string | null>(null);
  const [liste, setListe] = useState<ModellVorschlag[] | null>(null);
  const [laedt, setLaedt] = useState(false);
  const [frei, setFrei] = useState('');
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [entfernen, setEntfernen] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [nurKostenlos, setNurKostenlos] = useState(false);
  const [alleZeigen, setAlleZeigen] = useState(false);

  const uebersichtLaden = async (): Promise<Modelle | null> => {
    try {
      const m = await api.modelle();
      setUebersicht(m);
      return m;
    } catch (e) {
      setFehler((e as Error).message);
      return null;
    }
  };

  const listeLaden = async (anbieter: string, neu = false) => {
    setLaedt(true);
    setFehler(null);
    try {
      const m = await api.modelle(anbieter, neu);
      setListe(m.vorschlaege);
      setUebersicht((alt) => (alt ? { ...alt, aktuell: m.aktuell, anbieter: m.anbieter ?? alt.anbieter } : m));
    } catch (e) {
      setFehler((e as Error).message);
      setListe([]);
    } finally {
      setLaedt(false);
    }
  };

  const waehlen = (anbieter: string, neu = false) => {
    setGewaehlt(anbieter);
    setFilter('');
    setNurKostenlos(false);
    setAlleZeigen(false);
    void listeLaden(anbieter, neu);
  };

  useEffect(() => {
    void uebersichtLaden().then((m) => {
      if (!m) return;
      const anbieter = anbieterAus(m);
      const aktuellAnbieter = anbieterVonModell(m.aktuell);
      const start = anbieter.find((a) => a.id === aktuellAnbieter)?.id ?? anbieter.find((a) => a.verfuegbar)?.id ?? anbieter[0]?.id ?? null;
      if (start) waehlen(start);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setzen = async (id: string) => {
    const m = id.trim();
    if (!m) return;
    setFehler(null);
    try {
      await api.modellSetzen(m);
      setMeldung(`Modell gewechselt: ${m}`);
      setFrei('');
      setUebersicht((alt) => (alt ? { ...alt, aktuell: m } : alt));
      void statusLaden();
    } catch (e) {
      setFehler((e as Error).message);
    }
  };

  const anbieterEntfernen = async (kennung: string) => {
    setFehler(null);
    try {
      const aktuell = await api.einstellungen();
      await api.einstellungenSpeichern({ anbieter_eigene: (aktuell?.anbieter_eigene ?? []).filter((a) => a.id !== kennung) });
      setEntfernen(null);
      const m = await uebersichtLaden();
      if (gewaehlt === kennung) waehlen(anbieterAus(m ?? { aktuell: '', vorschlaege: [] })[0]?.id ?? 'ollama');
    } catch (e) {
      setFehler((e as Error).message);
    }
  };

  const anbieter = uebersicht ? anbieterAus(uebersicht) : [];
  const aktiv = anbieter.find((a) => a.id === gewaehlt) ?? null;
  const aktuell = uebersicht?.aktuell ?? '';
  const live = (liste ?? []).some((m) => m.live);
  const hatKostenlose = (liste ?? []).some((m) => m.kostenlos === true);
  const suchtext = filter.trim().toLowerCase();
  const gefiltert = (liste ?? [])
    .filter((m) => (!nurKostenlos || m.kostenlos === true) && (!suchtext || `${m.name} ${m.id}`.toLowerCase().includes(suchtext)))
    .sort((a, b) => versionsZahl(b.id) - versionsZahl(a.id) || a.name.localeCompare(b.name, 'de'));
  // Neueste zuerst; ältere Versionen eingeklappt (das aktive Modell bleibt immer sichtbar)
  const eingeklappt = !alleZeigen && !suchtext && !nurKostenlos && gefiltert.length > MODELLE_SICHTBAR;
  const sichtbar = eingeklappt ? gefiltert.filter((m, i) => i < MODELLE_SICHTBAR || m.id === aktuell) : gefiltert;
  const versteckt = gefiltert.length - sichtbar.length;

  return (
    <Abschnitt id="s-modell" titel="Modell" text="Anbieter wählen, Schlüssel daneben eintragen, darunter das Modell. Neueste Modelle stehen oben, ältere sind eingeklappt.">
      <div className="feld-reihe anbieter-wahl">
        <div className="feld">
          <label htmlFor="anbieter-wahl">Anbieter</label>
          <select id="anbieter-wahl" value={gewaehlt ?? ''} onChange={(e) => waehlen(e.target.value)} disabled={!uebersicht}>
            {!uebersicht && <option value="">Lade Anbieter …</option>}
            {anbieter.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.verfuegbar ? '' : a.lokal ? ' – nicht erreichbar' : ' – Schlüssel fehlt'}
              </option>
            ))}
          </select>
        </div>
        {aktiv && (
          <span className={`anbieter-status ${aktiv.verfuegbar ? 'an' : ''}`} role="status">
            <span className={`led ${aktiv.verfuegbar ? 'an' : ''}`} aria-hidden="true" />
            {aktiv.lokal ? (aktiv.verfuegbar ? 'Ollama erreichbar' : 'Ollama nicht erreichbar') : aktiv.verfuegbar ? 'Schlüssel hinterlegt' : 'Schlüssel fehlt'}
          </span>
        )}
      </div>

      {aktiv && aktiv.lokal && (
        <p className="feld-hilfe">
          {aktiv.verfuegbar ? 'Ollama läuft. Weitere Modelle: ' : 'Ollama ist nicht erreichbar („ollama serve“). Modelle laden mit: '}
          <code>ollama pull &lt;modell&gt;</code>
        </p>
      )}
      {aktiv && aktiv.schluessel && (
        <SchluesselZeile name={aktiv.schluessel} titel={aktiv.name} idPraefix="m" onGespeichert={() => waehlen(aktiv.id, true)} />
      )}
      {aktiv && aktiv.eigen && (
        <div className="feld-reihe anbieter-aktionen">
          {entfernen === aktiv.id ? (
            <>
              <span className="gedaempft">Anbieter „{aktiv.name}“ entfernen?</span>
              <button type="button" className="knopf klein gefahr" onClick={() => void anbieterEntfernen(aktiv.id)}>
                Ja, entfernen
              </button>
              <button type="button" className="knopf klein" onClick={() => setEntfernen(null)}>
                Abbrechen
              </button>
            </>
          ) : (
            <button type="button" className="knopf klein" onClick={() => setEntfernen(aktiv.id)}>
              <Trash2 size={14} aria-hidden="true" /> Anbieter entfernen
            </button>
          )}
        </div>
      )}

      <div className="modell-kopf">
        <span className="feld-hilfe">
          {laedt ? 'Lade Modelle …' : live ? 'Liste vom Anbieter' : aktiv && !aktiv.lokal ? 'Vorschläge – mit hinterlegtem Schlüssel erscheint die vollständige Liste.' : ''}
        </span>
        {aktiv && !aktiv.lokal && (
          <button type="button" className="knopf klein" onClick={() => waehlen(aktiv.id, true)} disabled={laedt}>
            <RefreshCw size={14} aria-hidden="true" /> Modelle neu laden
          </button>
        )}
      </div>
      {liste && liste.length > 8 && (
        <div className="feld-reihe modell-filter">
          <div className="feld">
            <label htmlFor="modell-filter">Filtern</label>
            <input id="modell-filter" placeholder="Name oder ID, z. B. deepseek" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </div>
          {hatKostenlose && (
            <label className="schalter-zeile kompakt">
              <span className="schalter-label">nur kostenlose</span>
              <input type="checkbox" role="switch" className="schalter" checked={nurKostenlos} onChange={(e) => setNurKostenlos(e.target.checked)} />
            </label>
          )}
          <span className="gedaempft">{gefiltert.length} von {liste.length}</span>
        </div>
      )}
      <ul className="modell-liste" role="radiogroup" aria-label="Modell">
        {sichtbar.map((m) => {
          const an = aktuell === m.id;
          return (
            <li key={m.id}>
              <button
                type="button"
                role="radio"
                aria-checked={an}
                className={`modell ${an ? 'an' : ''} ${m.verfuegbar ? '' : 'nicht-da'}`}
                onClick={() => setzen(m.id)}
              >
                <span className="modell-name">{m.name}</span>
                <span className="modell-id">{m.id}</span>
                <span className="modell-chips">
                  <span className={`marke-chip ${m.lokal ? 'lokal' : 'cloud'}`}>{m.lokal ? 'lokal' : 'Cloud'}</span>
                  {m.kostenlos === true && <span className="marke-chip frei">kostenlos</span>}
                  {m.werkzeuge === true && <span className="marke-chip werkzeuge">Werkzeuge</span>}
                  {!m.verfuegbar && <span className="marke-chip aus">{m.lokal ? 'nicht geladen' : 'Schlüssel fehlt'}</span>}
                  {an && <Check size={16} aria-label="aktiv" />}
                </span>
              </button>
            </li>
          );
        })}
        {liste && gefiltert.length === 0 && !laedt && <li className="gedaempft">Keine Modelle gefunden. Eigene Modell-ID unten eintragen.</li>}
      </ul>
      {(eingeklappt || (alleZeigen && gefiltert.length > MODELLE_SICHTBAR)) && (
        <button type="button" className="knopf klein leise modell-mehr" onClick={() => setAlleZeigen(!alleZeigen)}>
          {eingeklappt ? `${versteckt} ältere Modelle anzeigen` : 'Nur die neuesten anzeigen'}
        </button>
      )}
      <form
        className="feld-reihe frei"
        onSubmit={(e) => {
          e.preventDefault();
          void setzen(frei);
        }}
      >
        <div className="feld">
          <label htmlFor="modell-frei">Eigene Modell-ID</label>
          <input id="modell-frei" className="mono" placeholder="z. B. ollama/llama3.1:8b oder openrouter/deepseek/deepseek-v4.1-flash" value={frei} onChange={(e) => setFrei(e.target.value)} />
        </div>
        <button className="knopf" type="submit" disabled={!frei.trim()}>
          Übernehmen
        </button>
      </form>
      {frei.includes('/') && <p className="feld-hilfe">Anbieter: {modellAnbieter(frei)}</p>}
      <AnbieterNeu
        onAngelegt={(kennung) => {
          setMeldung(`Anbieter angelegt: ${kennung}`);
          void uebersichtLaden().then(() => waehlen(kennung));
        }}
      />
      {meldung && <p className="ok-text">{meldung}</p>}
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}

function SchluesselZeile({ name, titel, idPraefix = 'k', onGespeichert }: { name: string; titel: string; idPraefix?: string; onGespeichert?: () => void }) {
  const [wert, setWert] = useState('');
  const [zustand, setZustand] = useState<'leer' | 'speichert' | 'gespeichert' | 'fehler'>('leer');
  const [fehler, setFehler] = useState('');
  const speichern = async (e: FormEvent) => {
    e.preventDefault();
    if (!wert.trim()) return;
    setZustand('speichert');
    try {
      await api.geheimnisSetzen(name, wert.trim());
      setWert('');
      setZustand('gespeichert');
      onGespeichert?.();
    } catch (err) {
      setFehler((err as Error).message);
      setZustand('fehler');
    }
  };
  return (
    <form className="schluessel" onSubmit={speichern}>
      <label htmlFor={`${idPraefix}-${name}`}>
        <span className="schluessel-titel">{titel}</span>
        <code>{name}</code>
      </label>
      <input
        id={`${idPraefix}-${name}`}
        type="password"
        autoComplete="new-password"
        placeholder={zustand === 'gespeichert' ? 'Gespeichert im Schlüsselbund' : 'Schlüssel einfügen'}
        value={wert}
        onChange={(e) => {
          setWert(e.target.value);
          if (zustand !== 'speichert') setZustand('leer');
        }}
      />
      <button className="knopf klein" type="submit" disabled={!wert.trim() || zustand === 'speichert'}>
        {zustand === 'gespeichert' ? <Check size={14} aria-hidden="true" /> : <KeyRound size={14} aria-hidden="true" />}
        {zustand === 'gespeichert' ? 'Gespeichert' : 'Speichern'}
      </button>
      {zustand === 'fehler' && <p className="formular-fehler">{fehler}</p>}
    </form>
  );
}

function WeitereSchluessel() {
  const [eigener, setEigener] = useState('');
  const [extra, setExtra] = useState<string[]>([]);
  return (
    <Abschnitt id="s-schluessel" titel="Weitere Schlüssel" text="Für Integrationen und Werkzeuge, z. B. TAVILY_API_KEY. Anbieter-Schlüssel für Modelle stehen unter „Modell“, Sprach-Schlüssel laufen über OpenRouter. Alles landet im Schlüsselbund und wird nie wieder angezeigt.">
      {extra.length === 0 && <p className="gedaempft">Noch keine weiteren Schlüssel in dieser Sitzung angelegt.</p>}
      {extra.map((n) => (
        <SchluesselZeile key={n} name={n} titel="Eigener Schlüssel" />
      ))}
      <form
        className="feld-reihe frei"
        onSubmit={(e) => {
          e.preventDefault();
          const n = eigener.trim().toUpperCase().replace(/[^A-Z0-9_]/g, '_');
          if (n && !extra.includes(n)) setExtra([...extra, n]);
          setEigener('');
        }}
      >
        <div className="feld">
          <label htmlFor="eigener-schluessel">Weiterer Schlüssel</label>
          <input id="eigener-schluessel" className="mono" placeholder="NAME_DES_SCHLUESSELS" value={eigener} onChange={(e) => setEigener(e.target.value)} />
        </div>
        <button className="knopf" type="submit" disabled={!eigener.trim()}>
          Hinzufügen
        </button>
      </form>
    </Abschnitt>
  );
}

interface Entwurf {
  name: string;
  aktiv: boolean;
  weckwort: string;
  engine: string;
  schwelle: number;
  stt: string;
  sttModell: string;
  tts: string;
  ttsModell: string;
  stimme: string;
  stoppwort: string;
  sir: boolean;
  anrede: string;
}

export const STANDARD_TTS_MODELL = 'elevenlabs/eleven-flash-v2.5';
export const STANDARD_STT_MODELL = 'openai/whisper-large-v3';

function entwurfAus(e: Einstellungen): Entwurf {
  return {
    name: typeof e.name === 'string' ? e.name : STANDARD_NAME,
    aktiv: e.stimme?.aktiv ?? false,
    weckwort: typeof e.stimme?.weckwort === 'string' ? e.stimme.weckwort : 'javit',
    engine: e.stimme?.weckwort_engine ?? 'auto',
    schwelle: typeof e.stimme?.schwelle === 'number' ? e.stimme.schwelle : 0.5,
    stt: e.stimme?.stt ?? 'auto',
    sttModell: e.stimme?.stt_openrouter_modell ?? STANDARD_STT_MODELL,
    tts: e.stimme?.tts ?? 'auto',
    ttsModell: e.stimme?.tts_openrouter_modell ?? STANDARD_TTS_MODELL,
    stimme: e.stimme?.tts_stimme ?? '',
    stoppwort: typeof e.stimme?.stoppwort === 'string' ? e.stimme.stoppwort : 'stopp',
    sir: e.anrede_verwenden ?? true,
    anrede: e.anrede ?? 'Sir',
  };
}

/** Baut das Teilupdate für PUT /api/einstellungen (Schlüssel wie jarvis/konfig.py). */
export function einstellungenTeil(d: Entwurf): Partial<Einstellungen> {
  return {
    name: d.name.trim() || STANDARD_NAME,
    stimme: {
      aktiv: d.aktiv,
      weckwort: d.weckwort.trim() || 'javit',
      weckwort_engine: d.engine,
      schwelle: Math.round(d.schwelle * 100) / 100,
      stt: d.stt,
      stt_openrouter_modell: d.sttModell.trim() || STANDARD_STT_MODELL,
      tts: d.tts,
      tts_openrouter_modell: d.ttsModell.trim() || STANDARD_TTS_MODELL,
      tts_stimme: d.stimme.trim(),
      stoppwort: d.stoppwort.trim(),
    },
    anrede_verwenden: d.sir,
    anrede: d.anrede.trim() || 'Sir',
  };
}

/** Weckwort-Erkennung (Kern: jarvis/konfig.py weckwort_engine). */
export function engineOptionen(aktuell: string): [string, string][] {
  const optionen: [string, string][] = [
    ['auto', 'Automatisch'],
    ['vosk', 'Vosk (freies Wort)'],
    ['openwakeword', 'openWakeWord'],
  ];
  if (!optionen.some(([w]) => w === aktuell)) optionen.push([aktuell, aktuell]);
  return optionen;
}

/** Sprachausgabe-Optionen je Plattform (Kern: jarvis/stimme/tts.py, „auto“ = OpenRouter mit Schlüssel, sonst say/SAPI/Piper). */
export function ttsOptionen(plattform: string | undefined, aktuell: string): [string, string][] {
  const lokal: [string, string] =
    plattform === 'windows' ? ['sapi', 'Windows-Stimme'] : plattform === 'linux' ? ['piper', 'Piper'] : ['say', 'macOS say'];
  const optionen: [string, string][] = [['auto', 'Automatisch'], ['openrouter', 'OpenRouter'], lokal, ['cloud', 'Cloud'], ['aus', 'Aus']];
  if (!optionen.some(([w]) => w === aktuell)) optionen.splice(3, 0, [aktuell, aktuell]);
  return optionen;
}

/** Preis je Minute Sprache (ca. 900 Zeichen) aus dem Preis je 1 Mio. Zeichen. */
export function preisJeMinute(je1m: number | null): string {
  if (je1m === null || !Number.isFinite(je1m)) return '';
  const cent = (je1m / 1_000_000) * 900 * 100;
  const zahl = (cent < 1 ? cent.toFixed(2) : cent.toFixed(1)).replace('.', ',');
  return `ca. ${zahl} Cent je Minute`;
}

function StimmePersona() {
  const plattform = useJarvis((s) => s.status?.plattform);
  const [basis, setBasis] = useState<Entwurf | null>(null);
  const [d, setD] = useState<Entwurf | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [speichert, setSpeichert] = useState(false);
  const [modelle, setModelle] = useState<StimmModelle | null>(null);
  const [probe, setProbe] = useState<string | null>(null);
  const [probeLaeuft, setProbeLaeuft] = useState(false);

  useEffect(() => {
    api
      .einstellungen()
      .then((e) => {
        const x = entwurfAus(e ?? {});
        setBasis(x);
        setD(x);
      })
      .catch((e: Error) => setFehler(e.message));
  }, []);
  const openrouterSichtbar = d !== null && (d.tts === 'openrouter' || d.tts === 'auto' || d.stt === 'openrouter' || d.stt === 'auto');
  useEffect(() => {
    if (!openrouterSichtbar || modelle !== null) return;
    api
      .stimmeModelle()
      .then((m) => setModelle({ tts: Array.isArray(m?.tts) ? m.tts : [], stt: Array.isArray(m?.stt) ? m.stt : [], fehler: m?.fehler ?? null }))
      .catch((e: Error) => setModelle({ tts: [], stt: [], fehler: e.message }));
  }, [openrouterSichtbar, modelle]);

  if (!d) return <Abschnitt id="s-stimme" titel="Stimme und Persona">{fehler ? <p className="formular-fehler">{fehler}</p> : <p className="gedaempft">Lade Einstellungen …</p>}</Abschnitt>;

  const anzeigeName = d.name.trim() || STANDARD_NAME;
  const set = (teil: Partial<Entwurf>) => {
    setMeldung(null);
    setD({ ...d, ...teil });
  };
  const geaendert = JSON.stringify(d) !== JSON.stringify(basis);
  const ttsEintrag = modelle?.tts.find((m) => m.id === d.ttsModell) ?? null;

  const probeSprechen = async () => {
    setProbeLaeuft(true);
    setProbe(null);
    try {
      if (geaendert) {
        await api.einstellungenSpeichern(einstellungenTeil(d));
        setBasis(d);
      }
      const r = await api.stimmeProbe();
      setProbe(`Probe gesprochen (${r.art}${r.modell ? `, ${r.modell}` : ''}${r.stimme ? `, Stimme „${r.stimme}“` : ''}, ${r.ziel === 'browser' ? 'im Browser' : 'am Rechner'}).`);
    } catch (err) {
      setProbe(`Probe fehlgeschlagen: ${(err as Error).message}`);
    } finally {
      setProbeLaeuft(false);
    }
  };

  const speichern = async (e: FormEvent) => {
    e.preventDefault();
    setSpeichert(true);
    setFehler(null);
    try {
      await api.einstellungenSpeichern(einstellungenTeil(d));
      setBasis(d);
      setMeldung('Einstellungen gespeichert.');
      if (basis && (basis.aktiv !== d.aktiv || basis.name !== d.name || basis.weckwort !== d.weckwort || basis.engine !== d.engine))
        void statusLaden();
    } catch (err) {
      setFehler((err as Error).message);
    } finally {
      setSpeichert(false);
    }
  };

  return (
    <form onSubmit={speichern}>
      <Abschnitt id="s-stimme" titel="Stimme" text={`Weckwort „${weckwortAnzeige(d.weckwort, anzeigeName)}“, Spracherkennung und Sprachausgabe.`}>
        <Schalter label="Sprachsteuerung aktiv" beschreibung="Mikrofon lauscht auf das Weckwort." an={d.aktiv} onChange={(v) => set({ aktiv: v })} />
        <div className="feld">
          <label htmlFor="weckwort">Weckwort</label>
          <input id="weckwort" placeholder="javit" value={d.weckwort} onChange={(e) => set({ weckwort: e.target.value })} />
          <p className="feld-hilfe">
            Freies Wort, mehrere durch Komma (z. B. „javit, hey javit“). „hey_jarvis“ nutzt das fertige openWakeWord-Modell.
          </p>
        </div>
        <Segmente
          label="Weckwort-Erkennung"
          wert={d.engine}
          optionen={engineOptionen(d.engine)}
          onChange={(v) => set({ engine: v })}
        />
        <div className="feld">
          <label htmlFor="schwelle">
            Weckwort-Empfindlichkeit <span className="wert-anzeige">{d.schwelle.toFixed(2).replace('.', ',')}</span>
          </label>
          <input id="schwelle" type="range" min={0.1} max={0.95} step={0.05} value={d.schwelle} onChange={(e) => set({ schwelle: Number(e.target.value) })} />
          <div className="feld-hilfe skala">
            <span>reagiert leicht</span>
            <span>reagiert selten</span>
          </div>
        </div>
        <Segmente
          label="Spracherkennung"
          wert={d.stt}
          optionen={[['auto', 'Automatisch'], ['lokal', 'Lokal (Whisper)'], ['openrouter', 'OpenRouter'], ['cloud', 'Cloud']]}
          onChange={(v) => set({ stt: v })}
        />
        {(d.stt === 'openrouter' || d.stt === 'auto') && (
          <div className="feld">
            <label htmlFor="stt-modell">Erkennungsmodell (OpenRouter)</label>
            <select id="stt-modell" value={d.sttModell} onChange={(e) => set({ sttModell: e.target.value })}>
              {(modelle?.stt.length ? modelle.stt : [{ id: d.sttModell, name: d.sttModell }]).map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
            <p className="feld-hilfe">„Automatisch“ nutzt OpenRouter, sobald ein OpenRouter-Schlüssel hinterlegt ist, sonst Whisper lokal.</p>
          </div>
        )}
        <Segmente label="Sprachausgabe" wert={d.tts} optionen={ttsOptionen(plattform, d.tts)} onChange={(v) => set({ tts: v })} />
        {(d.tts === 'openrouter' || d.tts === 'auto') && (
          <div className="feld">
            <label htmlFor="tts-modell">Stimme (OpenRouter)</label>
            <select id="tts-modell" value={d.ttsModell} onChange={(e) => set({ ttsModell: e.target.value, stimme: '' })}>
              {(modelle?.tts.length ? modelle.tts : [{ id: d.ttsModell, name: d.ttsModell, stimmen: [], preis_je_1m_zeichen: null, standard_stimme: '' }]).map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
            <p className="feld-hilfe">
              {ttsEintrag ? `${preisJeMinute(ttsEintrag.preis_je_1m_zeichen)}${ttsEintrag.standard_stimme ? ` · Standardstimme „${ttsEintrag.standard_stimme}“` : ''}` : 'Streamt in Echtzeit über deinen OpenRouter-Schlüssel; „Automatisch“ wählt OpenRouter, sobald der Schlüssel da ist.'}
              {modelle?.fehler ? ` Modellliste nicht erreichbar: ${modelle.fehler}` : ''}
            </p>
          </div>
        )}
        <div className="feld">
          <label htmlFor="stimme-name">Stimme</label>
          {ttsEintrag && ttsEintrag.stimmen.length > 0 && (d.tts === 'openrouter' || d.tts === 'auto') ? (
            <select id="stimme-name" value={d.stimme} onChange={(e) => set({ stimme: e.target.value })}>
              <option value="">{ttsEintrag.standard_stimme ? `Standard (${ttsEintrag.standard_stimme})` : 'Standard'}</option>
              {ttsEintrag.stimmen.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          ) : (
            <input id="stimme-name" placeholder="leer = automatisch, z. B. Anna, daniel oder onyx" value={d.stimme} onChange={(e) => set({ stimme: e.target.value })} disabled={d.tts === 'aus'} />
          )}
        </div>
        <div className="feld">
          <label htmlFor="stoppwort">Stoppwort</label>
          <input id="stoppwort" placeholder="stopp" value={d.stoppwort} onChange={(e) => set({ stoppwort: e.target.value })} />
          <p className="feld-hilfe">Beendet die Sprachausgabe sofort, mehrere durch Komma (z. B. „stopp, halt“). Leer = aus.</p>
        </div>
        <div className="speichern-leiste links">
          <button className="knopf klein" type="button" onClick={() => void probeSprechen()} disabled={probeLaeuft || d.tts === 'aus'}>
            <Volume2 size={14} aria-hidden="true" /> {probeLaeuft ? 'Spricht …' : 'Probe sprechen'}
          </button>
          {probe && <span className={probe.startsWith('Probe fehlgeschlagen') ? 'formular-fehler' : 'ok-text'}>{probe}</span>}
        </div>
      </Abschnitt>
      <Abschnitt id="s-persona" titel="Persona">
        <div className="feld">
          <label htmlFor="assistent-name">Name des Assistenten</label>
          <input id="assistent-name" placeholder={STANDARD_NAME} maxLength={40} value={d.name} onChange={(e) => set({ name: e.target.value })} />
          <p className="feld-hilfe">Erscheint in Kopfzeile, Fenstertitel, Ansagen und im Systemprompt. Das Weckwort stellen Sie unter „Stimme“ ein.</p>
        </div>
        <Schalter
          label={`Mit „${d.anrede.trim() || 'Sir'}“ ansprechen`}
          beschreibung={`${anzeigeName} antwortet förmlich, etwa „Sehr wohl, ${d.anrede.trim() || 'Sir'}.“`}
          an={d.sir}
          onChange={(v) => set({ sir: v })}
        />
        <div className="feld">
          <label htmlFor="anrede">Anrede</label>
          <input id="anrede" placeholder="Sir" value={d.anrede} onChange={(e) => set({ anrede: e.target.value })} disabled={!d.sir} />
        </div>
      </Abschnitt>
      <div className="speichern-leiste">
        {meldung && <span className="ok-text">{meldung}</span>}
        {fehler && <span className="formular-fehler">{fehler}</span>}
        <button className="knopf primaer" type="submit" disabled={!geaendert || speichert}>
          {speichert ? 'Speichere …' : 'Einstellungen speichern'}
        </button>
      </div>
    </form>
  );
}

function AudioImBrowser() {
  const an = useJarvis((s) => s.audioBrowser);
  const setzen = useJarvis((s) => s.setAudioBrowser);
  return (
    <Abschnitt id="s-audio-browser" titel="Audio im Browser" text="Mikrofon und Lautsprecher dieses Geräts statt des Rechners, auf dem der Kern läuft – für Handy, Tablet oder einen entfernten Kern.">
      <Schalter label="Audio im Browser" beschreibung="Der Mikrofon-Knopf nimmt dann hier auf; Antworten werden hier abgespielt. Auf Handy und Tablet ist das Standard." an={an} onChange={setzen} />
    </Abschnitt>
  );
}

function datumKurz(wert?: string | null): string {
  if (!wert) return '';
  const d = new Date(wert);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function Unterhaltungen() {
  const aktuelle = useJarvis((s) => s.unterhaltung);
  const [liste, setListe] = useState<Unterhaltung[] | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [bearbeitet, setBearbeitet] = useState<number | null>(null);
  const [titel, setTitel] = useState('');
  const [loeschen, setLoeschen] = useState<number | null>(null);
  const laden = () =>
    api
      .unterhaltungen()
      .then((l) => {
        setListe(l);
        setFehler(null);
      })
      .catch((e: Error) => setFehler(e.message));
  useEffect(() => {
    void laden();
  }, [aktuelle?.id, aktuelle?.titel]);

  const umbenennen = async (id: number) => {
    const t = titel.trim();
    if (!t) return;
    try {
      await api.unterhaltungUmbenennen(id, t);
      setBearbeitet(null);
      await laden();
    } catch (e) {
      setFehler((e as Error).message);
    }
  };
  const entfernen = async (id: number) => {
    try {
      const ergebnis = await api.unterhaltungLoeschen(id);
      setLoeschen(null);
      useJarvis.getState().verarbeiten({ typ: 'unterhaltung', id: ergebnis.aktuell.id, titel: ergebnis.aktuell.titel, grund: 'geloescht' });
      await laden();
    } catch (e) {
      setFehler((e as Error).message);
    }
  };

  return (
    <Abschnitt id="s-unterhaltungen" titel="Unterhaltungen" text="Frühere Unterhaltungen öffnen, umbenennen oder löschen. Erinnerungen bleiben davon unberührt.">
      <div className="speichern-leiste links">
        <button className="knopf klein" onClick={() => void neueUnterhaltung()}>
          <MessageSquarePlus size={14} aria-hidden="true" /> Neue Unterhaltung
        </button>
      </div>
      {liste === null && !fehler && <p className="gedaempft">Lade …</p>}
      {liste && liste.length > 0 && (
        <ul className="unterhaltungen-liste" aria-label="Unterhaltungen">
          {liste.map((u) => (
            <li key={u.id} className={u.aktuell ? 'aktuell' : undefined}>
              {bearbeitet === u.id ? (
                <form
                  className="unterhaltung-umbenennen"
                  onSubmit={(e: FormEvent) => {
                    e.preventDefault();
                    void umbenennen(u.id);
                  }}
                >
                  <input aria-label="Neuer Titel" value={titel} maxLength={80} onChange={(e) => setTitel(e.target.value)} autoFocus />
                  <button className="knopf klein" type="submit">Speichern</button>
                  <button className="knopf klein leise" type="button" onClick={() => setBearbeitet(null)}>Abbrechen</button>
                </form>
              ) : (
                <>
                  <button className="unterhaltung-oeffnen" onClick={() => void unterhaltungOeffnen(u.id)} aria-label={`${u.titel} öffnen`}>
                    <span className="unterhaltung-name">{u.titel}</span>
                    <span className="gedaempft">
                      {datumKurz(u.aktualisiert)} · {u.nachrichten} {u.nachrichten === 1 ? 'Nachricht' : 'Nachrichten'}
                      {u.aktuell && ' · aktuell'}
                    </span>
                    {u.zusammenfassung && <span className="unterhaltung-zusammenfassung gedaempft">{u.zusammenfassung}</span>}
                  </button>
                  <span className="unterhaltung-aktionen">
                    <button
                      className="knopf klein leise"
                      aria-label={`${u.titel} umbenennen`}
                      onClick={() => {
                        setBearbeitet(u.id);
                        setTitel(u.titel);
                      }}
                    >
                      <Pencil size={13} aria-hidden="true" />
                    </button>
                    {loeschen === u.id ? (
                      <>
                        <button className="knopf gefahr klein" onClick={() => void entfernen(u.id)}>Ja, löschen</button>
                        <button className="knopf klein leise" onClick={() => setLoeschen(null)}>Behalten</button>
                      </>
                    ) : (
                      <button className="knopf klein leise" aria-label={`${u.titel} löschen`} onClick={() => setLoeschen(u.id)}>
                        <Trash2 size={13} aria-hidden="true" />
                      </button>
                    )}
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}

function Gedaechtnis() {
  const name = useName();
  const [liste, setListe] = useState<Erinnerung[] | null>(null);
  const [automatisch, setAutomatisch] = useState<boolean | null>(null);
  const [bestaetigen, setBestaetigen] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const laden = () =>
    api
      .gedaechtnis()
      .then(setListe)
      .catch((e: Error) => setFehler(e.message));
  useEffect(() => {
    void laden();
    api
      .einstellungen()
      .then((e) => setAutomatisch(e.gedaechtnis_automatisch !== false))
      .catch(() => setAutomatisch(true));
  }, []);
  const loeschen = async (id?: string | number) => {
    try {
      await api.gedaechtnisLoeschen(id);
      setBestaetigen(false);
      await laden();
    } catch (e) {
      setFehler((e as Error).message);
    }
  };
  const automatischSetzen = async (an: boolean) => {
    setAutomatisch(an);
    try {
      await api.einstellungenSpeichern({ gedaechtnis_automatisch: an });
    } catch (e) {
      setFehler((e as Error).message);
    }
  };
  return (
    <Abschnitt id="s-gedaechtnis" titel="Gedächtnis" text={`Was ${name} sich über Sie gemerkt hat.`}>
      {automatisch !== null && (
        <Schalter
          an={automatisch}
          onChange={(v) => void automatischSetzen(v)}
          label="Automatisch merken"
          beschreibung={`${name} fasst jede Unterhaltung beim Verlassen zusammen und merkt sich dauerhafte Fakten über Sie.`}
        />
      )}
      {liste === null && !fehler && <p className="gedaempft">Lade …</p>}
      {liste?.length === 0 && <p className="gedaempft">Noch keine Erinnerungen gespeichert.</p>}
      {liste && liste.length > 0 && (
        <ul className="erinnerungen">
          {liste.map((e, i) => (
            <li key={e.id ?? i}>
              <span>{e.text}</span>
              <span className="erinnerung-meta">
                <span className={`marke-chip ${e.quelle === 'auto' ? 'quelle' : ''}`}>{e.quelle === 'auto' ? 'automatisch' : 'von Ihnen'}</span>
                {e.zeit && <time className="gedaempft">{datumKurz(e.zeit)}</time>}
                <button className="knopf klein leise" aria-label={`Erinnerung löschen: ${e.text}`} onClick={() => void loeschen(e.id)}>
                  <Trash2 size={13} aria-hidden="true" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {fehler && <p className="formular-fehler">{fehler}</p>}
      {liste && liste.length > 0 && (
        <div className="speichern-leiste links">
          {bestaetigen ? (
            <>
              <span>Alle {liste.length} Erinnerungen endgültig löschen?</span>
              <button className="knopf gefahr klein" onClick={() => void loeschen()}>
                Ja, löschen
              </button>
              <button className="knopf klein leise" onClick={() => setBestaetigen(false)}>
                Behalten
              </button>
            </>
          ) : (
            <button className="knopf klein leise" onClick={() => setBestaetigen(true)}>
              <Trash2 size={14} aria-hidden="true" /> Gedächtnis löschen
            </button>
          )}
        </div>
      )}
    </Abschnitt>
  );
}

function Freigaben() {
  const [technisch, setTechnisch] = useState(false);
  const [fachlich, setFachlich] = useState<string>('aendern');
  const [fehler, setFehler] = useState<string | null>(null);
  useEffect(() => {
    api
      .einstellungen()
      .then((e) => {
        setTechnisch(Boolean(e?.freigabe_technisch));
        setFachlich(e?.freigabe_fachlich ?? 'aendern');
      })
      .catch(() => undefined);
  }, []);
  const speichern = async (teil: Partial<Einstellungen>) => {
    setFehler(null);
    try {
      const e = await api.einstellungenSpeichern(teil);
      setTechnisch(Boolean(e?.freigabe_technisch));
      setFachlich(e?.freigabe_fachlich ?? 'aendern');
    } catch (err) {
      setFehler((err as Error).message);
    }
  };
  return (
    <Abschnitt id="einst-freigaben" titel="Freigaben" text="Technische Werkzeuge (Dateien, Shell, Apps, Installationen, Entwicklung) laufen ohne Rückfrage mit den Rechten deines Benutzers – nur Dateien löschen und Zugangsdaten lesen werden immer bestätigt. Fachliche Werkzeuge (Nachrichten, Termine, Einträge in Diensten, Geld) legt der Assistent dir vor. Welche Integration als technisch oder fachlich gilt, stellst du auf ihrer Detailseite ein.">
      <Schalter
        an={technisch}
        onChange={(v) => void speichern({ freigabe_technisch: v })}
        label="Technische Aktionen bestätigen"
        beschreibung="Auch Shell-Befehle, Installationen und Schreiben in Systemordner vor dem Ausführen anzeigen"
      />
      <Segmente
        wert={fachlich}
        optionen={[
          ['aendern', 'Ab Ändern'],
          ['kritisch', 'Nur Kritisches'],
          ['nie', 'Nie'],
        ]}
        onChange={(v) => void speichern({ freigabe_fachlich: v })}
        label="Fachliche Aktionen bestätigen"
      />
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}

function Verzeichnisse() {
  const [eigene, setEigene] = useState<EigenesVerzeichnis[]>([]);
  const [offen, setOffen] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const laden = () =>
    api
      .einstellungen()
      .then((e) => setEigene(e?.verzeichnisse_eigene ?? []))
      .catch(() => undefined);
  useEffect(() => {
    void laden();
  }, []);
  const kennung = anbieterKennung(name);
  const speichern = async (liste: EigenesVerzeichnis[]) => {
    setLaeuft(true);
    setFehler(null);
    try {
      const e = await api.einstellungenSpeichern({ verzeichnisse_eigene: liste });
      setEigene(e?.verzeichnisse_eigene ?? liste);
      return true;
    } catch (err) {
      setFehler((err as Error).message);
      return false;
    } finally {
      setLaeuft(false);
    }
  };
  const anlegen = async (e: FormEvent) => {
    e.preventDefault();
    if (!kennung || !url.trim()) return;
    if (await speichern([...eigene.filter((v) => v.id !== kennung), { id: kennung, name: name.trim(), url: url.trim() }])) {
      setName('');
      setUrl('');
      setOffen(false);
    }
  };
  return (
    <Abschnitt id="einst-verzeichnisse" titel="Verzeichnisse" text="Wo „Integrationen → Hinzufügen → Suchen“ nach MCP-Servern sucht. Eingebaut: offizielles MCP-Registry und Smithery. Eigene Registries müssen die API des offiziellen Registry sprechen (/v0/servers).">
      <ul className="verzeichnis-liste" aria-label="Eigene Verzeichnisse">
        <li>
          <span>MCP-Registry (offiziell)</span>
          <code>https://registry.modelcontextprotocol.io</code>
          <span className="marke-chip offiziell">eingebaut</span>
        </li>
        <li>
          <span>Smithery</span>
          <code>https://registry.smithery.ai</code>
          <span className="marke-chip offiziell">eingebaut</span>
        </li>
        {eigene.map((v) => (
          <li key={v.id}>
            <span>{v.name || v.id}</span>
            <code>{v.url}</code>
            <button type="button" className="knopf klein leise" disabled={laeuft} onClick={() => void speichern(eigene.filter((x) => x.id !== v.id))} aria-label={`${v.name || v.id} entfernen`}>
              <Trash2 size={14} aria-hidden="true" /> Entfernen
            </button>
          </li>
        ))}
      </ul>
      {offen ? (
        <form className="anbieter-neu" onSubmit={anlegen} aria-label="Eigenes Verzeichnis anlegen">
          <div className="feld">
            <label htmlFor="verz-name">Name</label>
            <input id="verz-name" placeholder="z. B. Firmen-Registry" value={name} onChange={(e) => setName(e.target.value)} />
            {kennung && <p className="feld-hilfe">Kennung: <code>{kennung}</code></p>}
          </div>
          <div className="feld">
            <label htmlFor="verz-url">Basis-URL (https)</label>
            <input id="verz-url" className="mono" placeholder="https://registry.firma.example" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div className="feld-reihe">
            <button className="knopf" type="submit" disabled={!kennung || !url.trim() || laeuft}>
              Anlegen
            </button>
            <button className="knopf klein" type="button" onClick={() => setOffen(false)}>
              Abbrechen
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="knopf klein" onClick={() => setOffen(true)}>
          <Plus size={14} aria-hidden="true" /> Registry hinzufügen
        </button>
      )}
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}

export function EinstellungenAnsicht() {
  const verbindung = useJarvis((s) => s.verbindung);
  const [reiter, setReiter] = useState<Reiter>(() => reiterLaden());
  const waehlen = (r: Reiter) => {
    setReiter(r);
    try {
      localStorage.setItem('jarvis.einstellungen.reiter', r);
    } catch {
      /* egal */
    }
  };
  return (
    <section className="ansicht" aria-labelledby="einst-titel">
      <header className="ansicht-kopf">
        <div>
          <h1 id="einst-titel">Einstellungen</h1>
          <p>Modell, Stimme, Freigaben, Gedächtnis. Änderungen gelten sofort.</p>
        </div>
      </header>
      <nav className="reiter einstellungen-reiter" role="tablist" aria-label="Einstellungsbereiche">
        {REITER.map((r) => (
          <button key={r.id} type="button" role="tab" aria-selected={reiter === r.id} className="reiter-knopf" onClick={() => waehlen(r.id)}>
            {r.titel}
          </button>
        ))}
      </nav>
      <div className="ansicht-inhalt einstellungen" key={`${reiter}-${verbindung === 'offen' ? 'on' : 'off'}`} role="tabpanel">
        {reiter === 'modell' && <ModellWahl />}
        {reiter === 'stimme' && (
          <>
            <StimmePersona />
            <AudioImBrowser />
          </>
        )}
        {reiter === 'freigaben' && <Freigaben />}
        {reiter === 'gedaechtnis' && (
          <>
            <Unterhaltungen />
            <Gedaechtnis />
          </>
        )}
        {reiter === 'erweitert' && (
          <>
            <WeitereSchluessel />
            <Verzeichnisse />
          </>
        )}
      </div>
    </section>
  );
}
