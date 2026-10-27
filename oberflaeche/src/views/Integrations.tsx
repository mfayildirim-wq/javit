import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, RefreshCw, Search, Trash2, X } from 'lucide-react';
import { api } from '../api/rest';
import type { Integration, IntegrationAnlegen, KatalogEintrag } from '../api/types';
import { useJarvis, useName } from '../state/store';
import { iconFuer } from '../lib/icons';
import { EIGENE_ARTEN, EigeneFormular, KatalogFormular, type EigeneArt } from './Formulare';

type Reiter = 'installiert' | 'katalog' | 'eigene';

const STATUS_TEXT: Record<string, string> = { verbunden: 'verbunden', fehler: 'Fehler', aus: 'aus' };
const ART_TEXT: Record<string, string> = {
  mcp_stdio: 'MCP lokal',
  mcp_http: 'MCP über HTTP',
  mcp_befehl: 'MCP lokal',
  mcp_url: 'MCP über HTTP',
  openapi: 'OpenAPI',
  openapi_url: 'OpenAPI',
  rest: 'REST',
  eingebaut: 'eingebaut',
  katalog: 'Katalog',
};

function Installierte({
  liste,
  katalog,
  laden,
  neuLaden,
}: {
  liste: Integration[];
  katalog: KatalogEintrag[];
  laden: boolean;
  neuLaden: () => void;
}) {
  const [arbeitet, setArbeitet] = useState<string | null>(null);
  const [bestaetigen, setBestaetigen] = useState<string | null>(null);
  const hinweis = (text: string) => useJarvis.getState().verarbeiten({ typ: 'lokal_hinweis', text });

  const neuVerbinden = async (i: Integration) => {
    setArbeitet(i.id);
    try {
      await api.integrationNeuVerbinden(i.id);
    } catch (e) {
      hinweis(`${i.name}: Neu verbinden fehlgeschlagen – ${(e as Error).message}`);
    } finally {
      setArbeitet(null);
      neuLaden();
    }
  };
  const entfernen = async (i: Integration) => {
    setArbeitet(i.id);
    try {
      await api.integrationEntfernen(i.id);
    } catch (e) {
      hinweis(`${i.name}: Entfernen fehlgeschlagen – ${(e as Error).message}`);
    } finally {
      setArbeitet(null);
      setBestaetigen(null);
      neuLaden();
    }
  };

  if (laden && liste.length === 0) return <p className="gedaempft">Lade Integrationen …</p>;
  if (liste.length === 0)
    return (
      <div className="leer gross">
        <p>Noch keine Integration verbunden.</p>
        <p className="gedaempft">Wählen Sie eine App aus dem Katalog oder binden Sie einen eigenen MCP-Server an.</p>
      </div>
    );

  return (
    <ul className="installiert">
      {liste.map((i) => {
        const Icon = iconFuer(katalog.find((k) => k.id === i.id)?.icon ?? i.id);
        return (
          <li key={i.id} className={`inst s-${i.status}`}>
            <span className="inst-icon" aria-hidden="true">
              <Icon size={20} />
            </span>
            <div className="inst-text">
              <div className="inst-name">{i.name}</div>
              <div className="inst-meta">
                <span>{ART_TEXT[i.art] ?? i.art}</span>
                <span>{i.werkzeuge} Werkzeuge</span>
              </div>
              {i.fehler && <div className="inst-fehler">{i.fehler}</div>}
            </div>
            <span className={`status-chip s-${i.status}`}>
              <span className={`status-punkt s-${i.status}`} aria-hidden="true" />
              {STATUS_TEXT[i.status] ?? i.status}
            </span>
            <div className="inst-knoepfe">
              <button className="knopf klein" onClick={() => neuVerbinden(i)} disabled={arbeitet === i.id}>
                <RefreshCw size={14} aria-hidden="true" className={arbeitet === i.id ? 'dreht' : ''} />
                Neu verbinden
              </button>
              {bestaetigen === i.id ? (
                <>
                  <button className="knopf klein gefahr" onClick={() => entfernen(i)} disabled={arbeitet === i.id}>
                    Wirklich entfernen
                  </button>
                  <button className="icon-knopf" aria-label="Abbrechen" onClick={() => setBestaetigen(null)}>
                    <X size={14} />
                  </button>
                </>
              ) : (
                <button className="knopf klein leise" onClick={() => setBestaetigen(i.id)} aria-label={`${i.name} entfernen`}>
                  <Trash2 size={14} aria-hidden="true" />
                  Entfernen
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Katalog({
  eintraege,
  installiert,
  onAnlegen,
}: {
  eintraege: KatalogEintrag[];
  installiert: Set<string>;
  onAnlegen: (b: IntegrationAnlegen) => Promise<void>;
}) {
  const [suche, setSuche] = useState('');
  const [kategorie, setKategorie] = useState<string | null>(null);
  const [gewaehlt, setGewaehlt] = useState<KatalogEintrag | null>(null);
  const kategorien = useMemo(() => [...new Set(eintraege.map((e) => e.kategorie))].sort((a, b) => a.localeCompare(b, 'de')), [eintraege]);
  const q = suche.trim().toLowerCase();
  const gefiltert = eintraege.filter(
    (e) =>
      (!kategorie || e.kategorie === kategorie) &&
      (!q || `${e.name} ${e.beschreibung} ${e.kategorie} ${e.id}`.toLowerCase().includes(q)),
  );

  if (gewaehlt) {
    const Icon = iconFuer(gewaehlt.icon);
    return (
      <div className="katalog-detail">
        <button className="text-knopf" onClick={() => setGewaehlt(null)}>
          <ArrowLeft size={14} aria-hidden="true" /> Zurück zum Katalog
        </button>
        <div className="detail-kopf">
          <span className="kat-icon gross" aria-hidden="true">
            <Icon size={28} />
          </span>
          <div>
            <h3>{gewaehlt.name}</h3>
            <p>{gewaehlt.beschreibung}</p>
            <div className="inst-meta">
              <span>{gewaehlt.kategorie}</span>
              <span>{ART_TEXT[gewaehlt.art] ?? gewaehlt.art}</span>
            </div>
          </div>
        </div>
        <KatalogFormular
          eintrag={gewaehlt}
          onAnlegen={async (b) => {
            await onAnlegen(b);
            setGewaehlt(null);
          }}
        />
      </div>
    );
  }

  return (
    <div className="katalog">
      <div className="katalog-werkzeuge">
        <label className="suche">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            placeholder="Katalog durchsuchen, z. B. Spotify, Kalender, GitHub"
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            aria-label="Katalog durchsuchen"
            autoFocus
          />
        </label>
        <div className="kategorien" role="group" aria-label="Kategorien">
          <button className={`kat-chip ${kategorie === null ? 'an' : ''}`} aria-pressed={kategorie === null} onClick={() => setKategorie(null)}>
            Alle <span>{eintraege.length}</span>
          </button>
          {kategorien.map((k) => (
            <button key={k} className={`kat-chip ${kategorie === k ? 'an' : ''}`} aria-pressed={kategorie === k} onClick={() => setKategorie(k)}>
              {k} <span>{eintraege.filter((e) => e.kategorie === k).length}</span>
            </button>
          ))}
        </div>
      </div>
      {gefiltert.length === 0 ? (
        <p className="gedaempft">Nichts gefunden. Unter „Eigene“ lässt sich jede App per MCP, OpenAPI oder REST anbinden.</p>
      ) : (
        <ul className="katalog-raster">
          {gefiltert.map((e) => {
            const Icon = iconFuer(e.icon);
            const ist = installiert.has(e.id);
            return (
              <li key={e.id}>
                <button className={`kat-kachel ${ist ? 'ist-da' : ''}`} onClick={() => setGewaehlt(e)}>
                  <span className="kat-icon" aria-hidden="true">
                    <Icon size={20} />
                  </span>
                  <span className="kat-name">{e.name}</span>
                  <span className="kat-text">{e.beschreibung}</span>
                  <span className="kat-fuss">
                    <span>{e.kategorie}</span>
                    {ist ? <span className="kat-ist">installiert</span> : <span>{e.benoetigt.length === 0 ? 'ohne Schlüssel' : e.benoetigt.length === 1 ? '1 Angabe' : `${e.benoetigt.length} Angaben`}</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function Eigene({ onAnlegen }: { onAnlegen: (b: IntegrationAnlegen) => Promise<void> }) {
  const [art, setArt] = useState<EigeneArt>('mcp_befehl');
  return (
    <div className="eigene">
      <div className="segmente" role="tablist" aria-label="Art der Integration">
        {EIGENE_ARTEN.map((a) => (
          <button key={a.id} role="tab" aria-selected={art === a.id} className={`segment ${art === a.id ? 'an' : ''}`} onClick={() => setArt(a.id)}>
            <span className="segment-titel">{a.titel}</span>
            <span className="segment-text">{a.text}</span>
          </button>
        ))}
      </div>
      <EigeneFormular key={art} art={art} onAnlegen={onAnlegen} />
    </div>
  );
}

export function IntegrationsAnsicht() {
  const [reiter, setReiter] = useState<Reiter>('katalog');
  const reiterGewaehlt = useRef(false);
  const [liste, setListe] = useState<Integration[]>([]);
  const [katalog, setKatalog] = useState<KatalogEintrag[]>([]);
  const [laden, setLaden] = useState(true);
  const [erfolg, setErfolg] = useState<string | null>(null);
  const stand = useJarvis((s) => s.integrationsStand);
  const verbindung = useJarvis((s) => s.verbindung);
  const name = useName();

  const neuLaden = useCallback(() => {
    setLaden(true);
    void Promise.allSettled([api.integrationen(), api.katalog()]).then(([i, k]) => {
      if (i.status === 'fulfilled') {
        setListe(i.value);
        // Sind schon Integrationen installiert, zuerst diese zeigen (sonst den Katalog)
        if (i.value.length > 0 && !reiterGewaehlt.current) {
          reiterGewaehlt.current = true;
          setReiter('installiert');
        }
      }
      if (k.status === 'fulfilled') setKatalog(k.value);
      setLaden(false);
    });
  }, []);

  useEffect(() => {
    neuLaden();
  }, [neuLaden, stand, verbindung]);

  const anlegen = async (body: IntegrationAnlegen) => {
    const neu = await api.integrationAnlegen(body);
    setErfolg(`${neu?.name ?? 'Integration'} hinzugefügt${neu?.werkzeuge ? ` – ${neu.werkzeuge} Werkzeuge bereit` : ''}.`);
    setReiter('installiert');
    neuLaden();
  };

  const installiert = new Set(liste.map((i) => i.id));

  return (
    <section className="ansicht" aria-labelledby="int-titel">
      <header className="ansicht-kopf">
        <div>
          <h1 id="int-titel">Integrationen</h1>
          <p>Apps verbinden, damit {name} sie bedienen kann. Katalogeinträge brauchen meist nur einen Schlüssel.</p>
        </div>
        <div className="unter-reiter" role="tablist" aria-label="Integrationen">
          {(
            [
              ['installiert', `Installiert (${liste.length})`],
              ['katalog', 'Katalog'],
              ['eigene', 'Eigene'],
            ] as const
          ).map(([id, titel]) => (
            <button key={id} role="tab" aria-selected={reiter === id} className={`unter-reiter-knopf ${reiter === id ? 'an' : ''}`} onClick={() => {
                reiterGewaehlt.current = true;
                setReiter(id);
              }}>
              {titel}
            </button>
          ))}
        </div>
      </header>
      {erfolg && (
        <div className="erfolg" role="status">
          {erfolg}
          <button className="icon-knopf" aria-label="Meldung schließen" onClick={() => setErfolg(null)}>
            <X size={14} />
          </button>
        </div>
      )}
      <div className="ansicht-inhalt">
        {reiter === 'installiert' && <Installierte liste={liste} katalog={katalog} laden={laden} neuLaden={neuLaden} />}
        {reiter === 'katalog' && <Katalog eintraege={katalog} installiert={installiert} onAnlegen={anlegen} />}
        {reiter === 'eigene' && <Eigene onAnlegen={anlegen} />}
      </div>
    </section>
  );
}
