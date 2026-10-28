// Eingaben mit zweiseitiger Bindung: lokal sofort ins Datenmodell, an den Kern bei Blur/Enter
// (CheckBox und ChoicePicker sofort, da es dort kein „Fertig tippen“ gibt).
import { useId, type KeyboardEvent } from 'react';
import type { BausteinProps } from '../register';
import { useBaustein } from '../kontext';
import { alsText, textAufloesen } from '../binder';
import { wahl } from './hilfen';

export function TextField({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const id = useId();
  const { pfad, wert } = h.bindung('value');
  const variante = wahl(k.variant, ['shortText', 'longText', 'number', 'obscured'] as const, 'shortText');
  const aendern = (roh: string) => {
    if (variante === 'number') {
      const n = Number(roh.replace(',', '.'));
      h.setzen(pfad, roh.trim() === '' || !Number.isFinite(n) ? null : n);
    } else h.setzen(pfad, roh);
  };
  const melden = () => h.melden(pfad, h.bindung('value').wert ?? '');
  const anzeige = wert === null || wert === undefined ? '' : typeof wert === 'number' ? String(wert) : alsText(wert);
  return (
    <div className="b-feld">
      <label htmlFor={id}>{h.t('label')}</label>
      {variante === 'longText' ? (
        <textarea id={id} rows={3} value={anzeige} onChange={(e) => aendern(e.target.value)} onBlur={melden} />
      ) : (
        <input
          id={id}
          type={variante === 'number' ? 'number' : variante === 'obscured' ? 'password' : 'text'}
          value={anzeige}
          onChange={(e) => aendern(e.target.value)}
          onBlur={melden}
          onKeyDown={(e: KeyboardEvent) => {
            if (e.key === 'Enter') melden();
          }}
        />
      )}
    </div>
  );
}

export function CheckBox({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const { pfad, wert } = h.bindung('value');
  return (
    <label className="b-checkbox">
      <input
        type="checkbox"
        checked={wert === true}
        onChange={(e) => {
          h.setzen(pfad, e.target.checked);
          h.melden(pfad, e.target.checked);
        }}
      />
      <span>{h.t('label')}</span>
    </label>
  );
}

interface Option { label: string; value: string }

function optionenAus(roh: unknown, t: (x: unknown) => string): Option[] {
  if (!Array.isArray(roh)) return [];
  return roh.flatMap((o) => {
    if (typeof o === 'string') return [{ label: o, value: o }];
    if (typeof o !== 'object' || o === null) return [];
    const { label, value } = o as { label?: unknown; value?: unknown };
    const v = alsText(value);
    return [{ label: t(label) || v, value: v }];
  });
}

export function ChoicePicker({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const id = useId();
  const { pfad, wert } = h.bindung('value');
  const stil = wahl(k.displayStyle, ['chips', 'dropdown', 'checkbox'] as const, 'chips');
  const optionen = optionenAus(k.options, (x) => textAufloesen(x, h.ctx));
  const label = h.t('label');
  const waehlen = (v: unknown) => {
    h.setzen(pfad, v);
    h.melden(pfad, v);
  };
  if (stil === 'dropdown')
    return (
      <div className="b-feld">
        <label htmlFor={id}>{label}</label>
        <select id={id} value={typeof wert === 'string' ? wert : ''} onChange={(e) => waehlen(e.target.value)}>
          <option value="">–</option>
          {optionen.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    );
  if (stil === 'checkbox') {
    const auswahl = Array.isArray(wert) ? wert.map(String) : [];
    return (
      <fieldset className="b-auswahl" aria-label={label}>
        <legend>{label}</legend>
        {optionen.map((o) => (
          <label key={o.value} className="b-checkbox">
            <input
              type="checkbox"
              checked={auswahl.includes(o.value)}
              onChange={(e) => waehlen(e.target.checked ? [...auswahl, o.value] : auswahl.filter((x) => x !== o.value))}
            />
            <span>{o.label}</span>
          </label>
        ))}
      </fieldset>
    );
  }
  return (
    <div className="b-feld">
      <span className="b-feld-label" id={id}>
        {label}
      </span>
      <div className="b-chips" role="radiogroup" aria-labelledby={id}>
        {optionen.map((o) => (
          <button key={o.value} type="button" role="radio" aria-checked={wert === o.value} className="b-chip" onClick={() => waehlen(o.value)}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function DateTimeInput({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const id = useId();
  const { pfad, wert } = h.bindung('value');
  const datum = k.enableDate !== false;
  const zeit = k.enableTime === true;
  const typ = datum && zeit ? 'datetime-local' : zeit ? 'time' : 'date';
  const text = typeof wert === 'string' ? wert : '';
  // ISO-Werte auf das Eingabeformat kürzen (ohne Sekunden/Zeitzone).
  const anzeige = typ === 'date' ? text.slice(0, 10) : typ === 'time' ? (text.includes('T') ? text.split('T')[1] ?? '' : text).slice(0, 5) : text.slice(0, 16);
  return (
    <div className="b-feld">
      <label htmlFor={id}>{h.t('label')}</label>
      <input id={id} type={typ} value={anzeige} onChange={(e) => h.setzen(pfad, e.target.value)} onBlur={() => h.melden(pfad, h.bindung('value').wert ?? '')} />
    </div>
  );
}
