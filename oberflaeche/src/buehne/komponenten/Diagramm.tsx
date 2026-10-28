// Diagramm als eigenes SVG (balken, linie, kreis); serien: [{name, path → Array von {x, y}}].
import type { BausteinProps } from '../register';
import { MAX_LISTE, useBaustein } from '../kontext';
import { alsText, alsZahl, pfadAufloesen, zeigerLesen } from '../binder';
import { wahl } from './hilfen';

interface Punkt { x: string; y: number }
interface Serie { name: string; punkte: Punkt[] }

const B = 320;
const H = 160;
const RAND = 24;
const FARBEN = ['var(--b-primaer)', 'var(--b-akzent)', 'var(--b-ok)', 'var(--b-warn)', 'var(--b-fehler)', 'var(--b-dezent)'];

function punkteAus(roh: unknown): Punkt[] {
  if (!Array.isArray(roh)) return [];
  return roh.slice(0, MAX_LISTE).flatMap((p) => {
    if (typeof p === 'number') return [{ x: '', y: p }];
    if (typeof p !== 'object' || p === null) return [];
    const y = alsZahl((p as { y?: unknown }).y);
    return y === null ? [] : [{ x: alsText((p as { x?: unknown }).x), y }];
  });
}

function Balken({ serien, max }: { serien: Serie[]; max: number }) {
  const anzahl = Math.max(...serien.map((s) => s.punkte.length), 1);
  const gruppe = (B - 2 * RAND) / anzahl;
  const breite = Math.max(2, (gruppe * 0.8) / Math.max(1, serien.length));
  return (
    <>
      {serien.flatMap((s, si) =>
        s.punkte.map((p, i) => {
          const hoehe = max > 0 ? (Math.max(0, p.y) / max) * (H - 2 * RAND) : 0;
          return (
            <rect key={`${si}-${i}`} data-testid="balken" x={RAND + i * gruppe + gruppe * 0.1 + si * breite} y={H - RAND - hoehe} width={breite} height={hoehe} rx={2} fill={FARBEN[si % FARBEN.length]}>
              <title>{`${s.name} ${p.x}: ${alsText(p.y)}`}</title>
            </rect>
          );
        }),
      )}
    </>
  );
}

/** Beschriftung der x-Achse (höchstens 12 Marken) für Balken und Linie. */
function Achse({ punkte, balken }: { punkte: Punkt[]; balken: boolean }) {
  const n = punkte.length;
  if (n === 0) return null;
  const jede = Math.ceil(n / 12);
  const pos = (i: number) => (balken ? RAND + ((i + 0.5) * (B - 2 * RAND)) / n : RAND + (i * (B - 2 * RAND)) / Math.max(1, n - 1));
  return (
    <>
      {punkte.map((p, i) =>
        i % jede === 0 && p.x ? (
          <text key={i} x={pos(i)} y={H - RAND + 14} textAnchor="middle" fontSize={10} fill="var(--b-dezent)">
            {p.x.slice(0, 10)}
          </text>
        ) : null,
      )}
    </>
  );
}

function Linien({ serien, max, min }: { serien: Serie[]; max: number; min: number }) {
  const spanne = max - min || 1;
  return (
    <>
      {serien.map((s, si) => {
        const schritt = (B - 2 * RAND) / Math.max(1, s.punkte.length - 1);
        const pkt = s.punkte.map((p, i) => `${RAND + i * schritt},${H - RAND - ((p.y - min) / spanne) * (H - 2 * RAND)}`).join(' ');
        return <polyline key={si} points={pkt} fill="none" stroke={FARBEN[si % FARBEN.length]} strokeWidth={2} strokeLinejoin="round" />;
      })}
    </>
  );
}

function Kreis({ punkte }: { punkte: Punkt[] }) {
  const summe = punkte.reduce((a, p) => a + Math.max(0, p.y), 0) || 1;
  const r = H / 2 - 8;
  const cx = B / 2;
  const cy = H / 2;
  let winkel = -Math.PI / 2;
  return (
    <>
      {punkte.map((p, i) => {
        const anteil = Math.max(0, p.y) / summe;
        const ende = winkel + anteil * 2 * Math.PI;
        const gross = anteil > 0.5 ? 1 : 0;
        const d = anteil >= 0.9999
          ? `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`
          : `M ${cx} ${cy} L ${cx + r * Math.cos(winkel)} ${cy + r * Math.sin(winkel)} A ${r} ${r} 0 ${gross} 1 ${cx + r * Math.cos(ende)} ${cy + r * Math.sin(ende)} Z`;
        winkel = ende;
        return (
          <path key={i} d={d} fill={FARBEN[i % FARBEN.length]} stroke="var(--b-flaeche)" strokeWidth={1}>
            <title>{`${p.x}: ${alsText(p.y)}`}</title>
          </path>
        );
      })}
    </>
  );
}

export function Diagramm({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const typ = wahl(k.typ, ['balken', 'linie', 'kreis'] as const, 'balken');
  const titel = h.t('titel');
  const serien: Serie[] = (Array.isArray(k.serien) ? k.serien : []).slice(0, 6).flatMap((s) => {
    if (typeof s !== 'object' || s === null || typeof (s as { path?: unknown }).path !== 'string') return [];
    const { name, path } = s as { name?: unknown; path: string };
    return [{ name: alsText(name), punkte: punkteAus(zeigerLesen(h.ctx.daten, pfadAufloesen(path, basis))) }];
  });
  const werte = serien.flatMap((s) => s.punkte.map((p) => p.y));
  const max = Math.max(0, ...werte);
  const min = Math.min(0, ...werte);
  const kreisPunkte = serien[0]?.punkte ?? [];
  const legende = typ === 'kreis' ? kreisPunkte.map((p) => p.x) : serien.map((s) => s.name);
  return (
    <figure className="b-diagramm">
      {titel && <figcaption className="b-diagramm-titel">{titel}</figcaption>}
      <svg viewBox={`0 0 ${B} ${H}`} role="img" aria-label={`${titel || 'Diagramm'} (${typ})`} className="b-diagramm-svg">
        {typ !== 'kreis' && <line x1={RAND} x2={B - RAND} y1={H - RAND} y2={H - RAND} stroke="var(--b-dezent)" strokeWidth={1} opacity={0.5} />}
        {typ !== 'kreis' && <Achse punkte={serien[0]?.punkte ?? []} balken={typ === 'balken'} />}
        {typ === 'balken' && <Balken serien={serien} max={max} />}
        {typ === 'linie' && <Linien serien={serien} max={max} min={min} />}
        {typ === 'kreis' && <Kreis punkte={kreisPunkte} />}
      </svg>
      <ul className="b-diagramm-legende">
        {legende.map((n, i) => (
          <li key={i}>
            <span className="b-legende-farbe" style={{ background: FARBEN[i % FARBEN.length] }} aria-hidden="true" />
            {n}
          </li>
        ))}
      </ul>
    </figure>
  );
}
