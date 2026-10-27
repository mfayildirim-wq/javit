import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { Minus, Plus } from 'lucide-react';
import type { IntegrationAnlegen, KatalogEintrag } from '../api/types';
import {
  REST_METHODEN,
  katalogBody,
  mcpBefehlBody,
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

export function KatalogFormular({ eintrag, onAnlegen }: { eintrag: KatalogEintrag; onAnlegen: Anlegen }) {
  const [werte, setWerte] = useState<Record<string, string>>({});
  const { fehler, laeuft, absenden } = useAbsenden(onAnlegen);
  return (
    <form className="formular" onSubmit={(e) => absenden(e, () => katalogBody(eintrag, werte))}>
      {eintrag.benoetigt.length === 0 && <p className="gedaempft">Keine Angaben nötig – einfach hinzufügen.</p>}
      {eintrag.benoetigt.map((f, i) => (
        <Feld key={f.name} label={f.titel} hilfe={<code>{f.name}</code>}>
          {(id) => (
            <input
              id={id}
              type={f.geheim ? 'password' : 'text'}
              autoComplete={f.geheim ? 'new-password' : 'off'}
              autoFocus={i === 0}
              value={werte[f.name] ?? ''}
              onChange={(e) => setWerte({ ...werte, [f.name]: e.target.value })}
              className={f.geheim ? '' : 'mono'}
            />
          )}
        </Feld>
      ))}
      {eintrag.hinweis && <p className="formular-hinweis">{eintrag.hinweis}</p>}
      <Fehler text={fehler} />
      <Absenden laeuft={laeuft} text={`${eintrag.name} hinzufügen`} />
    </form>
  );
}

// ---------------- Eigene ----------------

export type EigeneArt = 'mcp_befehl' | 'mcp_url' | 'openapi_url' | 'rest';

export const EIGENE_ARTEN: { id: EigeneArt; titel: string; text: string }[] = [
  { id: 'mcp_befehl', titel: 'MCP-Befehl', text: 'Lokaler MCP-Server per npx, uvx oder Programm' },
  { id: 'mcp_url', titel: 'MCP-URL', text: 'Entfernter MCP-Server über HTTP' },
  { id: 'openapi_url', titel: 'OpenAPI', text: 'Jede API mit OpenAPI-Beschreibung' },
  { id: 'rest', titel: 'REST-Endpunkt', text: 'Einzelne HTTP-Aufrufe von Hand' },
];

export function McpBefehlFormular({ onAnlegen }: { onAnlegen: Anlegen }) {
  const [name, setName] = useState('');
  const [befehl, setBefehl] = useState('');
  const [umgebung, setUmgebung] = useState<Paar[]>([]);
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
      <Feld label="Umgebungsvariablen (optional)" gruppe>
        {() => <PaarEditor paare={umgebung} onChange={setUmgebung} schluesselLabel="Variable" wertLabel="Wert" geheim beispiel={['API_KEY', 'Wert']} />}
      </Feld>
      <Fehler text={fehler} />
      <Absenden laeuft={laeuft} />
    </form>
  );
}

export function McpUrlFormular({ onAnlegen }: { onAnlegen: Anlegen }) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [kopfzeilen, setKopfzeilen] = useState<Paar[]>([]);
  const { fehler, laeuft, absenden } = useAbsenden(onAnlegen);
  return (
    <form className="formular" onSubmit={(e) => absenden(e, () => mcpUrlBody(name, url, kopfzeilen))}>
      <Feld label="URL des MCP-Servers">
        {(id) => (
          <input id={id} className="mono" autoFocus inputMode="url" placeholder="http://homeassistant.local:8123/mcp" value={url} onChange={(e) => setUrl(e.target.value)} />
        )}
      </Feld>
      <Feld label="Name">{(id) => <input id={id} placeholder={nameAusUrl(url) || 'Home Assistant'} value={name} onChange={(e) => setName(e.target.value)} />}</Feld>
      <Feld label="Kopfzeilen (optional)" gruppe>
        {() => <PaarEditor paare={kopfzeilen} onChange={setKopfzeilen} schluesselLabel="Kopfzeile" wertLabel="Wert" geheim beispiel={['Authorization', 'Bearer …']} />}
      </Feld>
      <Fehler text={fehler} />
      <Absenden laeuft={laeuft} />
    </form>
  );
}

export function OpenApiFormular({ onAnlegen }: { onAnlegen: Anlegen }) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [art, setArt] = useState<AuthArt>('keine');
  const [wert, setWert] = useState('');
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
      <Absenden laeuft={laeuft} />
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
    case 'openapi_url':
      return <OpenApiFormular onAnlegen={onAnlegen} />;
    case 'rest':
      return <RestFormular onAnlegen={onAnlegen} />;
  }
}
