import { useEffect, useRef, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { useJarvis, useName } from '../state/store';
import { alsText } from '../lib/format';

export const FREIGABE_SEKUNDEN = 120;

const RISIKO_TEXT: Record<string, string> = {
  kritisch: 'Kritische Aktion',
  aendern: 'Ändert Daten',
  lesen: 'Nur lesen',
};

export function ApprovalDialog() {
  const anfrage = useJarvis((s) => s.freigaben[0]);
  const weitere = useJarvis((s) => s.freigaben.length - 1);
  const beantworten = useJarvis((s) => s.freigabeBeantworten);
  const name = useName();
  const [jetzt, setJetzt] = useState(() => Date.now());
  const ablehnenRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!anfrage) return;
    setJetzt(Date.now());
    const t = setInterval(() => setJetzt(Date.now()), 250);
    ablehnenRef.current?.focus();
    return () => clearInterval(t);
  }, [anfrage]);

  const gesamt = Math.round(anfrage?.timeout ?? FREIGABE_SEKUNDEN);
  const rest = anfrage ? Math.max(0, gesamt - Math.floor((jetzt - anfrage.empfangen) / 1000)) : 0;

  useEffect(() => {
    if (anfrage && rest <= 0) beantworten(anfrage.id, false);
  }, [anfrage, rest, beantworten]);

  if (!anfrage) return null;

  const kritisch = anfrage.risiko === 'kritisch';
  const argText = alsText(anfrage.argumente);
  const anteil = rest / gesamt;

  const fokusFalle = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab' || !dialogRef.current) return;
    const ziele = dialogRef.current.querySelectorAll<HTMLElement>('button, [tabindex="0"]');
    const erstes = ziele[0];
    const letztes = ziele[ziele.length - 1];
    if (!erstes || !letztes) return;
    if (e.shiftKey && document.activeElement === erstes) {
      e.preventDefault();
      letztes.focus();
    } else if (!e.shiftKey && document.activeElement === letztes) {
      e.preventDefault();
      erstes.focus();
    }
  };

  return (
    <div className="dialog-schleier freigabe-schleier">
      <div
        ref={dialogRef}
        className={`freigabe ${kritisch ? 'kritisch' : 'aendern'}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="freigabe-titel"
        aria-describedby="freigabe-grund"
        onKeyDown={fokusFalle}
      >
        <div className="freigabe-streifen" aria-hidden="true" />
        <header className="freigabe-kopf">
          <ShieldAlert size={22} aria-hidden="true" />
          <div>
            <div className="freigabe-risiko">{RISIKO_TEXT[anfrage.risiko] ?? anfrage.risiko}</div>
            <h2 id="freigabe-titel">Darf {name} das ausführen?</h2>
          </div>
          <div
            className="countdown"
            role="timer"
            aria-label={`Noch ${rest} Sekunden, danach automatisch abgelehnt`}
            style={{ ['--anteil' as string]: anteil }}
          >
            <svg viewBox="0 0 44 44" aria-hidden="true">
              <circle cx="22" cy="22" r="19" className="countdown-spur" />
              <circle cx="22" cy="22" r="19" className="countdown-wert" pathLength={100} strokeDasharray={`${anteil * 100} 100`} />
            </svg>
            <span>{rest}</span>
          </div>
        </header>

        <dl className="freigabe-daten">
          <dt>Werkzeug</dt>
          <dd className="mono">{anfrage.werkzeug}</dd>
          <dt>Grund</dt>
          <dd id="freigabe-grund">{anfrage.grund || 'Kein Grund angegeben.'}</dd>
          {argText && (
            <>
              <dt>Argumente</dt>
              <dd>
                <pre tabIndex={0}>{argText}</pre>
              </dd>
            </>
          )}
        </dl>

        <p className="freigabe-hinweis">
          Ohne Antwort wird in {rest} s automatisch abgelehnt.
          {weitere === 1 && ' 1 weitere Anfrage wartet.'}
          {weitere > 1 && ` ${weitere} weitere Anfragen warten.`}
        </p>

        <footer className="freigabe-knoepfe">
          <button ref={ablehnenRef} className="knopf" onClick={() => beantworten(anfrage.id, false)}>
            Ablehnen
            <kbd>Esc</kbd>
          </button>
          <button className="knopf gefahr" onClick={() => beantworten(anfrage.id, true)}>
            Erlauben
          </button>
        </footer>
      </div>
    </div>
  );
}
