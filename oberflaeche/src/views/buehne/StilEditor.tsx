// Stil bearbeiten: Farbwähler + Hex je Farbe, Schrift, Rundung/Abstand, Dichte/Schatten/Schema,
// Kontrastprüfung (WCAG) und Live-Vorschau. Vordefinierte Stile speichert der Kern als Kopie.
import { useState, type FormEvent } from 'react';
import { api } from '../../api/rest';
import type { Stil, StilWerte } from '../../api/types';
import { FARB_NAMEN, hexLang, istHex, kontrast } from '../../buehne/stile';
import { Segmente } from '../EinstellungsBausteine';
import { StilVorschau } from './StilVorschau';

type Farbe = keyof StilWerte['farben'];

function FarbFeld({ titel, wert, onChange }: { titel: string; wert: string; onChange: (hex: string) => void }) {
  const [text, setText] = useState(wert);
  const [zuletzt, setZuletzt] = useState(wert);
  if (wert !== zuletzt) {
    // Von außen geändert (Farbwähler): Hex-Feld nachziehen.
    setZuletzt(wert);
    setText(wert);
  }
  return (
    <div className="farb-feld">
      <input type="color" aria-label={`${titel} (Farbwähler)`} value={hexLang(wert) ?? '#000000'} onChange={(e) => onChange(e.target.value)} />
      <span className="farb-titel">{titel}</span>
      <input
        className="mono"
        aria-label={`${titel} (Hex)`}
        aria-invalid={!istHex(text)}
        value={text}
        maxLength={9}
        onChange={(e) => {
          const t = e.target.value.trim();
          setText(t);
          if (istHex(t)) {
            setZuletzt(t);
            onChange(t);
          }
        }}
      />
    </div>
  );
}

const zahl = (x: string, standard: number) => (Number.isFinite(Number(x)) && x !== '' ? Number(x) : standard);

export function StilEditor({ stil, onFertig }: { stil: Stil; onFertig: (meldung: string | null) => void }) {
  const [name, setName] = useState(stil.name);
  const [werte, setWerte] = useState<StilWerte>(structuredClone(stil.werte));
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const farbe = (f: Farbe, hex: string) => setWerte((w) => ({ ...w, farben: { ...w.farben, [f]: hex } }));
  const k1 = kontrast(werte.farben.text, werte.farben.hintergrund);
  const k2 = kontrast(werte.farben.text, werte.farben.flaeche);
  const eigen = stil.eigen === true || (stil.eigen === undefined && stil.quelle.art !== 'vordefiniert');

  const ausfuehren = async (aufruf: () => Promise<Stil>, meldung: (s: Stil) => string) => {
    setLaeuft(true);
    setFehler(null);
    try {
      const s = await aufruf();
      onFertig(meldung(s));
    } catch (e) {
      setFehler((e as Error).message);
    } finally {
      setLaeuft(false);
    }
  };
  const speichern = (e: FormEvent) => {
    e.preventDefault();
    void ausfuehren(() => api.buehneStilAendern(stil.id, { name: name.trim() || stil.name, werte }), (s) => `Stil „${s.name}“ gespeichert.`);
  };
  const alsNeu = () =>
    void ausfuehren(() => api.buehneStilAnlegen({ name: name.trim() || `${stil.name} (Kopie)`, quelle: { art: 'werte', werte } }), (s) => `Stil „${s.name}“ als neuer Stil gespeichert.`);

  return (
    <form className="stil-editor" aria-label="Stil bearbeiten" onSubmit={speichern}>
      <div className="stil-editor-spalten">
        <div className="stil-editor-felder">
          <div className="feld">
            <label htmlFor="stil-name">Name</label>
            <input id="stil-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="farb-raster">
            {FARB_NAMEN.map(({ schluessel, titel }) => (
              <FarbFeld key={schluessel} titel={titel} wert={werte.farben[schluessel]} onChange={(hex) => farbe(schluessel, hex)} />
            ))}
          </div>
          <p className={k1 < 4.5 || k2 < 4.5 ? 'formular-fehler' : 'feld-hilfe'} role="status">
            Kontrast Text/Hintergrund: {k1.toLocaleString('de-DE', { maximumFractionDigits: 1 })} : 1, Text/Fläche: {k2.toLocaleString('de-DE', { maximumFractionDigits: 1 })} : 1
            {(k1 < 4.5 || k2 < 4.5) && ' – unter 4,5 : 1, schwer lesbar (WCAG AA).'}
          </p>
          <div className="feld-reihe">
            <div className="feld">
              <label htmlFor="stil-schrift">Schriftfamilie</label>
              <input id="stil-schrift" value={werte.schrift.familie} onChange={(e) => setWerte((w) => ({ ...w, schrift: { ...w.schrift, familie: e.target.value } }))} />
            </div>
            <div className="feld stil-basis">
              <label htmlFor="stil-basis">Basisgröße</label>
              <input id="stil-basis" type="number" min={10} max={22} value={werte.schrift.basisgroesse} onChange={(e) => setWerte((w) => ({ ...w, schrift: { ...w.schrift, basisgroesse: zahl(e.target.value, 14) } }))} />
            </div>
          </div>
          <div className="feld-reihe">
            <div className="feld">
              <label htmlFor="stil-rundung">Rundung <span>{werte.rundung} px</span></label>
              <input id="stil-rundung" type="range" min={0} max={24} value={werte.rundung} onChange={(e) => setWerte((w) => ({ ...w, rundung: zahl(e.target.value, 10) }))} />
            </div>
            <div className="feld">
              <label htmlFor="stil-abstand">Abstand <span>{werte.abstand} px</span></label>
              <input id="stil-abstand" type="range" min={4} max={32} value={werte.abstand} onChange={(e) => setWerte((w) => ({ ...w, abstand: zahl(e.target.value, 12) }))} />
            </div>
          </div>
          <Segmente label="Dichte" wert={werte.dichte} optionen={[['dicht', 'Dicht'], ['normal', 'Normal'], ['luftig', 'Luftig']]} onChange={(dichte) => setWerte((w) => ({ ...w, dichte }))} />
          <Segmente label="Schatten" wert={werte.schatten} optionen={[['keiner', 'Keiner'], ['weich', 'Weich'], ['stark', 'Stark']]} onChange={(schatten) => setWerte((w) => ({ ...w, schatten }))} />
          <Segmente label="Schema" wert={werte.schema} optionen={[['dunkel', 'Dunkel'], ['hell', 'Hell']]} onChange={(schema) => setWerte((w) => ({ ...w, schema }))} />
        </div>
        <StilVorschau werte={werte} name={name || stil.name} />
      </div>
      <div className="feld-reihe frei">
        <button type="submit" className="knopf primaer" disabled={laeuft}>
          {eigen ? 'Speichern' : 'Als Kopie speichern'}
        </button>
        <button type="button" className="knopf" disabled={laeuft} onClick={alsNeu}>
          Als neuen Stil speichern
        </button>
        <button type="button" className="knopf leise" onClick={() => onFertig(null)}>
          Abbrechen
        </button>
      </div>
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </form>
  );
}
