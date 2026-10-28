// Layout-Bausteine: Column, Row, Grid, Card, List, Tabs, Divider.
import { useId, useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { BausteinProps } from '../register';
import { useBaustein } from '../kontext';
import { textAufloesen } from '../binder';
import { abstandStil, klassen, wahl } from './hilfen';

const JUSTIFY = ['start', 'center', 'end', 'spaceBetween'] as const;
const ALIGN = ['start', 'center', 'end', 'stretch'] as const;

function Flex({ k, basis, tiefe, richtung }: BausteinProps & { richtung: 'column' | 'row' }) {
  const h = useBaustein(k, basis, tiefe);
  return (
    <div
      className={klassen(
        richtung === 'column' ? 'b-column' : 'b-row',
        `b-justify-${wahl(k.justify, JUSTIFY, 'start')}`,
        `b-align-${wahl(k.align, ALIGN, richtung === 'column' ? 'stretch' : 'center')}`,
        k.wrap === true && 'b-wrap',
      )}
      style={abstandStil(k.gap)}
    >
      {h.kinder()}
    </div>
  );
}

export const Column = (p: BausteinProps) => <Flex {...p} richtung="column" />;
export const Row = (p: BausteinProps) => <Flex {...p} richtung="row" />;

export function Grid({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const spalten = Math.min(4, Math.max(1, Math.round(Number(k.spalten) || 2)));
  return (
    <div className={`b-grid b-spalten-${spalten}`} style={abstandStil(k.gap)}>
      {h.kinder()}
    </div>
  );
}

/** Klick auf eine Karte nicht auslösen, wenn ein inneres Bedienelement gemeint war. */
function innererKlick(e: MouseEvent | KeyboardEvent): boolean {
  const ziel = e.target as HTMLElement | null;
  const bedien = ziel?.closest('button, a, input, select, textarea, [role="button"]');
  return !!bedien && bedien !== e.currentTarget;
}

export function Card({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  if (!k.action) return <div className="b-card">{h.kind(k.child)}</div>;
  return (
    <div
      className="b-card b-klickbar"
      role="button"
      tabIndex={0}
      onClick={(e) => {
        if (!innererKlick(e)) h.ausloesen(k.action);
      }}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && !innererKlick(e)) {
          e.preventDefault();
          h.ausloesen(k.action);
        }
      }}
    >
      {h.kind(k.child)}
    </div>
  );
}

export function List({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const richtung = wahl(k.direction, ['vertical', 'horizontal'] as const, 'vertical');
  return (
    <div role="list" className={`b-list b-${richtung}`} style={abstandStil(k.gap)}>
      {h.kinder().map((kind, i) => (
        <div role="listitem" key={i} className="b-list-eintrag">
          {kind}
        </div>
      ))}
    </div>
  );
}

export function Tabs({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const [aktiv, setAktiv] = useState(0);
  const basisId = useId();
  const titel = Array.isArray(k.titles) ? k.titles.map((t) => textAufloesen(t, h.ctx)) : [];
  const kinder = Array.isArray(k.children) ? k.children.filter((x): x is string => typeof x === 'string') : [];
  const anzahl = Math.min(titel.length, kinder.length);
  const index = Math.min(aktiv, Math.max(0, anzahl - 1));
  const tasten = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') setAktiv((index + 1) % anzahl);
    if (e.key === 'ArrowLeft') setAktiv((index - 1 + anzahl) % anzahl);
  };
  return (
    <div className="b-tabs">
      <div role="tablist" className="b-tabs-leiste" onKeyDown={tasten}>
        {titel.slice(0, anzahl).map((t, i) => (
          <button
            key={i}
            type="button"
            role="tab"
            id={`${basisId}-t${i}`}
            aria-selected={i === index}
            aria-controls={`${basisId}-p`}
            tabIndex={i === index ? 0 : -1}
            className="b-tab"
            onClick={() => setAktiv(i)}
          >
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${basisId}-p`} aria-labelledby={`${basisId}-t${index}`} className="b-tabs-inhalt">
        {anzahl > 0 && h.kind(kinder[index])}
      </div>
    </div>
  );
}

export function Divider({ k }: BausteinProps) {
  const achse = wahl(k.axis, ['horizontal', 'vertical'] as const, 'horizontal');
  return <div role="separator" aria-orientation={achse} className={`b-divider b-${achse}`} />;
}
