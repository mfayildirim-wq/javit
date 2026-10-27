import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ChevronRight, ExternalLink, KeyRound, Plus, Search, ShieldCheck, Users, X } from 'lucide-react';
import { api } from '../api/rest';
import type { Integration, IntegrationAnlegen, KatalogEintrag, Schritt } from '../api/types';
import { useJarvis, useName } from '../state/store';
import { iconFuer } from '../lib/icons';
import { EIGENE_ARTEN, EigeneFormular, GruppenFormular, KatalogFormular, type EigeneArt } from './Formulare';
import { EinrichtungListe } from './Einrichtung';
import { IntegrationDetail } from './IntegrationDetail';
import { VerzeichnisSuche } from './Verzeichnisse';

type Reiter = 'installiert' | 'hinzufuegen';
type Quelle = 'katalog' | 'verzeichnis' | EigeneArt;

const STATUS_TEXT: Record<string, string> = { verbunden: 'verbunden', fehler: 'Fehler', aus: 'aus', verbindet: 'verbindet …' };
export const ART_TEXT: Record<string, string> = {
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

/** Chips für Katalogeinträge: Herkunft und Anmeldeart. */
export function KatalogChips({ e }: { e: KatalogEintrag }) {
  return (
    <>
      {e.vertrauen === 'offiziell' ? (
        <span className="marke-chip offiziell" title="Vom Anbieter selbst betrieben oder veröffentlicht">
          <ShieldCheck size={11} aria-hidden="true" /> Offiziell
        </span>
      ) : (
        <span className="marke-chip community" title="Von Dritten entwickelt">
          <Users size={11} aria-hidden="true" /> Community
        </span>
      )}
      {e.oauth && (
        <span className="marke-chip cloud" title="Anmeldung im Browser beim Anbieter, Zugangsdaten im Schlüsselbund">
          <KeyRound size={11} aria-hidden="true" /> Anmeldung im Browser
        </span>
      )}
    </>
  );
}

const GRUPPEN_NAMEN: Record<string, { name: string; beschreibung: string; icon: string }> = {
  'google-workspace': {
    name: 'Google Workspace',
    beschreibung: 'Gmail, Kalender, Drive, Docs, Sheets, Slides, Chat, Kontakte und Classroom – offizielle Google-Server mit einem OAuth-Client',
    icon: 'mail',
  },
};

function Installierte({
  liste,
  katalog,
  laden,
  onOeffnen,
  onHinzufuegen,
}: {
  liste: Integration[];
  katalog: KatalogEintrag[];
  laden: boolean;
  onOeffnen: (id: string) => void;
  onHinzufuegen: () => void;
}) {
  if (laden && liste.length === 0) return <p className="gedaempft">Lade Integrationen …</p>;
  if (liste.length === 0)
    return (
      <div className="leer gross">
        <p>Noch keine Integration verbunden.</p>
        <p className="gedaempft">Mit „Hinzufügen“ eine App aus dem Katalog wählen oder einen eigenen MCP-Server anbinden.</p>
        <button className="knopf primaer" onClick={onHinzufuegen}>
          <Plus size={14} aria-hidden="true" /> Hinzufügen
        </button>
      </div>
    );

  return (
    <ul className="installiert">
      {liste.map((i) => {
        const Icon = iconFuer(katalog.find((k) => k.id === i.id)?.icon ?? i.id);
        return (
          <li key={i.id} className={`inst s-${i.status}`}>
            <button type="button" className="inst-knopf" onClick={() => onOeffnen(i.id)} aria-label={`${i.name} öffnen`}>
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
                {i.status === 'fehler' && <div className="inst-hinweis">Öffnen für Details, Einrichtung und Hilfe</div>}
              </div>
              <span className={`status-chip s-${i.status}`}>
                <span className={`status-punkt s-${i.status}`} aria-hidden="true" />
                {STATUS_TEXT[i.status] ?? i.status}
              </span>
              <ChevronRight size={16} aria-hidden="true" className="inst-pfeil" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function KatalogDetail({ eintrag, installiert, onAnlegen, onZurueck }: { eintrag: KatalogEintrag; installiert: boolean; onAnlegen: (b: IntegrationAnlegen) => Promise<void>; onZurueck: () => void }) {
  const [schritte, setSchritte] = useState<Schritt[]>(eintrag.einrichtung ?? []);
  useEffect(() => {
    if (!eintrag.einrichtung?.length) return;
    api
      .katalogDetail(eintrag.id)
      .then((k) => setSchritte(k.einrichtung ?? []))
      .catch(() => undefined);
  }, [eintrag]);
  const Icon = iconFuer(eintrag.icon);
  return (
    <div className="katalog-detail">
      <button className="text-knopf" onClick={onZurueck}>
        <ArrowLeft size={14} aria-hidden="true" /> Zurück zum Katalog
      </button>
      <div className="detail-kopf">
        <span className="kat-icon gross" aria-hidden="true">
          <Icon size={28} />
        </span>
        <div>
          <h3>{eintrag.name}</h3>
          <p>{eintrag.beschreibung}</p>
          <div className="inst-meta">
            <span>{eintrag.kategorie}</span>
            <span>{ART_TEXT[eintrag.art] ?? eintrag.art}</span>
            <KatalogChips e={eintrag} />
            {installiert && <span className="kat-ist">bereits installiert – Hinzufügen ersetzt die Einstellungen</span>}
            {(eintrag.quelle ?? eintrag.webseite) && (
              <a href={eintrag.quelle ?? eintrag.webseite ?? ''} target="_blank" rel="noreferrer" className="text-knopf">
                <ExternalLink size={12} aria-hidden="true" /> {eintrag.quelle ? 'Quelle (Anbieter-Doku)' : 'Anleitung'}
              </a>
            )}
          </div>
        </div>
      </div>
      {eintrag.oauth && (
        <p className="formular-hinweis">
          Beim Hinzufügen öffnet sich der Browser zur Anmeldung bei {eintrag.name}. Javit speichert die Zugangsdaten im Schlüsselbund; abmelden geht jederzeit auf der Detailseite.
        </p>
      )}
      {schritte.length > 0 && (
        <>
          <p className="formular-hinweis">Dieser Dienst braucht eine einmalige Vorbereitung. Die Schritte lassen sich jetzt oder später unter „Installiert“ erledigen.</p>
          <EinrichtungListe katalogId={eintrag.id} schritte={schritte} onAktualisiert={setSchritte} />
        </>
      )}
      <KatalogFormular eintrag={eintrag} onAnlegen={onAnlegen} />
    </div>
  );
}

function Hinzufuegen({
  eintraege,
  installiert,
  onAnlegen,
  onInstalliert,
}: {
  eintraege: KatalogEintrag[];
  installiert: Set<string>;
  onAnlegen: (b: IntegrationAnlegen) => Promise<void>;
  onInstalliert: (i: Integration) => void;
}) {
  const [quelle, setQuelle] = useState<Quelle>('katalog');
  const [suche, setSuche] = useState('');
  const [kategorie, setKategorie] = useState<string | null>(null);
  const [gewaehlt, setGewaehlt] = useState<KatalogEintrag | null>(null);
  const [gruppe, setGruppe] = useState<string | null>(null);
  const kategorien = useMemo(() => [...new Set(eintraege.map((e) => e.kategorie))].sort((a, b) => a.localeCompare(b, 'de')), [eintraege]);
  const q = suche.trim().toLowerCase();
  const gefiltert = eintraege.filter(
    (e) =>
      (!kategorie || e.kategorie === kategorie) &&
      (!q || `${e.name} ${e.beschreibung} ${e.kategorie} ${e.id}`.toLowerCase().includes(q)),
  );
  // Gruppen (z. B. Google Workspace) erscheinen als eine Kachel; die Mitglieder bleiben in der Suche einzeln erreichbar
  const gruppen = useMemo(() => {
    const m = new Map<string, KatalogEintrag[]>();
    for (const e of eintraege) if (e.gruppe) m.set(e.gruppe, [...(m.get(e.gruppe) ?? []), e]);
    return m;
  }, [eintraege]);
  const sichtbar: (KatalogEintrag | { gruppe: string; mitglieder: KatalogEintrag[] })[] = [];
  const gesehen = new Set<string>();
  for (const e of gefiltert) {
    if (e.gruppe && gruppen.get(e.gruppe)?.length && !q) {
      if (!gesehen.has(e.gruppe)) {
        gesehen.add(e.gruppe);
        sichtbar.push({ gruppe: e.gruppe, mitglieder: gruppen.get(e.gruppe) ?? [] });
      }
    } else sichtbar.push(e);
  }

  if (gruppe) {
    const mitglieder = gruppen.get(gruppe) ?? [];
    const info = GRUPPEN_NAMEN[gruppe] ?? { name: gruppe, beschreibung: '', icon: 'puzzle' };
    const Icon = iconFuer(info.icon);
    return (
      <div className="katalog-detail">
        <button className="text-knopf" onClick={() => setGruppe(null)}>
          <ArrowLeft size={14} aria-hidden="true" /> Zurück zum Katalog
        </button>
        <div className="detail-kopf">
          <span className="kat-icon gross" aria-hidden="true">
            <Icon size={28} />
          </span>
          <div>
            <h3>{info.name}</h3>
            <p>{info.beschreibung}</p>
            <div className="inst-meta">
              {mitglieder[0] && <KatalogChips e={mitglieder[0]} />}
              {mitglieder[0]?.quelle && (
                <a href={mitglieder[0].quelle} target="_blank" rel="noreferrer" className="text-knopf">
                  <ExternalLink size={12} aria-hidden="true" /> Quelle (Anbieter-Doku)
                </a>
              )}
            </div>
          </div>
        </div>
        <GruppenFormular
          mitglieder={mitglieder}
          installiert={installiert}
          onAnlegen={onAnlegen}
          onFertig={() => setGruppe(null)}
        />
      </div>
    );
  }

  if (gewaehlt) {
    return (
      <KatalogDetail
        eintrag={gewaehlt}
        installiert={installiert.has(gewaehlt.id)}
        onZurueck={() => setGewaehlt(null)}
        onAnlegen={async (b) => {
          await onAnlegen(b);
          setGewaehlt(null);
        }}
      />
    );
  }

  const quellen: { id: Quelle; titel: string; text: string }[] = [
    { id: 'katalog', titel: 'Katalog', text: `${eintraege.length} Apps und Dienste, meist nur ein Schlüssel` },
    { id: 'verzeichnis', titel: 'Suchen', text: 'MCP-Registry, Smithery und eigene Registries durchsuchen' },
    ...EIGENE_ARTEN,
  ];

  return (
    <div className="hinzufuegen">
      <div className="segmente" role="tablist" aria-label="Quelle der Integration">
        {quellen.map((a) => (
          <button key={a.id} role="tab" aria-selected={quelle === a.id} className={`segment ${quelle === a.id ? 'an' : ''}`} onClick={() => setQuelle(a.id)}>
            <span className="segment-titel">{a.titel}</span>
            <span className="segment-text">{a.text}</span>
          </button>
        ))}
      </div>
      {quelle === 'katalog' ? (
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
            <p className="gedaempft">Nichts gefunden. Über „MCP-Befehl“, „MCP-URL“ oder „JSON einfügen“ lässt sich jeder Server anbinden.</p>
          ) : (
            <ul className="katalog-raster">
              {sichtbar.map((e) => {
                if ('mitglieder' in e) {
                  const info = GRUPPEN_NAMEN[e.gruppe] ?? { name: e.gruppe, beschreibung: '', icon: 'puzzle' };
                  const Icon = iconFuer(info.icon);
                  const anzahl = e.mitglieder.filter((m) => installiert.has(m.id)).length;
                  return (
                    <li key={`gruppe-${e.gruppe}`}>
                      <button className={`kat-kachel gruppe ${anzahl ? 'ist-da' : ''}`} onClick={() => setGruppe(e.gruppe)} aria-label={`${info.name} öffnen`}>
                        <span className="kat-icon" aria-hidden="true">
                          <Icon size={20} />
                        </span>
                        <span className="kat-name">{info.name}</span>
                        <span className="kat-text">{info.beschreibung}</span>
                        <span className="kat-chips">{e.mitglieder[0] && <KatalogChips e={e.mitglieder[0]} />}</span>
                        <span className="kat-fuss">
                          <span>{e.mitglieder.length} Dienste</span>
                          {anzahl ? <span className="kat-ist">{anzahl} installiert</span> : <span>ein OAuth-Client für alle</span>}
                        </span>
                      </button>
                    </li>
                  );
                }
                const Icon = iconFuer(e.icon);
                const ist = installiert.has(e.id);
                const schritte = e.einrichtung?.length ?? 0;
                return (
                  <li key={e.id}>
                    <button className={`kat-kachel ${ist ? 'ist-da' : ''}`} onClick={() => setGewaehlt(e)}>
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
                        {ist ? (
                          <span className="kat-ist">installiert</span>
                        ) : e.oauth && e.benoetigt.length === 0 ? (
                          <span>Anmeldung im Browser</span>
                        ) : schritte ? (
                          <span>{schritte} Einrichtungsschritte</span>
                        ) : (
                          <span>{e.benoetigt.length === 0 ? 'ohne Schlüssel' : e.benoetigt.length === 1 ? '1 Angabe' : `${e.benoetigt.length} Angaben`}</span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : quelle === 'verzeichnis' ? (
        <VerzeichnisSuche katalog={eintraege} installiert={installiert} onKatalog={setGewaehlt} onInstalliert={onInstalliert} />
      ) : (
        <EigeneFormular key={quelle} art={quelle} onAnlegen={onAnlegen} />
      )}
    </div>
  );
}

export function IntegrationsAnsicht() {
  const [reiter, setReiter] = useState<Reiter>('hinzufuegen');
  const reiterGewaehlt = useRef(false);
  const [liste, setListe] = useState<Integration[]>([]);
  const [katalog, setKatalog] = useState<KatalogEintrag[]>([]);
  const [laden, setLaden] = useState(true);
  const [erfolg, setErfolg] = useState<string | null>(null);
  const [offen, setOffen] = useState<string | null>(null);
  const stand = useJarvis((s) => s.integrationsStand);
  const verbindung = useJarvis((s) => s.verbindung);
  const oauth = useJarvis((s) => s.oauthAnmeldung);
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

  const angelegt = (neu: Integration) => {
    const verbunden = neu?.status === 'verbunden';
    setErfolg(
      verbunden
        ? `${neu?.name ?? 'Integration'} hinzugefügt${neu?.werkzeuge ? ` – ${neu.werkzeuge} Werkzeuge bereit` : ''}.`
        : `${neu?.name ?? 'Integration'} gespeichert, aber noch nicht verbunden – Details öffnen für Einrichtung und Hilfe.`,
    );
    reiterGewaehlt.current = true;
    setReiter('installiert');
    if (neu?.id && !verbunden) setOffen(neu.id);
    neuLaden();
  };
  const anlegen = async (body: IntegrationAnlegen) => angelegt(await api.integrationAnlegen(body));

  const installiert = new Set(liste.map((i) => i.id));
  const zumHinzufuegen = () => {
    reiterGewaehlt.current = true;
    setOffen(null);
    setReiter('hinzufuegen');
  };

  return (
    <section className="ansicht" aria-labelledby="int-titel">
      <header className="ansicht-kopf">
        <div>
          <h1 id="int-titel">Integrationen</h1>
          <p>Apps verbinden, damit {name} sie bedienen kann. Katalogeinträge brauchen meist nur einen Schlüssel.</p>
        </div>
        <div className="kopf-aktionen">
          <div className="unter-reiter" role="tablist" aria-label="Integrationen">
            {(
              [
                ['installiert', `Installiert (${liste.length})`],
                ['hinzufuegen', 'Hinzufügen'],
              ] as const
            ).map(([id, titel]) => (
              <button
                key={id}
                role="tab"
                aria-selected={reiter === id}
                className={`unter-reiter-knopf ${reiter === id ? 'an' : ''}`}
                onClick={() => {
                  reiterGewaehlt.current = true;
                  setOffen(null);
                  setReiter(id);
                }}
              >
                {titel}
              </button>
            ))}
          </div>
          <button className="knopf primaer" onClick={zumHinzufuegen} aria-label="Integration hinzufügen">
            <Plus size={14} aria-hidden="true" /> Hinzufügen
          </button>
        </div>
      </header>
      {oauth && (
        <div className="erfolg oauth-hinweis" role="status">
          <KeyRound size={14} aria-hidden="true" />
          <span>
            Anmeldung für <strong>{liste.find((i) => i.id === oauth.integration)?.name ?? oauth.integration}</strong> läuft im Browser. Falls sich kein Fenster geöffnet hat:
          </span>
          <a className="knopf klein" href={oauth.url} target="_blank" rel="noreferrer">
            Anmeldeseite öffnen
          </a>
          <button className="icon-knopf" aria-label="Hinweis schließen" onClick={() => useJarvis.getState().verarbeiten({ typ: 'lokal_oauth_weg' })}>
            <X size={14} />
          </button>
        </div>
      )}
      {erfolg && (
        <div className="erfolg" role="status">
          {erfolg}
          <button className="icon-knopf" aria-label="Meldung schließen" onClick={() => setErfolg(null)}>
            <X size={14} />
          </button>
        </div>
      )}
      <div className="ansicht-inhalt">
        {reiter === 'installiert' && offen && <IntegrationDetail id={offen} onZurueck={() => setOffen(null)} onGeaendert={neuLaden} />}
        {reiter === 'installiert' && !offen && (
          <Installierte liste={liste} katalog={katalog} laden={laden} onOeffnen={setOffen} onHinzufuegen={zumHinzufuegen} />
        )}
        {reiter === 'hinzufuegen' && <Hinzufuegen eintraege={katalog} installiert={installiert} onAnlegen={anlegen} onInstalliert={angelegt} />}
      </div>
    </section>
  );
}
