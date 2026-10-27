import { useRef, useState, type FormEvent } from 'react';
import { CornerDownLeft, Mic, MicOff, Square, Volume2, VolumeX } from 'lucide-react';
import { istBeschaeftigt, useJarvis, useName, useWeckwort } from '../state/store';

export function Composer() {
  const [text, setText] = useState('');
  const eingabe = useRef<HTMLInputElement>(null);
  const nachrichtSenden = useJarvis((s) => s.nachrichtSenden);
  const abbrechen = useJarvis((s) => s.abbrechen);
  const stimmeSetzen = useJarvis((s) => s.stimmeSetzen);
  const vorlesen = useJarvis((s) => s.vorlesen);
  const setVorlesen = useJarvis((s) => s.setVorlesen);
  const stimmeAn = useJarvis((s) => s.status?.stimme.aktiv ?? false);
  const zustand = useJarvis((s) => s.zustand);
  const beschaeftigt = useJarvis(istBeschaeftigt);
  const verbunden = useJarvis((s) => s.verbindung === 'offen');
  const name = useName();
  const weckwort = useWeckwort();

  const absenden = (e: FormEvent) => {
    e.preventDefault();
    if (nachrichtSenden(text)) setText('');
  };

  return (
    <form className="eingabe" onSubmit={absenden}>
      <button
        type="button"
        className={`rund-knopf mikro ${stimmeAn ? 'an' : ''} ${zustand === 'hoert' ? 'hoert' : ''}`}
        aria-pressed={stimmeAn}
        aria-label={stimmeAn ? 'Mikrofon ausschalten' : 'Mikrofon einschalten'}
        title={stimmeAn ? `Mikrofon an – „${weckwort}“ aktiv` : 'Mikrofon aus'}
        onClick={() => stimmeSetzen(!stimmeAn)}
        disabled={!verbunden}
      >
        {stimmeAn ? <Mic size={18} aria-hidden="true" /> : <MicOff size={18} aria-hidden="true" />}
      </button>

      <div className="eingabe-feld">
        <input
          ref={eingabe}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={verbunden ? `Nachricht an ${name} …` : 'Warte auf Verbindung zum Kern …'}
          aria-label={`Nachricht an ${name}`}
          autoComplete="off"
          spellCheck
        />
        <span className="eingabe-tipp" aria-hidden="true">
          <kbd>Leertaste</kbd> halten zum Sprechen
        </span>
      </div>

      <button
        type="button"
        className={`rund-knopf ${vorlesen ? 'an' : ''}`}
        aria-pressed={vorlesen}
        aria-label={vorlesen ? 'Antworten nicht mehr vorlesen' : 'Antworten vorlesen'}
        title={vorlesen ? 'Antworten werden vorgelesen' : 'Antworten werden nicht vorgelesen'}
        onClick={() => setVorlesen(!vorlesen)}
      >
        {vorlesen ? <Volume2 size={18} aria-hidden="true" /> : <VolumeX size={18} aria-hidden="true" />}
      </button>

      {beschaeftigt ? (
        <button type="button" className="haupt-knopf abbrechen" onClick={abbrechen} title="Abbrechen (Esc)">
          <Square size={14} aria-hidden="true" />
          Abbrechen
        </button>
      ) : (
        <button type="submit" className="haupt-knopf" disabled={!text.trim() || !verbunden}>
          Senden
          <CornerDownLeft size={14} aria-hidden="true" />
        </button>
      )}
    </form>
  );
}
