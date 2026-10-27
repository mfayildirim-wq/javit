import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Check, KeyRound, Trash2 } from 'lucide-react';
import { api } from '../api/rest';
import type { Einstellungen, Erinnerung, Modelle } from '../api/types';
import { useJarvis, useName } from '../state/store';
import { STANDARD_NAME, weckwortAnzeige } from '../lib/name';
import { statusLaden } from '../state/verbindung';
import { modellAnbieter } from '../lib/format';

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

function ModellWahl() {
  const [modelle, setModelle] = useState<Modelle | null>(null);
  const [frei, setFrei] = useState('');
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  const laden = () =>
    api
      .modelle()
      .then(setModelle)
      .catch((e: Error) => setFehler(e.message));
  useEffect(() => {
    void laden();
  }, []);

  const setzen = async (id: string) => {
    const m = id.trim();
    if (!m) return;
    setFehler(null);
    try {
      await api.modellSetzen(m);
      setMeldung(`Modell gewechselt: ${m}`);
      setFrei('');
      await laden();
      void statusLaden();
    } catch (e) {
      setFehler((e as Error).message);
    }
  };

  return (
    <Abschnitt id="s-modell" titel="Modell" text="Lokale Modelle laufen über Ollama auf diesem Mac, Cloud-Modelle brauchen einen API-Schlüssel.">
      <ul className="modell-liste" role="radiogroup" aria-label="Modell">
        {modelle?.vorschlaege.map((m) => {
          const aktiv = modelle.aktuell === m.id;
          return (
            <li key={m.id}>
              <button
                type="button"
                role="radio"
                aria-checked={aktiv}
                className={`modell ${aktiv ? 'an' : ''} ${m.verfuegbar ? '' : 'nicht-da'}`}
                onClick={() => setzen(m.id)}
              >
                <span className="modell-name">{m.name}</span>
                <span className="modell-id">{m.id}</span>
                <span className="modell-chips">
                  <span className={`marke-chip ${m.lokal ? 'lokal' : 'cloud'}`}>{m.lokal ? 'lokal' : 'Cloud'}</span>
                  {!m.verfuegbar && <span className="marke-chip aus">{m.lokal ? 'nicht geladen' : 'Schlüssel fehlt'}</span>}
                  {aktiv && <Check size={16} aria-label="aktiv" />}
                </span>
              </button>
            </li>
          );
        })}
        {!modelle && !fehler && <li className="gedaempft">Lade Modelle …</li>}
      </ul>
      <form
        className="feld-reihe frei"
        onSubmit={(e) => {
          e.preventDefault();
          void setzen(frei);
        }}
      >
        <div className="feld">
          <label htmlFor="modell-frei">Eigene Modell-ID</label>
          <input id="modell-frei" className="mono" placeholder="z. B. ollama/llama3.1:8b oder openai/gpt-5.4-mini" value={frei} onChange={(e) => setFrei(e.target.value)} />
        </div>
        <button className="knopf" type="submit" disabled={!frei.trim()}>
          Übernehmen
        </button>
      </form>
      {frei.includes('/') && <p className="feld-hilfe">Anbieter: {modellAnbieter(frei)}</p>}
      {meldung && <p className="ok-text">{meldung}</p>}
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}

function SchluesselZeile({ name, titel }: { name: string; titel: string }) {
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
    } catch (err) {
      setFehler((err as Error).message);
      setZustand('fehler');
    }
  };
  return (
    <form className="schluessel" onSubmit={speichern}>
      <label htmlFor={`k-${name}`}>
        <span className="schluessel-titel">{titel}</span>
        <code>{name}</code>
      </label>
      <input
        id={`k-${name}`}
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

function Schluessel() {
  const [eigener, setEigener] = useState('');
  const [extra, setExtra] = useState<string[]>([]);
  return (
    <Abschnitt id="s-schluessel" titel="API-Schlüssel" text="Werden im macOS-Schlüsselbund abgelegt und nie wieder angezeigt.">
      {SCHLUESSEL.map((s) => (
        <SchluesselZeile key={s.name} name={s.name} titel={s.titel} />
      ))}
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
  tts: string;
  stimme: string;
  sir: boolean;
  anrede: string;
}

function entwurfAus(e: Einstellungen): Entwurf {
  return {
    name: typeof e.name === 'string' ? e.name : STANDARD_NAME,
    aktiv: e.stimme?.aktiv ?? false,
    weckwort: typeof e.stimme?.weckwort === 'string' ? e.stimme.weckwort : 'javit',
    engine: e.stimme?.weckwort_engine ?? 'auto',
    schwelle: typeof e.stimme?.schwelle === 'number' ? e.stimme.schwelle : 0.5,
    stt: e.stimme?.stt ?? 'lokal',
    tts: e.stimme?.tts ?? 'auto',
    stimme: e.stimme?.tts_stimme ?? '',
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
      tts: d.tts,
      tts_stimme: d.stimme.trim(),
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

/** Sprachausgabe-Optionen je Plattform (Kern: jarvis/stimme/tts.py, „auto“ = say/SAPI/Piper). */
export function ttsOptionen(plattform: string | undefined, aktuell: string): [string, string][] {
  const lokal: [string, string] =
    plattform === 'windows' ? ['sapi', 'Windows-Stimme'] : plattform === 'linux' ? ['piper', 'Piper'] : ['say', 'macOS say'];
  const optionen: [string, string][] = [['auto', 'Automatisch'], lokal, ['cloud', 'Cloud'], ['aus', 'Aus']];
  if (!optionen.some(([w]) => w === aktuell)) optionen.splice(2, 0, [aktuell, aktuell]);
  return optionen;
}

function StimmePersona() {
  const plattform = useJarvis((s) => s.status?.plattform);
  const [basis, setBasis] = useState<Entwurf | null>(null);
  const [d, setD] = useState<Entwurf | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [speichert, setSpeichert] = useState(false);

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

  if (!d) return <Abschnitt id="s-stimme" titel="Stimme und Persona">{fehler ? <p className="formular-fehler">{fehler}</p> : <p className="gedaempft">Lade Einstellungen …</p>}</Abschnitt>;

  const anzeigeName = d.name.trim() || STANDARD_NAME;
  const set = (teil: Partial<Entwurf>) => {
    setMeldung(null);
    setD({ ...d, ...teil });
  };
  const geaendert = JSON.stringify(d) !== JSON.stringify(basis);

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
        <Segmente label="Spracherkennung" wert={d.stt} optionen={[['lokal', 'Lokal (Whisper)'], ['cloud', 'Cloud']]} onChange={(v) => set({ stt: v })} />
        <Segmente label="Sprachausgabe" wert={d.tts} optionen={ttsOptionen(plattform, d.tts)} onChange={(v) => set({ tts: v })} />
        <div className="feld">
          <label htmlFor="stimme-name">Stimme</label>
          <input id="stimme-name" placeholder="leer = automatisch, z. B. Anna oder onyx" value={d.stimme} onChange={(e) => set({ stimme: e.target.value })} disabled={d.tts === 'aus'} />
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

function Gedaechtnis() {
  const name = useName();
  const [liste, setListe] = useState<Erinnerung[] | null>(null);
  const [bestaetigen, setBestaetigen] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const laden = () =>
    api
      .gedaechtnis()
      .then(setListe)
      .catch((e: Error) => setFehler(e.message));
  useEffect(() => {
    void laden();
  }, []);
  const loeschen = async () => {
    try {
      await api.gedaechtnisLoeschen();
      setBestaetigen(false);
      await laden();
    } catch (e) {
      setFehler((e as Error).message);
    }
  };
  return (
    <Abschnitt id="s-gedaechtnis" titel="Gedächtnis" text={`Was ${name} sich über Sie gemerkt hat.`}>
      {liste === null && !fehler && <p className="gedaempft">Lade …</p>}
      {liste?.length === 0 && <p className="gedaempft">Noch keine Erinnerungen gespeichert.</p>}
      {liste && liste.length > 0 && (
        <ul className="erinnerungen">
          {liste.map((e, i) => (
            <li key={e.id ?? i}>
              <span>{e.text}</span>
              {e.zeit && <time className="gedaempft">{new Date(e.zeit).toLocaleDateString('de-DE')}</time>}
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
              <button className="knopf gefahr klein" onClick={loeschen}>
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

export function EinstellungenAnsicht() {
  const verbindung = useJarvis((s) => s.verbindung);
  return (
    <section className="ansicht" aria-labelledby="einst-titel">
      <header className="ansicht-kopf">
        <div>
          <h1 id="einst-titel">Einstellungen</h1>
          <p>Modell, Schlüssel, Stimme und Gedächtnis. Änderungen gelten sofort.</p>
        </div>
      </header>
      <div className="ansicht-inhalt einstellungen" key={verbindung === 'offen' ? 'on' : 'off'}>
        <ModellWahl />
        <Schluessel />
        <StimmePersona />
        <Gedaechtnis />
      </div>
    </section>
  );
}
