// Neuen Stil ableiten: aus einer Webseite (URL), einer hochgeladenen Datei (CSS/JSON/Tailwind) oder eingefügten Klassen.
import { useState, type FormEvent } from 'react';
import { api } from '../../api/rest';
import type { StilAnlegen } from '../../api/types';
import { Segmente } from '../EinstellungsBausteine';

type Art = 'url' | 'datei' | 'klassen';

/** Datei als Base64 ohne „data:…;base64,“-Präfix. */
export function dateiAlsBase64(datei: Blob): Promise<string> {
  return new Promise((ok, fehler) => {
    const leser = new FileReader();
    leser.onload = () => ok(String(leser.result).replace(/^data:[^,]*,/, ''));
    leser.onerror = () => fehler(new Error('Datei nicht lesbar'));
    leser.readAsDataURL(datei);
  });
}

export function StilAbleiten({ onAngelegt }: { onAngelegt: () => void }) {
  const [art, setArt] = useState<Art>('url');
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [klassen, setKlassen] = useState('');
  const [datei, setDatei] = useState<File | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const bereit = name.trim() !== '' && (art === 'url' ? /^https?:\/\//.test(url.trim()) : art === 'datei' ? datei !== null : klassen.trim() !== '');

  const ableiten = async (e: FormEvent) => {
    e.preventDefault();
    if (!bereit) return;
    setLaeuft(true);
    setFehler(null);
    setMeldung(null);
    try {
      let quelle: StilAnlegen['quelle'];
      if (art === 'url') quelle = { art, wert: url.trim() };
      else if (art === 'klassen') quelle = { art, wert: klassen };
      else quelle = { art, wert: datei!.name, inhalt_base64: await dateiAlsBase64(datei!) };
      const stil = await api.buehneStilAnlegen({ name: name.trim(), quelle });
      setMeldung(`Stil „${stil.name || name.trim()}“ angelegt.`);
      setName('');
      onAngelegt();
    } catch (err) {
      setFehler((err as Error).message);
    } finally {
      setLaeuft(false);
    }
  };

  return (
    <form className="stil-ableiten" aria-label="Stil ableiten" onSubmit={ableiten}>
      <Segmente<Art> label="Quelle" wert={art} optionen={[['url', 'Aus URL ableiten'], ['datei', 'Datei hochladen'], ['klassen', 'Klassen einfügen']]} onChange={setArt} />
      <div className="feld">
        <label htmlFor="ableiten-name">Name des Stils</label>
        <input id="ableiten-name" value={name} placeholder="z. B. GG Immobilien" onChange={(e) => setName(e.target.value)} />
      </div>
      {art === 'url' && (
        <div className="feld">
          <label htmlFor="ableiten-url">Adresse (https)</label>
          <input id="ableiten-url" className="mono" type="url" placeholder="https://m3.material.io" value={url} onChange={(e) => setUrl(e.target.value)} />
        </div>
      )}
      {art === 'datei' && (
        <div className="feld">
          <label htmlFor="ableiten-datei">Datei</label>
          <input id="ableiten-datei" type="file" accept=".css,.json,.js,.cjs,.mjs,.ts,.txt,.scss" onChange={(e) => setDatei(e.target.files?.[0] ?? null)} />
          <p className="feld-hilfe">CSS, JSON-Design-Tokens oder Tailwind-Konfiguration (nur Werte werden übernommen).</p>
        </div>
      )}
      {art === 'klassen' && (
        <div className="feld">
          <label htmlFor="ableiten-klassen">Klassen oder CSS</label>
          <textarea id="ableiten-klassen" className="mono" rows={5} value={klassen} onChange={(e) => setKlassen(e.target.value)} />
        </div>
      )}
      <button type="submit" className="knopf primaer" disabled={!bereit || laeuft}>
        {laeuft ? 'Leite ab …' : 'Stil ableiten'}
      </button>
      {meldung && <p className="ok-text" role="status">{meldung}</p>}
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </form>
  );
}
