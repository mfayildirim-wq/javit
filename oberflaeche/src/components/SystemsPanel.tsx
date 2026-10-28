import { useEffect, useState } from 'react';
import { api } from '../api/rest';
import type { Integration, Modelle, Werkzeug } from '../api/types';
import { useJarvis } from '../state/store';
import { datum, kalenderwoche, modellAnbieter, modellKurz } from '../lib/format';
import { weckwortAnzeige } from '../lib/name';
import { Kachel } from './Kachel';
import { Marke } from './TopBar';

function Uhr() {
  const [jetzt, setJetzt] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setJetzt(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const hh = String(jetzt.getHours()).padStart(2, '0');
  const mm = String(jetzt.getMinutes()).padStart(2, '0');
  const ss = String(jetzt.getSeconds()).padStart(2, '0');
  return (
    <div className="uhr">
      <time className="uhr-zeit" dateTime={jetzt.toISOString()}>
        {hh}
        <span className="uhr-trenner">:</span>
        {mm}
        <span className="uhr-sek">{ss}</span>
      </time>
      <div className="uhr-datum">{datum(jetzt)}</div>
      <div className="uhr-kw">KW {kalenderwoche(jetzt)}</div>
    </div>
  );
}


function PegelBalken() {
  const pegel = useJarvis((s) => s.pegel);
  const zustand = useJarvis((s) => s.zustand);
  const aktiv = zustand === 'hoert' || zustand === 'spricht';
  const balken = 16;
  const an = Math.round((aktiv ? pegel : 0) * balken);
  return (
    <div className="pegel" aria-label={`Audiopegel ${Math.round(pegel * 100)} %`} role="meter" aria-valuenow={Math.round(pegel * 100)} aria-valuemin={0} aria-valuemax={100}>
      {Array.from({ length: balken }, (_, i) => (
        <span key={i} className={i < an ? 'an' : ''} />
      ))}
    </div>
  );
}

export function SystemsPanel() {
  const status = useJarvis((s) => s.status);
  const verbindung = useJarvis((s) => s.verbindung);
  const stand = useJarvis((s) => s.integrationsStand);
  const setAnsicht = useJarvis((s) => s.setAnsicht);
  const [integrationen, setIntegrationen] = useState<Integration[]>([]);
  const [werkzeuge, setWerkzeuge] = useState<Werkzeug[]>([]);
  const [modelle, setModelle] = useState<Modelle | null>(null);

  useEffect(() => {
    if (verbindung !== 'offen') return;
    let aktiv = true;
    void Promise.allSettled([api.integrationen(), api.werkzeuge(), api.modelle()]).then(([i, w, m]) => {
      if (!aktiv) return;
      if (i.status === 'fulfilled') setIntegrationen(i.value);
      if (w.status === 'fulfilled') setWerkzeuge(w.value);
      if (m.status === 'fulfilled') setModelle(m.value);
    });
    return () => {
      aktiv = false;
    };
  }, [verbindung, stand, status?.modell]);

  const modell = status?.modell ?? modelle?.aktuell ?? '';
  const lokal = modell.startsWith('ollama/') || modelle?.vorschlaege.find((v) => v.id === modell)?.lokal === true;
  const risiko = { lesen: 0, aendern: 0, kritisch: 0 };
  for (const w of werkzeuge) {
    if (w.risiko === 'lesen' || w.risiko === 'aendern' || w.risiko === 'kritisch') risiko[w.risiko] += 1;
  }
  const werkzeugZahl = status?.werkzeuge ?? werkzeuge.length;
  const stimme = status?.stimme;

  return (
    <aside className="leiste leiste-links" aria-label="Systeme">
      <Marke />
      <Uhr />

      <Kachel titel="Modell" onClick={() => setAnsicht('einstellungen')} aktionText="Modell ändern">
        <div className="kachel-wert gross" title={modell}>
          {modell ? modellKurz(modell) : '—'}
        </div>
        <div className="kachel-zeile">
          <span>{modell ? modellAnbieter(modell) : 'unbekannt'}</span>
          {modell && <span className={`marke-chip ${lokal ? 'lokal' : 'cloud'}`}>{lokal ? 'lokal' : 'Cloud'}</span>}
        </div>
      </Kachel>

      <Kachel titel="Stimme">
        <div className="kachel-zeile">
          <span className={`led ${stimme?.aktiv ? 'an' : ''}`} aria-hidden="true" />
          <span className="kachel-wert">{stimme ? (stimme.aktiv ? 'Mikrofon an' : 'Mikrofon aus') : '—'}</span>
        </div>
        <div className="kachel-zeile gedaempft">
          Weckwort{' '}
          <span className="hell">
            {typeof stimme?.weckwort === 'string' ? `„${weckwortAnzeige(stimme.weckwort)}“` : stimme?.weckwort ? 'an' : 'aus'}
          </span>
          {stimme?.engine && <span className="weckwort-engine"> · {stimme.engine === 'vosk' ? 'Vosk' : stimme.engine === 'openwakeword' ? 'openWakeWord' : stimme.engine}</span>}
        </div>
        <PegelBalken />
      </Kachel>

      <Kachel titel="Integrationen" onClick={() => setAnsicht('integrationen')} aktionText="Integrationen verwalten">
        <div className="kachel-wert gross">
          {status?.integrationen ?? integrationen.length}
          <span className="einheit">aktiv</span>
        </div>
        <ul className="mini-liste">
          {integrationen.slice(0, 5).map((i) => (
            <li key={i.id}>
              <span className={`status-punkt s-${i.status}`} aria-hidden="true" />
              <span className="mini-name">{i.name}</span>
              <span className="mini-zahl">{i.werkzeuge}</span>
            </li>
          ))}
          {integrationen.length > 5 && <li className="gedaempft">und {integrationen.length - 5} weitere</li>}
          {integrationen.length === 0 && <li className="gedaempft">Noch keine – hinzufügen über „Integrationen“.</li>}
        </ul>
      </Kachel>

      <Kachel titel="Werkzeuge">
        <div className="kachel-wert gross">
          {werkzeugZahl}
          <span className="einheit">verfügbar</span>
        </div>
        {werkzeuge.length > 0 && (
          <>
            <div className="risiko-balken" aria-hidden="true">
              <span className="r-lesen" style={{ flexGrow: risiko.lesen }} />
              <span className="r-aendern" style={{ flexGrow: risiko.aendern }} />
              <span className="r-kritisch" style={{ flexGrow: risiko.kritisch }} />
            </div>
            <div className="risiko-legende">
              <span>
                <i className="r-lesen" />
                {risiko.lesen} lesen
              </span>
              <span>
                <i className="r-aendern" />
                {risiko.aendern} ändern
              </span>
              <span>
                <i className="r-kritisch" />
                {risiko.kritisch} kritisch
              </span>
            </div>
          </>
        )}
      </Kachel>

      <div className="leiste-fuss">Kern {status?.version ? `v${status.version}` : 'unbekannt'}</div>
    </aside>
  );
}
