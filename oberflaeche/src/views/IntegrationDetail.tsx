import { useEffect, useState, type ReactNode } from 'react';
import { ArrowLeft, ExternalLink, KeyRound, LogOut, MessageCircleQuestion, Pencil, RefreshCw, Trash2, X } from 'lucide-react';
import { api } from '../api/rest';
import type { IntegrationAnlegen, IntegrationDetails, Schritt } from '../api/types';
import { useJarvis, useName } from '../state/store';
import { iconFuer } from '../lib/icons';
import { EinrichtungListe } from './Einrichtung';
import { BearbeitenFormular } from './Formulare';

const STATUS_TEXT: Record<string, string> = { verbunden: 'verbunden', fehler: 'Fehler', aus: 'aus', verbindet: 'verbindet …' };
const ART_TEXT: Record<string, string> = { mcp_stdio: 'MCP lokal', mcp_http: 'MCP über HTTP', openapi: 'OpenAPI', rest: 'REST', eingebaut: 'eingebaut' };
const RISIKO_TEXT: Record<string, string> = { lesen: 'lesen', aendern: 'ändern', kritisch: 'kritisch' };
const VERZEICHNIS_NAMEN: Record<string, string> = { 'mcp-registry': 'MCP-Registry (offiziell)', smithery: 'Smithery' };

function Werte({ werte }: { werte: Record<string, string> }) {
  const eintraege = Object.entries(werte);
  if (eintraege.length === 0) return null;
  return (
    <dl className="werte">
      {eintraege.map(([k, v]) => (
        <div key={k}>
          <dt>
            <code>{k}</code>
          </dt>
          <dd>{v === 'gespeichert' ? <span className="marke-chip cloud">gespeichert</span> : <code>{v || '–'}</code>}</dd>
        </div>
      ))}
    </dl>
  );
}

