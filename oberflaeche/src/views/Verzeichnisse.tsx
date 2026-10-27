import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, BookOpen, ExternalLink, Globe, KeyRound, Search, ShieldAlert, ShieldCheck, Terminal, Users } from 'lucide-react';
import { api, ApiFehler } from '../api/rest';
import type { Integration, KatalogEintrag, VerzeichnisFeld, VerzeichnisQuelle, VerzeichnisTreffer } from '../api/types';
import { iconFuer } from '../lib/icons';
import { Feld } from './Formulare';
import { KatalogChips } from './Integrations';

export const QUELLEN_NAMEN: Record<string, string> = { 'mcp-registry': 'MCP-Registry', smithery: 'Smithery' };

export function quellenName(id: string, quellen: VerzeichnisQuelle[]): string {
  return quellen.find((q) => q.id === id)?.name ?? QUELLEN_NAMEN[id] ?? id;
}

/** Chips eines Treffers: Herkunft, Verifizierung, Art, Anmeldung. */
export function TrefferChips({ t, quellen }: { t: VerzeichnisTreffer; quellen: VerzeichnisQuelle[] }) {
  return (
    <>
      <span className="marke-chip quelle" title={`Gefunden in ${quellenName(t.quelle, quellen)}`}>
        <BookOpen size={11} aria-hidden="true" /> {quellenName(t.quelle, quellen)}
      </span>
      {t.verifiziert ? (
        <span className="marke-chip offiziell" title="Vom Verzeichnis als geprüft markiert">
          <ShieldCheck size={11} aria-hidden="true" /> Verifiziert
        </span>
      ) : (
        <span className="marke-chip community" title={t.herausgeber}>
          <Users size={11} aria-hidden="true" /> {t.herausgeber || 'Unbekannter Herausgeber'}
        </span>
      )}
      {t.laufzeit === 'fern' && (
        <span className="marke-chip cloud">
          <Globe size={11} aria-hidden="true" /> Fern
        </span>
      )}
      {(t.laufzeit === 'npx' || t.laufzeit === 'uvx') && (
        <span className="marke-chip lokal" title="Wird auf diesem Rechner ausgeführt">
          <Terminal size={11} aria-hidden="true" /> Lokal ({t.laufzeit})
        </span>
      )}
      {t.oauth && t.installierbar && (
        <span className="marke-chip cloud">
          <KeyRound size={11} aria-hidden="true" /> Anmeldung im Browser
        </span>
      )}
      {!t.installierbar && <span className="marke-chip aus">nicht installierbar</span>}
    </>
  );
}

