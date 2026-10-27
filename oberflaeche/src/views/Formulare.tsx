import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { Minus, Plus } from 'lucide-react';
import type { IntegrationAnlegen, IntegrationDetails, KatalogEintrag } from '../api/types';
import {
  REST_METHODEN,
  katalogBody,
  mcpBefehlBody,
  mcpJsonParsen,
  mcpUrlBody,
  nameAusBefehl,
  nameAusUrl,
  openapiBody,
  restBody,
  type AuthArt,
  type Ergebnis,
  type Paar,
  type RestEntwurf,
} from '../lib/integration';

export type Anlegen = (body: IntegrationAnlegen) => Promise<void>;

function useAbsenden(onAnlegen: Anlegen) {
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const absenden = async (e: FormEvent, bauen: () => Ergebnis) => {
    e.preventDefault();
    const r = bauen();
    if (!r.ok) {
      setFehler(r.fehler);
      return;
    }
    setFehler(null);
    setLaeuft(true);
    try {
      await onAnlegen(r.body);
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  };
  return { fehler, laeuft, absenden };
}

export function Feld({
  label,
  hilfe,
  children,
  gruppe,
}: {
  label: string;
  hilfe?: ReactNode;
  children: (id: string) => ReactNode;
  /** Für zusammengesetzte Inhalte ohne einzelnes Eingabefeld. */
  gruppe?: boolean;
}) {
  const id = useId();
  return (
    <div className="feld" role={gruppe ? 'group' : undefined} aria-labelledby={gruppe ? `${id}-l` : undefined}>
      {gruppe ? (
        <span className="feld-label" id={`${id}-l`}>
          {label}
        </span>
      ) : (
        <label htmlFor={id}>{label}</label>
      )}
      {children(id)}
      {hilfe && <div className="feld-hilfe">{hilfe}</div>}
    </div>
  );
}

function Fehler({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p className="formular-fehler" role="alert">
      {text}
    </p>
  );
}

function Absenden({ laeuft, text = 'Integration hinzufügen' }: { laeuft: boolean; text?: string }) {
  return (
    <button type="submit" className="knopf primaer" disabled={laeuft}>
      {laeuft ? 'Verbinde …' : text}
    </button>
  );
}

export function PaarEditor({
  paare,
  onChange,
  schluesselLabel,
  wertLabel,
  geheim,
  beispiel,
}: {
  paare: Paar[];
  onChange: (p: Paar[]) => void;
  schluesselLabel: string;
  wertLabel: string;
  geheim?: boolean;
  beispiel?: [string, string];
}) {
  const setze = (i: number, teil: Partial<Paar>) => onChange(paare.map((p, j) => (j === i ? { ...p, ...teil } : p)));
  return (
    <div className="paare">
      {paare.map((p, i) => (
        <div className="paar" key={i}>
          <input
            aria-label={`${schluesselLabel} ${i + 1}`}
            placeholder={beispiel?.[0] ?? schluesselLabel}
            value={p.schluessel}
            onChange={(e) => setze(i, { schluessel: e.target.value })}
            className="mono"
          />
          <input
            aria-label={`${wertLabel} ${i + 1}`}
            placeholder={beispiel?.[1] ?? wertLabel}
            value={p.wert}
            type={geheim ? 'password' : 'text'}
            onChange={(e) => setze(i, { wert: e.target.value })}
          />
          <button type="button" className="icon-knopf" aria-label={`Zeile ${i + 1} entfernen`} onClick={() => onChange(paare.filter((_, j) => j !== i))}>
            <Minus size={14} />
          </button>
        </div>
      ))}
      <button type="button" className="text-knopf" onClick={() => onChange([...paare, { schluessel: '', wert: '' }])}>
        <Plus size={13} aria-hidden="true" /> {schluesselLabel} hinzufügen
      </button>
    </div>
  );
}

// ---------------- Katalog ----------------

const TYP_HILFE: Record<string, string> = {
  ordner: 'Absoluter Pfad oder ~/… – keine Platzhalter wie *.',
  datei: 'Pfad zu einer vorhandenen Datei (absolut oder ~/…).',
  url: 'Adresse mit http:// oder https://.',
};

/** Startwerte für das Katalogformular: beim Anlegen die Standardwerte, beim Bearbeiten die gespeicherten. */
function katalogStart(eintrag: KatalogEintrag, start?: Record<string, string>): Record<string, string> {
  const w: Record<string, string> = {};
  for (const f of eintrag.benoetigt) {
    const s = start?.[f.name];
    w[f.name] = s !== undefined && s !== 'gespeichert' ? s : (f.standard ?? '');
  }
  return w;
}

export function KatalogFormular({
  eintrag,
  onAnlegen,
  start,
  text,
  onAbbrechen,
}: {
  eintrag: KatalogEintrag;
  onAnlegen: Anlegen;
  /** Vorhandene Werte (Bearbeiten); Geheimnisse kommen als „gespeichert“ und bleiben leer. */
  start?: Record<string, string>;
  text?: string;
  onAbbrechen?: () => void;
}) {
  const [werte, setWerte] = useState<Record<string, string>>(() => katalogStart(eintrag, start));
  const { fehler, laeuft, absenden } = useAbsenden(onAnlegen);
  const bearbeiten = start !== undefined;
  return (
    <form className="formular" onSubmit={(e) => absenden(e, () => katalogBody(eintrag, bearbeiten ? { ...werte } : werte))}>
      {eintrag.benoetigt.length === 0 && <p className="gedaempft">{bearbeiten ? 'Dieser Eintrag hat keine einstellbaren Werte.' : 'Keine Angaben nötig – einfach hinzufügen.'}</p>}
      {eintrag.benoetigt.map((f, i) => {
        const gespeichert = bearbeiten && f.geheim && start?.[f.name] === 'gespeichert';
        const typ = f.typ ?? (f.geheim ? 'geheim' : 'text');
        return (
          <Feld
            key={f.name}
            label={f.titel + (f.optional ? ' (optional)' : '')}
            hilfe={
              <>
                <code>{f.name}</code>
                {f.beschreibung ? ` – ${f.beschreibung}` : TYP_HILFE[typ] ? ` – ${TYP_HILFE[typ]}` : ''}
                {gespeichert ? ' – gespeichert; leer lassen, um den Wert zu behalten.' : ''}
              </>
            }
          >
            {(id) => (
              <input
                id={id}
                type={f.geheim ? 'password' : typ === 'url' ? 'url' : 'text'}
                autoComplete={f.geheim ? 'new-password' : 'off'}
                autoFocus={i === 0}
                placeholder={gespeichert ? 'Gespeichert im Schlüsselbund' : (f.standard ?? (typ === 'ordner' ? '~/Documents' : ''))}
                value={werte[f.name] ?? ''}
                onChange={(e) => setWerte({ ...werte, [f.name]: e.target.value })}
                className={f.geheim ? '' : 'mono'}
              />
            )}
          </Feld>
        );
      })}
      {eintrag.hinweis && !bearbeiten && <p className="formular-hinweis">{eintrag.hinweis}</p>}
      <Fehler text={fehler} />
      <div className="feld-reihe">
        <Absenden laeuft={laeuft} text={text ?? `${eintrag.name} hinzufügen`} />
        {onAbbrechen && (
          <button type="button" className="knopf klein" onClick={onAbbrechen}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  );
}

// ---------------- Eigene ----------------

export type EigeneArt = 'mcp_befehl' | 'mcp_url' | 'openapi_url' | 'rest' | 'json';

export const EIGENE_ARTEN: { id: EigeneArt; titel: string; text: string }[] = [
  { id: 'mcp_befehl', titel: 'MCP-Befehl', text: 'Lokaler MCP-Server per npx, uvx oder Programm' },
  { id: 'mcp_url', titel: 'MCP-URL', text: 'Entfernter MCP-Server über HTTP' },
  { id: 'json', titel: 'JSON einfügen', text: 'Konfiguration aus Claude Desktop / Claude Code' },
  { id: 'openapi_url', titel: 'OpenAPI', text: 'Jede API mit OpenAPI-Beschreibung' },
  { id: 'rest', titel: 'REST-Endpunkt', text: 'Einzelne HTTP-Aufrufe von Hand' },
];

/** Startwerte zum Bearbeiten eigener Integrationen (Geheimnisse als „gespeichert“). */
export interface EigeneStart {
  name?: string;
  befehl?: string;
  url?: string;
  paare?: Paar[];
  authArt?: AuthArt;
}

function paareAus(werte: Record<string, string> | undefined): Paar[] {
  return Object.entries(werte ?? {}).map(([schluessel, wert]) => ({ schluessel, wert }));
}

export function JsonFormular({ onAnlegen }: { onAnlegen: Anlegen }) {
  const [text, setText] = useState('');
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const [ergebnis, setErgebnis] = useState<string[]>([]);
  const vorschau = text.trim() ? mcpJsonParsen(text) : null;
  const anlegen = async (e: FormEvent) => {
    e.preventDefault();
    const r = mcpJsonParsen(text);
    if (!r.ok) {
      setFehler(r.fehler);
      return;
    }
    setFehler(null);
    setLaeuft(true);
    const fertig: string[] = [];
    try {
      for (const eintrag of r.eintraege) {
        await onAnlegen(eintrag);
        fertig.push('name' in eintrag ? eintrag.name : eintrag.katalog);
      }
      setText('');
    } catch (err) {
      setFehler(`${fertig.length ? `${fertig.join(', ')} angelegt. ` : ''}${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setErgebnis(fertig);
      setLaeuft(false);
    }
  };
  return (
    <form className="formular" onSubmit={anlegen}>
      <Feld
        label="JSON-Konfiguration"
        hilfe={
          <>
            Format von Claude Desktop / Claude Code: <code>{'{"mcpServers": {"name": {"command": "npx", "args": ["-y", "paket"], "env": {}}}}'}</code> oder{' '}
            <code>{'{"type": "http", "url": "https://…/mcp", "headers": {"Authorization": "Bearer …"}}'}</code>. Geheimnisse landen im Schlüsselbund.
          </>
        }
      >
        {(id) => (
          <textarea
            id={id}
            className="mono"
            rows={8}
            autoFocus
            placeholder={'{\n  "mcpServers": {\n    "notion": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"], "env": {"NOTION_TOKEN": "…"}}\n  }\n}'}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        )}
      </Feld>
      {vorschau && vorschau.ok && (
        <ul className="json-vorschau" aria-label="Erkannte Server">
          {vorschau.eintraege.map((e, i) => (
            <li key={i}>
              <strong>{'name' in e ? e.name : e.katalog}</strong>{' '}
              <code>{'mcp_befehl' in e ? e.mcp_befehl : 'mcp_url' in e ? e.mcp_url : ''}</code>
            </li>
          ))}
        </ul>
      )}
      {vorschau && !vorschau.ok && text.trim().length > 20 && <p className="feld-hilfe">{vorschau.fehler}</p>}
      {ergebnis.length > 0 && !fehler && <p className="ok-text">Angelegt: {ergebnis.join(', ')}</p>}
      <Fehler text={fehler} />
      <Absenden laeuft={laeuft} text={vorschau && vorschau.ok && vorschau.eintraege.length > 1 ? `${vorschau.eintraege.length} Integrationen hinzufügen` : 'Integration hinzufügen'} />
    </form>
  );
}

export function McpBefehlFormular({ onAnlegen, start, text, onAbbrechen }: { onAnlegen: Anlegen; start?: EigeneStart; text?: string; onAbbrechen?: () => void }) {
  const [name, setName] = useState(start?.name ?? '');
  const [befehl, setBefehl] = useState(start?.befehl ?? '');
  const [umgebung, setUmgebung] = useState<Paar[]>(start?.paare ?? []);
  const { fehler, laeuft, absenden } = useAbsenden(onAnlegen);
  const vorschlag = nameAusBefehl(befehl);
  return (
    <form className="formular" onSubmit={(e) => absenden(e, () => mcpBefehlBody(name, befehl, umgebung))}>
      <Feld label="Befehl" hilfe="Wird beim Start ausgeführt und spricht MCP über stdin/stdout.">
        {(id) => (
          <input
            id={id}
            className="mono"
            autoFocus
            placeholder="npx -y @modelcontextprotocol/server-everything"
            value={befehl}
            onChange={(e) => setBefehl(e.target.value)}
          />
        )}
      </Feld>
      <Feld label="Name">{(id) => <input id={id} placeholder={vorschlag || 'Mein Werkzeug'} value={name} onChange={(e) => setName(e.target.value)} />}</Feld>
      <Feld label="Umgebungsvariablen (optional)" gruppe hilfe={start ? 'Geheime Werte stehen als „gespeichert“ – so lassen, um sie zu behalten.' : undefined}>
        {() => <PaarEditor paare={umgebung} onChange={setUmgebung} schluesselLabel="Variable" wertLabel="Wert" geheim beispiel={['API_KEY', 'Wert']} />}
      </Feld>
      <Fehler text={fehler} />
      <div className="feld-reihe">
        <Absenden laeuft={laeuft} text={text} />
        {onAbbrechen && (
          <button type="button" className="knopf klein" onClick={onAbbrechen}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  );
}

export function McpUrlFormular({ onAnlegen, start, text, onAbbrechen }: { onAnlegen: Anlegen; start?: EigeneStart; text?: string; onAbbrechen?: () => void }) {
  const [name, setName] = useState(start?.name ?? '');
  const [url, setUrl] = useState(start?.url ?? '');
  const [kopfzeilen, setKopfzeilen] = useState<Paar[]>(start?.paare ?? []);
  const { fehler, laeuft, absenden } = useAbsenden(onAnlegen);
  return (
    <form className="formular" onSubmit={(e) => absenden(e, () => mcpUrlBody(name, url, kopfzeilen))}>
      <Feld label="URL des MCP-Servers">
        {(id) => (
          <input id={id} className="mono" autoFocus inputMode="url" placeholder="http://homeassistant.local:8123/mcp" value={url} onChange={(e) => setUrl(e.target.value)} />
        )}
      </Feld>
      <Feld label="Name">{(id) => <input id={id} placeholder={nameAusUrl(url) || 'Home Assistant'} value={name} onChange={(e) => setName(e.target.value)} />}</Feld>
      <Feld label="Kopfzeilen (optional)" gruppe hilfe={start ? 'Geheime Werte stehen als „gespeichert“ – so lassen, um sie zu behalten.' : undefined}>
        {() => <PaarEditor paare={kopfzeilen} onChange={setKopfzeilen} schluesselLabel="Kopfzeile" wertLabel="Wert" geheim beispiel={['Authorization', 'Bearer …']} />}
      </Feld>
      <Fehler text={fehler} />
      <div className="feld-reihe">
        <Absenden laeuft={laeuft} text={text} />
        {onAbbrechen && (
          <button type="button" className="knopf klein" onClick={onAbbrechen}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  );
}

export function OpenApiFormular({ onAnlegen, start, text, onAbbrechen }: { onAnlegen: Anlegen; start?: EigeneStart; text?: string; onAbbrechen?: () => void }) {
  const [name, setName] = useState(start?.name ?? '');
  const [url, setUrl] = useState(start?.url ?? '');
  const [art, setArt] = useState<AuthArt>(start?.authArt ?? 'keine');
  const [wert, setWert] = useState(start?.authArt && start.authArt !== 'keine' ? 'gespeichert' : '');
  const { fehler, laeuft, absenden } = useAbsenden(onAnlegen);
  return (
    <form className="formular" onSubmit={(e) => absenden(e, () => openapiBody(name, url, art, wert))}>
      <Feld label="URL der OpenAPI-Beschreibung" hilfe="JSON oder YAML, z. B. …/openapi.json">
        {(id) => (
          <input id={id} className="mono" autoFocus inputMode="url" placeholder="https://petstore3.swagger.io/api/v3/openapi.json" value={url} onChange={(e) => setUrl(e.target.value)} />
        )}
      </Feld>
      <Feld label="Name">{(id) => <input id={id} placeholder={nameAusUrl(url) || 'Petstore'} value={name} onChange={(e) => setName(e.target.value)} />}</Feld>
      <div className="feld-reihe">
        <Feld label="Anmeldung">
          {(id) => (
            <select id={id} value={art} onChange={(e) => setArt(e.target.value as AuthArt)}>
              <option value="keine">Keine</option>
              <option value="bearer">Bearer-Token</option>
              <option value="api_key">API-Schlüssel</option>
              <option value="basic">Benutzer:Passwort</option>
            </select>
          )}
        </Feld>
        {art !== 'keine' && (
          <Feld label={art === 'basic' ? 'Benutzer:Passwort' : 'Token / Schlüssel'}>
            {(id) => <input id={id} type="password" autoComplete="new-password" value={wert} onChange={(e) => setWert(e.target.value)} />}
          </Feld>
        )}
      </div>
      <Fehler text={fehler} />
      <div className="feld-reihe">
        <Absenden laeuft={laeuft} text={text} />
        {onAbbrechen && (
          <button type="button" className="knopf klein" onClick={onAbbrechen}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  );
}

const leererEndpunkt = (): RestEntwurf => ({ name: '', methode: 'GET', url: '', beschreibung: '', parameter: [] });

export function RestFormular({ onAnlegen }: { onAnlegen: Anlegen }) {
  const [name, setName] = useState('');
  const [endpunkte, setEndpunkte] = useState<RestEntwurf[]>([leererEndpunkt()]);
  const { fehler, laeuft, absenden } = useAbsenden(onAnlegen);
  const setze = (i: number, teil: Partial<RestEntwurf>) => setEndpunkte(endpunkte.map((e, j) => (j === i ? { ...e, ...teil } : e)));

  return (
    <form className="formular" onSubmit={(e) => absenden(e, () => restBody(name, endpunkte))}>
      <Feld label="Name der Integration">{(id) => <input id={id} autoFocus placeholder="Wetter" value={name} onChange={(e) => setName(e.target.value)} />}</Feld>
      {endpunkte.map((ep, i) => (
        <fieldset className="endpunkt" key={i}>
          <legend>Endpunkt {i + 1}</legend>
          <div className="feld-reihe">
            <Feld label="Werkzeugname">
              {(id) => <input id={id} className="mono" placeholder="wetter_abrufen" value={ep.name} onChange={(e) => setze(i, { name: e.target.value })} />}
            </Feld>
            <Feld label="Methode">
              {(id) => (
                <select id={id} value={ep.methode} onChange={(e) => setze(i, { methode: e.target.value })}>
                  {REST_METHODEN.map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              )}
            </Feld>
          </div>
          <Feld label="URL">
            {(id) => <input id={id} className="mono" inputMode="url" placeholder="https://api.open-meteo.com/v1/forecast" value={ep.url} onChange={(e) => setze(i, { url: e.target.value })} />}
          </Feld>
          <Feld label="Beschreibung für das Modell">
            {(id) => <input id={id} placeholder="Aktuelles Wetter für Koordinaten abrufen" value={ep.beschreibung} onChange={(e) => setze(i, { beschreibung: e.target.value })} />}
          </Feld>
          <div className="feld">
            <span className="feld-label">Parameter</span>
            <div className="paare">
              {ep.parameter.map((p, k) => (
                <div className="paar" key={k}>
                  <input
                    aria-label={`Parameter ${k + 1} Name`}
                    className="mono"
                    placeholder="latitude"
                    value={p.name}
                    onChange={(e) => setze(i, { parameter: ep.parameter.map((q, m) => (m === k ? { ...q, name: e.target.value } : q)) })}
                  />
                  <select
                    aria-label={`Parameter ${k + 1} Typ`}
                    value={p.typ}
                    onChange={(e) =>
                      setze(i, { parameter: ep.parameter.map((q, m) => (m === k ? { ...q, typ: e.target.value as 'text' | 'zahl' | 'bool' } : q)) })
                    }
                  >
                    <option value="text">Text</option>
                    <option value="zahl">Zahl</option>
                    <option value="bool">Ja/Nein</option>
                  </select>
                  <button type="button" className="icon-knopf" aria-label={`Parameter ${k + 1} entfernen`} onClick={() => setze(i, { parameter: ep.parameter.filter((_, m) => m !== k) })}>
                    <Minus size={14} />
                  </button>
                </div>
              ))}
              <button type="button" className="text-knopf" onClick={() => setze(i, { parameter: [...ep.parameter, { name: '', typ: 'text' }] })}>
                <Plus size={13} aria-hidden="true" /> Parameter hinzufügen
              </button>
            </div>
          </div>
          {endpunkte.length > 1 && (
            <button type="button" className="text-knopf gefahr" onClick={() => setEndpunkte(endpunkte.filter((_, j) => j !== i))}>
              Endpunkt entfernen
            </button>
          )}
        </fieldset>
      ))}
      <button type="button" className="text-knopf" onClick={() => setEndpunkte([...endpunkte, leererEndpunkt()])}>
        <Plus size={13} aria-hidden="true" /> Weiteren Endpunkt
      </button>
      <Fehler text={fehler} />
      <Absenden laeuft={laeuft} />
    </form>
  );
}

export function EigeneFormular({ art, onAnlegen }: { art: EigeneArt; onAnlegen: Anlegen }) {
  switch (art) {
    case 'mcp_befehl':
      return <McpBefehlFormular onAnlegen={onAnlegen} />;
    case 'mcp_url':
      return <McpUrlFormular onAnlegen={onAnlegen} />;
    case 'json':
      return <JsonFormular onAnlegen={onAnlegen} />;
    case 'openapi_url':
      return <OpenApiFormular onAnlegen={onAnlegen} />;
    case 'rest':
      return <RestFormular onAnlegen={onAnlegen} />;
  }
}

/** Bearbeiten einer installierten Integration: passendes Formular, vorbelegt aus den Details. */
export function BearbeitenFormular({
  details,
  onSpeichern,
  onAbbrechen,
}: {
  details: IntegrationDetails;
  onSpeichern: Anlegen;
  onAbbrechen: () => void;
}) {
  const k = details.konfig;
  if (details.katalog) {
    const eintrag: KatalogEintrag = {
      id: details.katalog.id,
      name: details.katalog.name,
      beschreibung: '',
      kategorie: '',
      icon: '',
      art: details.art,
      benoetigt: details.katalog.benoetigt,
      hinweis: details.katalog.hinweis,
    };
    return <KatalogFormular eintrag={eintrag} start={details.werte ?? {}} onAnlegen={onSpeichern} text="Speichern und neu verbinden" onAbbrechen={onAbbrechen} />;
  }
  if (details.art === 'mcp_stdio') {
    const paare = paareAus(k.umgebung);
    for (const g of k.geheimnisse) if (!paare.some((p) => p.schluessel === g)) paare.push({ schluessel: g, wert: 'gespeichert' });
    return <McpBefehlFormular onAnlegen={onSpeichern} start={{ name: details.name, befehl: (k.befehl ?? []).join(' '), paare }} text="Speichern und neu verbinden" onAbbrechen={onAbbrechen} />;
  }
  if (details.art === 'mcp_http') {
    return <McpUrlFormular onAnlegen={onSpeichern} start={{ name: details.name, url: k.url ?? '', paare: paareAus(k.kopfzeilen) }} text="Speichern und neu verbinden" onAbbrechen={onAbbrechen} />;
  }
  if (details.art === 'openapi') {
    return <OpenApiFormular onAnlegen={onSpeichern} start={{ name: details.name, url: k.url ?? '', authArt: (k.auth?.art as AuthArt | undefined) ?? 'keine' }} text="Speichern und neu verbinden" onAbbrechen={onAbbrechen} />;
  }
  return <p className="gedaempft">Diese Integration lässt sich hier nicht bearbeiten. Entfernen und neu anlegen.</p>;
}