export function IntegrationDetail({ id, onZurueck, onGeaendert }: { id: string; onZurueck: () => void; onGeaendert: () => void }) {
  const [d, setD] = useState<IntegrationDetails | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [bearbeiten, setBearbeiten] = useState(false);
  const [arbeitet, setArbeitet] = useState(false);
  const [bestaetigen, setBestaetigen] = useState(false);
  const [protokollOffen, setProtokollOffen] = useState(false);
  const stand = useJarvis((s) => s.integrationsStand);
  const name = useName();

  const laden = () =>
    api
      .integrationDetails(id)
      .then((x) => {
        setD(x);
        setFehler(null);
      })
      .catch((e: Error) => setFehler(e.message));
  useEffect(() => {
    void laden();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, stand]);

  const neuVerbinden = async () => {
    setArbeitet(true);
    try {
      await api.integrationNeuVerbinden(id);
      await laden();
      onGeaendert();
    } catch (e) {
      setFehler((e as Error).message);
    } finally {
      setArbeitet(false);
    }
  };
  const entfernen = async () => {
    setArbeitet(true);
    try {
      await api.integrationEntfernen(id);
      onGeaendert();
      onZurueck();
    } catch (e) {
      setFehler((e as Error).message);
      setArbeitet(false);
    }
  };
  const abmelden = async () => {
    setArbeitet(true);
    try {
      await api.integrationAbmelden(id);
      await laden();
      onGeaendert();
    } catch (e) {
      setFehler((e as Error).message);
    } finally {
      setArbeitet(false);
    }
  };
  const anmelden = async () => {
    setArbeitet(true);
    try {
      await api.integrationAnmelden(id);
      await laden();
      onGeaendert();
    } catch (e) {
      setFehler((e as Error).message);
    } finally {
      setArbeitet(false);
    }
  };
  const speichern = async (body: IntegrationAnlegen) => {
    const neu = await api.integrationAendern(id, body);
    setD(neu);
    setBearbeiten(false);
    onGeaendert();
  };
  const hilfe = () => {
    const st = useJarvis.getState();
    st.setAnsicht('konsole');
    st.nachrichtSenden(`Hilf mir, die Integration „${d?.name ?? id}“ einzurichten. Sie ist gerade nicht verbunden.`);
  };
  const schritteSetzen = (schritte: Schritt[]) => setD((alt) => (alt && alt.katalog ? { ...alt, katalog: { ...alt.katalog, einrichtung: schritte } } : alt));

  if (!d) {
    return (
      <div className="katalog-detail">
        <button className="text-knopf" onClick={onZurueck}>
          <ArrowLeft size={14} aria-hidden="true" /> Zurück
        </button>
        {fehler ? <p className="formular-fehler">{fehler}</p> : <p className="gedaempft">Lade …</p>}
      </div>
    );
  }
  const Icon = iconFuer(d.katalog?.id ?? d.id);
  const k = d.konfig;
  return (
    <div className="katalog-detail integration-detail">
      <button className="text-knopf" onClick={onZurueck}>
        <ArrowLeft size={14} aria-hidden="true" /> Zurück zu Installiert
      </button>
      <div className="detail-kopf">
        <span className="kat-icon gross" aria-hidden="true">
          <Icon size={28} />
        </span>
        <div>
          <h3>{d.name}</h3>
          <div className="inst-meta">
            <span>{ART_TEXT[d.art] ?? d.art}</span>
            <span>{d.werkzeuge} Werkzeuge</span>
            <span className={`status-chip s-${d.status}`}>
              <span className={`status-punkt s-${d.status}`} aria-hidden="true" />
              {STATUS_TEXT[d.status] ?? d.status}
            </span>
            {d.oauth && (
              <span className={`marke-chip ${d.oauth.angemeldet ? 'lokal' : 'aus'}`}>
                <KeyRound size={11} aria-hidden="true" /> {d.oauth.angemeldet ? 'angemeldet' : 'nicht angemeldet'}
              </span>
            )}
          </div>
        </div>
        <div className="inst-knoepfe">
          {d.oauth && (
            d.oauth.angemeldet ? (
              <button className="knopf klein leise" onClick={() => void abmelden()} disabled={arbeitet}>
                <LogOut size={14} aria-hidden="true" /> Abmelden
              </button>
            ) : (
              <button className="knopf klein" onClick={() => void anmelden()} disabled={arbeitet}>
                <KeyRound size={14} aria-hidden="true" /> Anmelden
              </button>
            )
          )}
          <button className="knopf klein" onClick={() => void neuVerbinden()} disabled={arbeitet}>
            <RefreshCw size={14} aria-hidden="true" className={arbeitet ? 'dreht' : ''} /> Neu verbinden
          </button>
          {bestaetigen ? (
            <>
              <button className="knopf klein gefahr" onClick={() => void entfernen()} disabled={arbeitet}>
                Wirklich entfernen
              </button>
              <button className="icon-knopf" aria-label="Abbrechen" onClick={() => setBestaetigen(false)}>
                <X size={14} />
              </button>
            </>
          ) : (
            <button className="knopf klein leise" onClick={() => setBestaetigen(true)}>
              <Trash2 size={14} aria-hidden="true" /> Entfernen
            </button>
          )}
        </div>
      </div>

      {fehler && <p className="formular-fehler">{fehler}</p>}
      {d.status === 'fehler' && (
        <div className="fehler-kasten" role="alert">
          <strong>Nicht verbunden.</strong> {d.fehler}
          <div className="fehler-aktionen">
            <button type="button" className="knopf klein" onClick={hilfe}>
              <MessageCircleQuestion size={14} aria-hidden="true" /> {name} um Hilfe bitten
            </button>
            {d.katalog?.webseite && (
              <a className="knopf klein leise" href={d.katalog.webseite} target="_blank" rel="noreferrer">
                <ExternalLink size={14} aria-hidden="true" /> Anleitung des Servers
              </a>
            )}
          </div>
        </div>
      )}

      {d.katalog && d.katalog.einrichtung.length > 0 && (
        <EinrichtungListe katalogId={d.katalog.id} schritte={d.katalog.einrichtung} onAktualisiert={schritteSetzen} />
      )}
      {d.katalog?.hinweis && !d.katalog.einrichtung.length && <p className="formular-hinweis">{d.katalog.hinweis}</p>}

      <section className="detail-abschnitt" aria-label="Konfiguration">
        <div className="einrichtung-kopf">
          <h4>Konfiguration</h4>
          {!bearbeiten && d.art !== 'eingebaut' && (
            <button type="button" className="knopf klein" onClick={() => setBearbeiten(true)}>
              <Pencil size={14} aria-hidden="true" /> Bearbeiten
            </button>
          )}
        </div>
        {bearbeiten ? (
          <BearbeitenFormular details={d} onSpeichern={speichern} onAbbrechen={() => setBearbeiten(false)} />
        ) : (
          <>
            {k.befehl && (
              <p>
                Befehl: <code>{k.befehl.join(' ')}</code>
              </p>
            )}
            {k.url && (
              <p>
                URL: <code>{k.url}</code>
              </p>
            )}
            {d.verzeichnis && (
              <p className="gedaempft">
                Aus Verzeichnis: {VERZEICHNIS_NAMEN[d.verzeichnis.quelle] ?? d.verzeichnis.quelle} · <code>{d.verzeichnis.kennung}</code>
              </p>
            )}
            {d.werte && <Werte werte={d.werte} />}
            {!d.werte && Object.keys(k.umgebung).length > 0 && (
              <>
                <p className="gedaempft">Umgebungsvariablen</p>
                <Werte werte={k.umgebung} />
              </>
            )}
            {Object.keys(k.kopfzeilen).length > 0 && (
              <>
                <p className="gedaempft">Kopfzeilen</p>
                <Werte werte={k.kopfzeilen} />
              </>
            )}
            {k.geheimnisse.length > 0 && (
              <p className="gedaempft">
                Geheimnisse im Schlüsselbund: {k.geheimnisse.map((g) => <code key={g}>{g}</code>).reduce<ReactNode[]>((a, c, i) => (i ? [...a, ', ', c] : [c]), [])}
              </p>
            )}
            {!k.befehl && !k.url && !d.werte && Object.keys(k.umgebung).length === 0 && Object.keys(k.kopfzeilen).length === 0 && (
              <p className="gedaempft">Keine Einstellungen – diese Integration braucht nichts weiter.</p>
            )}
          </>
        )}
      </section>

      <section className="detail-abschnitt" aria-label="Werkzeuge">
        <h4>Werkzeuge ({d.werkzeug_liste.length})</h4>
        {d.werkzeug_liste.length === 0 ? (
          <p className="gedaempft">Noch keine Werkzeuge – erst nach erfolgreicher Verbindung.</p>
        ) : (
          <ul className="werkzeug-liste">
            {d.werkzeug_liste.map((w) => (
              <li key={w.name}>
                <code>{w.name}</code>
                <span className={`marke-chip risiko-${w.risiko}`}>{RISIKO_TEXT[w.risiko] ?? w.risiko}</span>
                <span className="gedaempft">{w.beschreibung}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {d.protokoll.length > 0 && (
        <section className="detail-abschnitt" aria-label="Protokoll">
          <button type="button" className="text-knopf" onClick={() => setProtokollOffen(!protokollOffen)}>
            Protokoll des Servers {protokollOffen ? 'verbergen' : 'zeigen'} ({d.protokoll.length} Zeilen)
          </button>
          {protokollOffen && <pre className="protokoll">{d.protokoll.join('\n')}</pre>}
        </section>
      )}
    </div>
  );
}
