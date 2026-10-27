import { useEffect, useRef, useState } from 'react';
import { Check, Circle, ExternalLink, Play, RefreshCw, Upload } from 'lucide-react';
import { api } from '../api/rest';
import type { Schritt, SchrittStand } from '../api/types';

/** Liest eine Datei als Base64 (ohne data:-Präfix). */
function dateiAlsBase64(datei: File): Promise<string> {
  return new Promise((loesen, ablehnen) => {
    const leser = new FileReader();
    leser.onerror = () => ablehnen(new Error('Datei konnte nicht gelesen werden.'));
    leser.onload = () => {
      const s = String(leser.result ?? '');
      loesen(s.includes(',') ? s.slice(s.indexOf(',') + 1) : s);
    };
    leser.readAsDataURL(datei);
  });
}

function DateiSchritt({ katalogId, nummer, onErledigt }: { katalogId: string; nummer: number; onErledigt: (schritte: Schritt[]) => void }) {
  const eingabe = useRef<HTMLInputElement>(null);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const hochladen = async (datei: File | undefined) => {
    if (!datei) return;
    setLaeuft(true);
    setFehler(null);
    try {
      const r = await api.einrichtungDatei(katalogId, nummer, await dateiAlsBase64(datei));
      onErledigt(r.einrichtung);
    } catch (e) {
      setFehler((e as Error).message);
    } finally {
      setLaeuft(false);
      if (eingabe.current) eingabe.current.value = '';
    }
  };
  return (
    <span className="schritt-aktion">
      <input
        ref={eingabe}
        type="file"
        accept=".json,application/json"
        hidden
        aria-label={`Datei für Schritt ${nummer + 1} auswählen`}
        onChange={(e) => void hochladen(e.target.files?.[0])}
      />
      <button type="button" className="knopf klein" disabled={laeuft} onClick={() => eingabe.current?.click()}>
        <Upload size={14} aria-hidden="true" /> {laeuft ? 'Lädt hoch …' : 'Datei hochladen'}
      </button>
      {fehler && <span className="formular-fehler">{fehler}</span>}
    </span>
  );
}

function BefehlSchritt({ katalogId, nummer, befehl }: { katalogId: string; nummer: number; befehl: string }) {
  const [stand, setStand] = useState<SchrittStand | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [offen, setOffen] = useState(false);
  const timer = useRef<number | null>(null);

  const abfragen = async () => {
    try {
      const s = await api.einrichtungStand(katalogId, nummer);
      setStand(s);
      if (s.status === 'laeuft') timer.current = window.setTimeout(() => void abfragen(), 1500);
    } catch (e) {
      setFehler((e as Error).message);
    }
  };
  useEffect(() => {
    void abfragen();
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [katalogId, nummer]);

  const starten = async () => {
    setFehler(null);
    try {
      const s = await api.einrichtungAusfuehren(katalogId, nummer);
      setStand(s);
      setOffen(true);
      timer.current = window.setTimeout(() => void abfragen(), 1500);
    } catch (e) {
      setFehler((e as Error).message);
    }
  };

  const laeuft = stand?.status === 'laeuft';
  return (
    <span className="schritt-aktion befehl">
      <code className="schritt-befehl">{befehl}</code>
      <button type="button" className="knopf klein" disabled={laeuft} onClick={() => void starten()}>
        {laeuft ? <RefreshCw size={14} aria-hidden="true" className="dreht" /> : <Play size={14} aria-hidden="true" />}
        {laeuft ? 'Läuft …' : stand && stand.status !== 'nie' ? 'Erneut ausführen' : 'Ausführen'}
      </button>
      {stand && stand.status !== 'nie' && (
        <button type="button" className="text-knopf" onClick={() => setOffen(!offen)}>
          {stand.status === 'fertig' ? 'Fertig' : stand.status === 'fehler' ? 'Fehlgeschlagen' : `${stand.sekunden} s`} – Ausgabe {offen ? 'verbergen' : 'zeigen'}
        </button>
      )}
      {fehler && <span className="formular-fehler">{fehler}</span>}
      {offen && stand && stand.ausgabe.length > 0 && <pre className="protokoll">{stand.ausgabe.join('\n')}</pre>}
    </span>
  );
}

/** Checkliste der Einrichtungsschritte eines Katalogeintrags mit Prüfungen, Upload und Ausführen. */
export function EinrichtungListe({
  katalogId,
  schritte,
  onAktualisiert,
}: {
  katalogId: string;
  schritte: Schritt[];
  onAktualisiert: (schritte: Schritt[]) => void;
}) {
  const [prueft, setPrueft] = useState(false);
  const pruefen = async () => {
    setPrueft(true);
    try {
      const k = await api.katalogDetail(katalogId);
      onAktualisiert(k.einrichtung ?? []);
    } finally {
      setPrueft(false);
    }
  };
  if (schritte.length === 0) return null;
  const offen = schritte.filter((s) => s.erfuellt === false).length;
  return (
    <section className="einrichtung" aria-label="Einrichtung">
      <div className="einrichtung-kopf">
        <h4>Einrichtung</h4>
        <span className="gedaempft">{offen === 0 ? 'Alle prüfbaren Schritte erledigt' : `${offen} ${offen === 1 ? 'Schritt' : 'Schritte'} offen`}</span>
        <button type="button" className="knopf klein leise" onClick={() => void pruefen()} disabled={prueft}>
          <RefreshCw size={14} aria-hidden="true" className={prueft ? 'dreht' : ''} /> Erneut prüfen
        </button>
      </div>
      <ol className="schritte">
        {schritte.map((s, i) => (
          <li key={i} className={`schritt ${s.erfuellt === true ? 'erledigt' : s.erfuellt === false ? 'offen' : ''}`}>
            <span className="schritt-status" aria-hidden="true">
              {s.erfuellt === true ? <Check size={16} /> : <Circle size={14} />}
            </span>
            <div className="schritt-text">
              <div className="schritt-titel">
                {i + 1}. {s.titel}
                {s.erfuellt === true && <span className="marke-chip lokal">erledigt</span>}
                {s.erfuellt === false && <span className="marke-chip aus">offen</span>}
              </div>
              {s.text && <p>{s.text}</p>}
              {s.datei && (
                <p className="gedaempft">
                  Ziel: <code>{s.datei}</code>
                </p>
              )}
              <div className="schritt-aktionen">
                {s.link && (
                  <a className="knopf klein" href={s.link} target="_blank" rel="noreferrer">
                    <ExternalLink size={14} aria-hidden="true" /> Öffnen
                  </a>
                )}
                {s.datei && <DateiSchritt katalogId={katalogId} nummer={i} onErledigt={onAktualisiert} />}
                {s.befehl && <BefehlSchritt katalogId={katalogId} nummer={i} befehl={s.befehl} />}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