function TrefferDetail({
  treffer,
  quellen,
  onZurueck,
  onInstalliert,
}: {
  treffer: VerzeichnisTreffer;
  quellen: VerzeichnisQuelle[];
  onZurueck: () => void;
  onInstalliert: (i: Integration) => void;
}) {
  const [t, setT] = useState<VerzeichnisTreffer>(treffer);
  const [laden, setLaden] = useState(!treffer.vollstaendig);
  const [werte, setWerte] = useState<Record<string, string>>({});
  const [name, setName] = useState('');
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  useEffect(() => {
    let aktiv = true;
    api
      .verzeichnisDetails(treffer.quelle, treffer.kennung)
      .then((d) => {
        if (aktiv) setT(d);
      })
      .catch((e: Error) => {
        if (aktiv) setFehler(e.message);
      })
      .finally(() => {
        if (aktiv) setLaden(false);
      });
    return () => {
      aktiv = false;
    };
  }, [treffer]);

  const installieren = async (e: FormEvent) => {
    e.preventDefault();
    const fehlend = t.felder.filter((f) => !f.optional && !f.standard && !werte[f.name]?.trim());
    if (fehlend.length) {
      setFehler(`Bitte ausfüllen: ${fehlend.map((f) => f.titel).join(', ')}`);
      return;
    }
    setFehler(null);
    setLaeuft(true);
    try {
      const neu = await api.verzeichnisInstallieren({ quelle: t.quelle, kennung: t.kennung, werte, name: name.trim() || undefined });
      onInstalliert(neu);
    } catch (err) {
      setFehler(err instanceof ApiFehler ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  };

  const Icon = iconFuer(t.laufzeit === 'fern' ? 'globe' : 'terminal');
  const lokal = t.laufzeit === 'npx' || t.laufzeit === 'uvx';
  return (
    <div className="katalog-detail">
      <button className="text-knopf" onClick={onZurueck}>
        <ArrowLeft size={14} aria-hidden="true" /> Zurück zur Suche
      </button>
      <div className="detail-kopf">
        <span className="kat-icon gross" aria-hidden="true">
          <Icon size={28} />
        </span>
        <div>
          <h3>{t.name}</h3>
          <p>{t.beschreibung}</p>
          <div className="inst-meta">
            <code>{t.kennung}</code>
            <TrefferChips t={t} quellen={quellen} />
            {t.nutzungen ? <span>{t.nutzungen.toLocaleString('de-DE')} Nutzungen</span> : null}
            {t.webseite && (
              <a href={t.webseite} target="_blank" rel="noreferrer" className="text-knopf">
                <ExternalLink size={12} aria-hidden="true" /> Webseite
              </a>
            )}
            {t.repository && t.repository !== t.webseite && (
              <a href={t.repository} target="_blank" rel="noreferrer" className="text-knopf">
                <ExternalLink size={12} aria-hidden="true" /> Quellcode
              </a>
            )}
          </div>
        </div>
      </div>
      {!t.verifiziert && (
        <div className="fehler-kasten warnung" role="note">
          <ShieldAlert size={16} aria-hidden="true" />
          <div>
            <strong>Von Dritten veröffentlicht.</strong> Javit hat diesen Server nicht geprüft – Herausgeber: {t.herausgeber || 'unbekannt'}.
            {lokal ? ' Lokale Server führen fremden Code auf diesem Rechner aus.' : ' Deine Daten laufen über den Server des Herausgebers.'} Nur installieren, wenn du der Quelle vertraust.
          </div>
        </div>
      )}
      {t.warnungen.map((w) => (
        <p key={w} className="formular-hinweis">
          {w}
        </p>
      ))}
      {laden ? (
        <p className="gedaempft">Lade Details …</p>
      ) : t.installierbar ? (
        <form className="formular" onSubmit={(e) => void installieren(e)} aria-label={`${t.name} installieren`}>
          {t.felder.length === 0 && <p className="gedaempft">{t.oauth ? 'Keine Angaben nötig – beim Verbinden öffnet sich die Anmeldung im Browser.' : 'Keine Angaben nötig.'}</p>}
          {t.felder.map((f: VerzeichnisFeld, i) => (
            <Feld
              key={f.name}
              label={f.titel + (f.optional ? ' (optional)' : '')}
              hilfe={
                <>
                  <code>{f.name}</code>
                  {f.beschreibung && f.beschreibung !== f.titel ? ` – ${f.beschreibung}` : ''}
                  {f.geheim ? ' – wird im Schlüsselbund gespeichert.' : ''}
                </>
              }
            >
              {(id) => (
                <input
                  id={id}
                  type={f.geheim ? 'password' : 'text'}
                  autoComplete={f.geheim ? 'new-password' : 'off'}
                  autoFocus={i === 0}
                  className={f.geheim ? '' : 'mono'}
                  placeholder={f.standard ?? ''}
                  value={werte[f.name] ?? ''}
                  onChange={(e) => setWerte({ ...werte, [f.name]: e.target.value })}
                />
              )}
            </Feld>
          ))}
          <Feld label="Name (optional)">{(id) => <input id={id} placeholder={t.name} value={name} onChange={(e) => setName(e.target.value)} />}</Feld>
          {fehler && <p className="formular-fehler">{fehler}</p>}
          <div className="feld-reihe">
            <button className="knopf primaer" type="submit" disabled={laeuft}>
              {laeuft ? 'Installiere …' : `${t.name} installieren`}
            </button>
          </div>
        </form>
      ) : (
        <>
          {fehler && <p className="formular-fehler">{fehler}</p>}
          <p className="gedaempft">Dieser Eintrag lässt sich mit Javit nicht direkt installieren. Die Webseite des Herausgebers beschreibt ggf. einen anderen Weg.</p>
        </>
      )}
    </div>
  );
}

/** Reiter „Suchen“: Katalogtreffer zuerst, dann Verzeichnisse (MCP-Registry, Smithery, eigene). */
export function VerzeichnisSuche({
  katalog,
  installiert,
  onKatalog,
  onInstalliert,
}: {
  katalog: KatalogEintrag[];
  installiert: Set<string>;
  onKatalog: (e: KatalogEintrag) => void;
  onInstalliert: (i: Integration) => void;
}) {
  const [quellen, setQuellen] = useState<VerzeichnisQuelle[]>([]);
  const [quelle, setQuelle] = useState<string | null>(null);
  const [eingabe, setEingabe] = useState('');
  const [begriff, setBegriff] = useState('');
  const [treffer, setTreffer] = useState<VerzeichnisTreffer[] | null>(null);
  const [fehler, setFehler] = useState<Record<string, string>>({});
  const [meldung, setMeldung] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const [gewaehlt, setGewaehlt] = useState<VerzeichnisTreffer | null>(null);
  const laufend = useRef(0);

  useEffect(() => {
    api
      .verzeichnisse()
      .then(setQuellen)
      .catch(() => setQuellen([]));
  }, []);

  useEffect(() => {
    if (begriff.trim().length < 2) {
      setTreffer(null);
      setFehler({});
      return;
    }
    const nr = ++laufend.current;
    setLaeuft(true);
    setMeldung(null);
    api
      .verzeichnisSuche(begriff.trim(), quelle ?? undefined)
      .then((r) => {
        if (nr !== laufend.current) return;
        setTreffer(r.treffer);
        setFehler(r.fehler);
      })
      .catch((e: Error) => {
        if (nr !== laufend.current) return;
        setTreffer([]);
        setMeldung(e.message);
      })
      .finally(() => {
        if (nr === laufend.current) setLaeuft(false);
      });
  }, [begriff, quelle]);

  if (gewaehlt) {
    return <TrefferDetail treffer={gewaehlt} quellen={quellen} onZurueck={() => setGewaehlt(null)} onInstalliert={onInstalliert} />;
  }

  const q = begriff.trim().toLowerCase();
  const imKatalog = q.length >= 2 ? katalog.filter((e) => `${e.name} ${e.beschreibung} ${e.id} ${e.kategorie}`.toLowerCase().includes(q)).slice(0, 6) : [];

  return (
    <div className="katalog verzeichnis-suche">
      <form
        className="katalog-werkzeuge"
        onSubmit={(e) => {
          e.preventDefault();
          setBegriff(eingabe);
        }}
      >
        <label className="suche">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            placeholder="Dienst oder Server suchen, z. B. Jira, Todoist, Wetter"
            value={eingabe}
            onChange={(e) => setEingabe(e.target.value)}
            aria-label="Verzeichnisse durchsuchen"
            autoFocus
          />
        </label>
        <button type="submit" className="knopf" disabled={eingabe.trim().length < 2 || laeuft}>
          Suchen
        </button>
        <div className="kategorien" role="group" aria-label="Verzeichnisse">
          <button type="button" className={`kat-chip ${quelle === null ? 'an' : ''}`} aria-pressed={quelle === null} onClick={() => setQuelle(null)}>
            Alle
          </button>
          {quellen.map((v) => (
            <button key={v.id} type="button" className={`kat-chip ${quelle === v.id ? 'an' : ''}`} aria-pressed={quelle === v.id} onClick={() => setQuelle(v.id)} title={v.url}>
              {v.name}
            </button>
          ))}
        </div>
      </form>
      <p className="gedaempft">
        Durchsucht das offizielle MCP-Registry und Smithery{quellen.some((v) => v.eigen) ? ' sowie eigene Registries' : ''}. Treffer stammen von Dritten – achte auf Herausgeber und Verifizierung. Eigene Registries lassen sich in den Einstellungen hinzufügen.
      </p>
      {meldung && <p className="formular-fehler">{meldung}</p>}
      {Object.entries(fehler).map(([id, text]) => (
        <p key={id} className="formular-hinweis">
          {quellenName(id, quellen)} nicht erreichbar: {text}
        </p>
      ))}
      {imKatalog.length > 0 && (
        <section aria-label="Im Katalog">
          <h4 className="gedaempft">Im Katalog</h4>
          <ul className="katalog-raster">
            {imKatalog.map((e) => {
              const Icon = iconFuer(e.icon);
              return (
                <li key={e.id}>
                  <button className={`kat-kachel ${installiert.has(e.id) ? 'ist-da' : ''}`} onClick={() => onKatalog(e)}>
                    <span className="kat-icon" aria-hidden="true">
                      <Icon size={20} />
                    </span>
                    <span className="kat-name">{e.name}</span>
                    <span className="kat-text">{e.beschreibung}</span>
                    <span className="kat-chips">
                      <KatalogChips e={e} />
                    </span>
                    <span className="kat-fuss">
                      <span>{e.kategorie}</span>
                      {installiert.has(e.id) && <span className="kat-ist">installiert</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {laeuft && <p className="gedaempft">Suche in den Verzeichnissen …</p>}
      {treffer && !laeuft && (
        <section aria-label="Treffer aus Verzeichnissen">
          <h4 className="gedaempft">Aus Verzeichnissen ({treffer.length})</h4>
          {treffer.length === 0 ? (
            <p className="gedaempft">Nichts gefunden. Über „MCP-Befehl“, „MCP-URL“ oder „JSON einfügen“ lässt sich jeder Server von Hand anbinden.</p>
          ) : (
            <ul className="installiert verzeichnis-treffer">
              {treffer.map((t) => (
                <li key={`${t.quelle}/${t.kennung}`} className={`inst ${t.installierbar ? '' : 'gedaempft'}`}>
                  <button type="button" className="inst-knopf" onClick={() => setGewaehlt(t)} aria-label={`${t.name} öffnen`}>
                    <div className="inst-text">
                      <div className="inst-name">
                        {t.name} <code className="gedaempft">{t.kennung}</code>
                      </div>
                      <div className="kat-text">{t.beschreibung}</div>
                      <div className="inst-meta">
                        <TrefferChips t={t} quellen={quellen} />
                        {t.nutzungen ? <span>{t.nutzungen.toLocaleString('de-DE')} Nutzungen</span> : null}
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
