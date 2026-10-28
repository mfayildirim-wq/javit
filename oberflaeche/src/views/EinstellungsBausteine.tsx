// Gemeinsame Bausteine der Einstellungen (Abschnitt, Schalter, Segmente).
import type { ReactNode } from 'react';

export function Abschnitt({ titel, text, children, id }: { titel: string; text?: string; children: ReactNode; id: string }) {
  return (
    <section className="abschnitt" aria-labelledby={id}>
      <header>
        <h2 id={id}>{titel}</h2>
        {text && <p>{text}</p>}
      </header>
      <div className="abschnitt-inhalt">{children}</div>
    </section>
  );
}

export function Schalter({ an, onChange, label, beschreibung }: { an: boolean; onChange: (v: boolean) => void; label: string; beschreibung?: string }) {
  return (
    <label className="schalter-zeile">
      <span>
        <span className="schalter-label">{label}</span>
        {beschreibung && <span className="schalter-text">{beschreibung}</span>}
      </span>
      <input type="checkbox" role="switch" className="schalter" checked={an} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

export function Segmente<T extends string>({ wert, optionen, onChange, label }: { wert: T; optionen: [T, string][]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="feld">
      <span className="feld-label">{label}</span>
      <div className="seg-gruppe" role="radiogroup" aria-label={label}>
        {optionen.map(([v, t]) => (
          <button type="button" key={v} role="radio" aria-checked={wert === v} className={wert === v ? 'an' : ''} onClick={() => onChange(v)}>
            {t}
          </button>
        ))}
      </div>
    </div>
  );
}
