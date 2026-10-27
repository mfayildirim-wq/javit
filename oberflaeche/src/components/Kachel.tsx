import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';

interface Props {
  titel: string;
  children: ReactNode;
  onClick?: () => void;
  aktionText?: string;
}

/** HUD-Kachel mit Eckwinkeln. Klickbar, wenn onClick gesetzt ist. */
export function Kachel({ titel, children, onClick, aktionText }: Props) {
  return (
    <section className={`kachel ${onClick ? 'klickbar' : ''}`}>
      <span className="ecke ol" aria-hidden="true" />
      <span className="ecke ur" aria-hidden="true" />
      <header className="kachel-kopf">
        <h3>{titel}</h3>
        {onClick && (
          <button className="kachel-aktion" onClick={onClick} aria-label={aktionText ?? titel}>
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        )}
      </header>
      {children}
    </section>
  );
}
