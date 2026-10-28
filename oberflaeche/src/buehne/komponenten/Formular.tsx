// Formular aus einem JSON-Schema (Objekt mit string/number/integer/boolean/enum).
// Absenden: Werte ins Datenmodell (value-Bindung), buehne_daten, dann Aktion mit context.werte.
import { useEffect, useId, useState, type FormEvent } from 'react';
import type { BausteinProps } from '../register';
import { useBaustein } from '../kontext';
import { alsText } from '../binder';

interface Feld {
  name: string;
  titel: string;
  typ: 'string' | 'number' | 'boolean' | 'enum';
  optionen: string[];
  pflicht: boolean;
  beschreibung: string;
  format: string;
}

function istObjekt(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x);
}

export function felderAus(schema: unknown): Feld[] {
  if (!istObjekt(schema) || !istObjekt(schema.properties)) return [];
  const pflicht = Array.isArray(schema.required) ? schema.required.filter((x): x is string => typeof x === 'string') : [];
  return Object.entries(schema.properties).slice(0, 40).flatMap(([name, def]) => {
    if (!istObjekt(def)) return [];
    const typ = Array.isArray(def.enum) ? 'enum' : def.type === 'number' || def.type === 'integer' ? 'number' : def.type === 'boolean' ? 'boolean' : 'string';
    return [{
      name,
      titel: typeof def.title === 'string' ? def.title : name,
      typ,
      optionen: Array.isArray(def.enum) ? def.enum.map(alsText) : [],
      pflicht: pflicht.includes(name),
      beschreibung: typeof def.description === 'string' ? def.description : '',
      format: typeof def.format === 'string' ? def.format : '',
    } satisfies Feld];
  });
}

function anfangswerte(schema: unknown, gebunden: unknown): Record<string, unknown> {
  const werte: Record<string, unknown> = {};
  if (istObjekt(schema) && istObjekt(schema.properties))
    for (const [name, def] of Object.entries(schema.properties)) if (istObjekt(def) && def.default !== undefined) werte[name] = def.default;
  return istObjekt(gebunden) ? { ...werte, ...gebunden } : werte;
}

function leer(x: unknown): boolean {
  return x === undefined || x === null || (typeof x === 'string' && x.trim() === '');
}

export function Formular({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const basisId = useId();
  const { pfad, wert } = h.bindung('value');
  const gebundenText = JSON.stringify(wert ?? null);
  const [werte, setWerte] = useState<Record<string, unknown>>(() => anfangswerte(k.schema, wert));
  const [fehler, setFehler] = useState<string | null>(null);
  useEffect(() => {
    setWerte(anfangswerte(k.schema, JSON.parse(gebundenText)));
  }, [gebundenText, k.schema]);
  const felder = felderAus(k.schema);
  const setze = (name: string, v: unknown) => setWerte((w) => ({ ...w, [name]: v }));

  const absenden = (e: FormEvent) => {
    e.preventDefault();
    const fehlend = felder.filter((f) => f.pflicht && leer(werte[f.name])).map((f) => f.titel);
    if (fehlend.length) {
      setFehler(`Bitte ausfüllen: ${fehlend.join(', ')}`);
      return;
    }
    setFehler(null);
    h.setzen(pfad, werte);
    h.melden(pfad, werte);
    h.ausloesen(k.action, { werte });
  };

  return (
    <form className="b-formular" onSubmit={absenden} noValidate>
      {felder.map((f) => {
        const id = `${basisId}-${f.name}`;
        const label = `${f.titel}${f.pflicht ? ' *' : ''}`;
        const v = werte[f.name];
        if (f.typ === 'boolean')
          return (
            <label key={f.name} className="b-checkbox">
              <input type="checkbox" checked={v === true} onChange={(e) => setze(f.name, e.target.checked)} />
              <span>{f.titel}</span>
            </label>
          );
        return (
          <div key={f.name} className="b-feld">
            <label htmlFor={id}>{label}</label>
            {f.typ === 'enum' ? (
              <select id={id} value={alsText(v)} onChange={(e) => setze(f.name, e.target.value || undefined)} aria-required={f.pflicht}>
                <option value="">–</option>
                {f.optionen.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : f.typ === 'number' ? (
              <input
                id={id}
                type="number"
                value={typeof v === 'number' ? String(v) : ''}
                aria-required={f.pflicht}
                onChange={(e) => setze(f.name, e.target.value === '' ? undefined : Number(e.target.value))}
              />
            ) : f.format === 'textarea' ? (
              <textarea id={id} rows={3} value={alsText(v)} aria-required={f.pflicht} onChange={(e) => setze(f.name, e.target.value)} />
            ) : (
              <input
                id={id}
                type={f.format === 'date' ? 'date' : f.format === 'email' ? 'email' : 'text'}
                value={alsText(v)}
                aria-required={f.pflicht}
                onChange={(e) => setze(f.name, e.target.value)}
              />
            )}
            {f.beschreibung && <span className="b-hilfe">{f.beschreibung}</span>}
          </div>
        );
      })}
      {fehler && (
        <p role="alert" className="b-fehler">
          {fehler}
        </p>
      )}
      <button type="submit" className="b-button b-button-primary">
        {typeof k.absenden === 'string' && k.absenden ? k.absenden : 'Absenden'}
      </button>
    </form>
  );
}
