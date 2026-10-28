// Tabelle über ein Array; Spalten mit Format; Zeilenaktion erhält die Zeile als /zeile im Kontext.
import type { BausteinProps } from '../register';
import { MAX_LISTE, useBaustein } from '../kontext';
import { alsText, formatCurrency, formatDate, formatNumber, pfadAufloesen, zeigerLesen } from '../binder';
import { wahl } from './hilfen';

interface Spalte {
  titel: string;
  path: string;
  format: 'text' | 'zahl' | 'waehrung' | 'datum' | 'badge';
  waehrung?: string;
}

const FORMATE = ['text', 'zahl', 'waehrung', 'datum', 'badge'] as const;

function spaltenAus(roh: unknown): Spalte[] {
  if (!Array.isArray(roh)) return [];
  return roh
    .filter((s): s is Record<string, unknown> => typeof s === 'object' && s !== null && typeof (s as { path?: unknown }).path === 'string')
    .map((s) => ({
      titel: typeof s.titel === 'string' ? s.titel : String(s.path),
      path: s.path as string,
      format: wahl(s.format, FORMATE, 'text'),
      waehrung: typeof s.waehrung === 'string' ? s.waehrung : undefined,
    }));
}

function Zelle({ wert, spalte }: { wert: unknown; spalte: Spalte }) {
  switch (spalte.format) {
    case 'zahl':
      return <>{formatNumber(wert)}</>;
    case 'waehrung':
      return <>{formatCurrency(wert, spalte.waehrung ?? 'EUR')}</>;
    case 'datum':
      return <>{formatDate(wert, 'dd.MM.yyyy HH:mm')}</>;
    case 'badge':
      return alsText(wert) ? <span className="b-badge b-ton-neutral">{alsText(wert)}</span> : null;
    default:
      return <>{alsText(wert)}</>;
  }
}

export function Tabelle({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const spalten = spaltenAus(k.spalten);
  const zeilenBindung = h.bindung('zeilen');
  const zeilen = Array.isArray(zeilenBindung.wert) ? zeilenBindung.wert.slice(0, MAX_LISTE) : [];
  const zeilenPfad = zeilenBindung.pfad && zeilenBindung.pfad !== '/' ? zeilenBindung.pfad : '';
  const aktion = k.zeilenAktion;
  const ausloesen = (zeile: unknown, i: number) => h.ausloesen(aktion, { zeile }, `${zeilenPfad}/${i}`);
  return (
    <div className="b-tabelle-rahmen">
      <table className="b-tabelle">
        <thead>
          <tr>
            {spalten.map((s, i) => (
              <th key={i} scope="col" className={s.format === 'zahl' || s.format === 'waehrung' ? 'b-rechts' : undefined}>
                {s.titel}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {zeilen.map((zeile, i) => {
            const zeilenBasis = `${zeilenPfad}/${i}`;
            return (
              <tr
                key={i}
                className={aktion ? 'b-klickbar' : undefined}
                tabIndex={aktion ? 0 : undefined}
                onClick={aktion ? () => ausloesen(zeile, i) : undefined}
                onKeyDown={
                  aktion
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          ausloesen(zeile, i);
                        }
                      }
                    : undefined
                }
              >
                {spalten.map((s, j) => (
                  <td key={j} className={s.format === 'zahl' || s.format === 'waehrung' ? 'b-rechts' : undefined}>
                    <Zelle wert={zeigerLesen(h.ctx.daten, pfadAufloesen(s.path, zeilenBasis))} spalte={s} />
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {zeilen.length === 0 && <p className="b-leer">Keine Einträge.</p>}
    </div>
  );
}
