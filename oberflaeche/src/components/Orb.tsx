import { useEffect, useRef } from 'react';
import type { Zustand } from '../api/types';
import { useJarvis } from '../state/store';

/**
 * Reaktor-Orb: Canvas-2D, ein requestAnimationFrame-Loop, pausiert im
 * Hintergrund-Tab und wenn nicht sichtbar. Liest Zustand/Pegel direkt aus
 * dem Store (kein React-Render pro Frame).
 */

interface Ziel {
  energie: number; // Grundhelligkeit
  drehung: number; // Tempo der Segmentringe
  wellen: number; // Wellenform im Kern
  orbit: number; // Orbit-Punkte (arbeitet)
  atmen: number; // Atem-Amplitude
}

const ZIELE: Record<Zustand, Ziel> = {
  bereit: { energie: 0.55, drehung: 0.12, wellen: 0, orbit: 0, atmen: 1 },
  hoert: { energie: 0.85, drehung: 0.25, wellen: 0, orbit: 0, atmen: 0.2 },
  denkt: { energie: 0.9, drehung: 2.6, wellen: 0, orbit: 0, atmen: 0.3 },
  arbeitet: { energie: 0.85, drehung: 0.9, wellen: 0, orbit: 1, atmen: 0.3 },
  spricht: { energie: 1, drehung: 0.3, wellen: 1, orbit: 0, atmen: 0.2 },
};

const CYAN: [number, number, number] = [127, 232, 255];
const EIS: [number, number, number] = [220, 250, 255];
const WARN: [number, number, number] = [255, 138, 76];

interface Partikel { r: number; w: number; v: number; g: number; p: number }

function mix(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}
function rgba(c: [number, number, number], a: number): string {
  return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
}

export interface OrbProps {
  /** Wenn false, steht die Animation still (z. B. hinter einer Ansicht). */
  aktiv?: boolean;
  className?: string;
}

export function Orb({ aktiv = true, className }: OrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const huelleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const huelle = huelleRef.current;
    if (!canvas || !huelle) return;
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext('2d');
    } catch {
      ctx = null;
    }
    if (!ctx) return;
    const c = ctx;

    const reduziert = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    let groesse = 0;
    let dpr = 1;

    const anpassen = () => {
      const rect = huelle.getBoundingClientRect();
      const s = Math.max(120, Math.floor(Math.min(rect.width, rect.height)));
      dpr = Math.min(2, window.devicePixelRatio || 1);
      if (s === groesse && canvas.width === Math.round(s * dpr)) return;
      groesse = s;
      canvas.width = Math.round(s * dpr);
      canvas.height = Math.round(s * dpr);
      canvas.style.width = `${s}px`;
      canvas.style.height = `${s}px`;
      if (reduziert) zeichnen(performance.now());
    };

    const partikel: Partikel[] = Array.from({ length: 64 }, () => ({
      r: 0.38 + Math.random() * 0.7,
      w: Math.random() * Math.PI * 2,
      v: (Math.random() - 0.5) * 0.12,
      g: 0.6 + Math.random() * 1.4,
      p: Math.random() * Math.PI * 2,
    }));

    // geglättete Werte
    const ist: Ziel & { pegel: number; warn: number } = { ...ZIELE.bereit, pegel: 0, warn: 0 };
    let winkelSeg = 0;
    let winkelTicks = 0;
    let winkelInnen = 0;
    let orbitWinkel = 0;
    let zuletzt = performance.now();
    let raf = 0;

    function zeichnen(jetzt: number) {
      const dt = Math.min(0.05, (jetzt - zuletzt) / 1000);
      zuletzt = jetzt;
      const st = useJarvis.getState();
      const basis = ZIELE[st.zustand] ?? ZIELE.bereit;
      // Ohne Kern: gedimmt und fast still.
      const ziel = st.verbindung === 'offen' ? basis : { ...ZIELE.bereit, energie: 0.28, drehung: 0.04, atmen: 0.4 };
      const k = reduziert ? 1 : 1 - Math.exp(-dt * 4);
      ist.energie += (ziel.energie - ist.energie) * k;
      ist.drehung += (ziel.drehung - ist.drehung) * (reduziert ? 1 : 1 - Math.exp(-dt * 2.5));
      ist.wellen += (ziel.wellen - ist.wellen) * k;
      ist.orbit += (ziel.orbit - ist.orbit) * k;
      ist.atmen += (ziel.atmen - ist.atmen) * k;
      ist.warn += ((st.freigaben.length > 0 ? 1 : 0) - ist.warn) * k;
      const pegelZiel = st.zustand === 'hoert' || st.zustand === 'spricht' ? st.pegel : 0;
      ist.pegel += (pegelZiel - ist.pegel) * (reduziert ? 1 : 1 - Math.exp(-dt * 14));

      if (!reduziert) {
        winkelSeg += ist.drehung * dt;
        winkelTicks -= (0.03 + ist.drehung * 0.08) * dt;
        winkelInnen -= (0.2 + ist.drehung * 0.6) * dt;
        orbitWinkel += 1.4 * dt;
      }
      const t = reduziert ? 0 : jetzt / 1000;

      const W = groesse * dpr;
      const R = (W / 2) * 0.9;
      const cx = W / 2;
      const cy = W / 2;
      const farbe = mix(CYAN, WARN, ist.warn);
      const hell = mix(EIS, [255, 214, 190], ist.warn);
      const atem = 0.5 + 0.5 * Math.sin(t * ((Math.PI * 2) / 4.2));
      const puls = ist.pegel;
      const skal = 1 + puls * 0.06 + atem * 0.012 * ist.atmen;
      const E = ist.energie;

      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, W, W);
      c.globalCompositeOperation = 'lighter';
      c.lineCap = 'butt';

      // Aura
      const aura = c.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.1);
      aura.addColorStop(0, rgba(farbe, 0.22 * E + puls * 0.14));
      aura.addColorStop(0.35, rgba(farbe, 0.09 * E));
      aura.addColorStop(0.7, rgba(farbe, 0.025 * E));
      aura.addColorStop(1, rgba(farbe, 0));
      c.fillStyle = aura;
      c.fillRect(0, 0, W, W);

      c.save();
      c.translate(cx, cy);
      c.scale(skal, skal);

      // Partikel
      for (const p of partikel) {
        if (!reduziert) {
          p.w += (p.v + (st.zustand === 'denkt' ? 0.25 : 0) * Math.sign(p.v || 1)) * dt;
          if (st.zustand === 'denkt') {
            p.r -= dt * 0.05;
            if (p.r < 0.36) p.r = 1.08;
          }
        }
        const fl = 0.5 + 0.5 * Math.sin(t * p.g + p.p);
        const rr = p.r * R * (1 + puls * 0.12);
        c.fillStyle = rgba(farbe, (0.15 + fl * 0.45) * E * (p.r > 1 ? 1.08 - (p.r - 1) * 8 : 1));
        const g = (0.6 + fl * 0.8) * dpr;
        c.fillRect(Math.cos(p.w) * rr - g / 2, Math.sin(p.w) * rr - g / 2, g, g);
      }

      // Äußerer Tick-Ring
      const tickN = 180;
      const rT = R * 0.97;
      c.lineWidth = Math.max(1, dpr);
      for (let i = 0; i < tickN; i++) {
        const w = winkelTicks + (i / tickN) * Math.PI * 2;
        const lang = i % 15 === 0;
        const welle = puls * (0.5 + 0.5 * Math.sin(i * 0.7 + t * 9)) * R * 0.06;
        const len = (lang ? R * 0.05 : R * 0.022) + welle;
        const a = (lang ? 0.85 : 0.42) * E + welle / (R * 0.06) * 0.3;
        c.strokeStyle = rgba(farbe, a);
        c.beginPath();
        c.moveTo(Math.cos(w) * rT, Math.sin(w) * rT);
        c.lineTo(Math.cos(w) * (rT - len), Math.sin(w) * (rT - len));
        c.stroke();
      }

      // Halo-Ring (weicher Schein außen)
      for (const [breite, alpha] of [
        [R * 0.06, 0.05],
        [R * 0.02, 0.12],
      ] as const) {
        c.strokeStyle = rgba(farbe, alpha * E + puls * 0.06);
        c.lineWidth = breite;
        c.beginPath();
        c.arc(0, 0, R * 0.885, 0, Math.PI * 2);
        c.stroke();
      }

      // Dünner Kreis
      c.strokeStyle = rgba(farbe, 0.4 * E);
      c.lineWidth = dpr;
      c.beginPath();
      c.arc(0, 0, R * 0.885, 0, Math.PI * 2);
      c.stroke();

      // Segmentring (dick, mit Glow)
      const rS = R * (0.8 + puls * 0.03);
      const segmente: [number, number][] = [
        [0, 0.62],
        [0.78, 1.55],
        [1.72, 2.05],
        [2.25, 3.6],
        [3.78, 4.1],
        [4.3, 5.6],
        [5.75, 6.05],
      ];
      for (const lage of [0, 1]) {
        c.lineWidth = lage === 0 ? R * 0.075 : R * 0.03;
        c.strokeStyle = rgba(farbe, lage === 0 ? 0.1 * E : 0.78 * E + puls * 0.3);
        for (const [a, b] of segmente) {
          c.beginPath();
          c.arc(0, 0, rS, winkelSeg + a, winkelSeg + b);
          c.stroke();
        }
      }
      // feine Gegenläufer
      c.lineWidth = Math.max(1, dpr * 1.2);
      c.strokeStyle = rgba(hell, 0.7 * E);
      for (let i = 0; i < 3; i++) {
        const s0 = -winkelSeg * 1.6 + (i * Math.PI * 2) / 3;
        c.beginPath();
        c.arc(0, 0, R * 0.735, s0, s0 + 0.5 + (st.zustand === 'denkt' ? 0.4 : 0));
        c.stroke();
      }

      // Gestrichelter Innenring
      c.save();
      c.rotate(winkelInnen);
      c.setLineDash([R * 0.012, R * 0.028]);
      c.strokeStyle = rgba(farbe, 0.6 * E);
      c.lineWidth = R * 0.018;
      c.beginPath();
      c.arc(0, 0, R * 0.64, 0, Math.PI * 2);
      c.stroke();
      c.setLineDash([]);
      c.restore();

      // Innere Zellen (24 Segmente, Muster wandert beim Denken)
      const zellen = 24;
      const rZ = R * 0.53;
      c.lineWidth = R * 0.05;
      for (let i = 0; i < zellen; i++) {
        const w0 = (i / zellen) * Math.PI * 2 - Math.PI / 2;
        const phase = st.zustand === 'denkt' ? Math.floor(t * 14) : Math.floor(t * 1.2);
        const an = (i + phase) % 6 < 4;
        const pegelAn = i / zellen < 0.15 + puls * 0.85;
        const a = (an ? 0.6 : 0.16) * E + (st.zustand === 'hoert' && pegelAn ? 0.4 : 0);
        c.strokeStyle = rgba(farbe, a);
        c.beginPath();
        c.arc(0, 0, rZ, w0 + 0.03, w0 + (Math.PI * 2) / zellen - 0.03);
        c.stroke();
      }

      // Orbit-Punkte (Werkzeuge laufen)
      if (ist.orbit > 0.01) {
        const laufend = st.werkzeuge.filter((w) => w.ende === null).length;
        const n = Math.max(3, Math.min(6, laufend + 2));
        for (let i = 0; i < n; i++) {
          const rr = R * (0.885 + (i % 2) * 0.04);
          const w = orbitWinkel * (1 + (i % 3) * 0.25) + (i * Math.PI * 2) / n;
          c.lineWidth = R * 0.012;
          c.strokeStyle = rgba(hell, 0.35 * ist.orbit);
          c.beginPath();
          c.arc(0, 0, rr, w - 0.55, w);
          c.stroke();
          const x = Math.cos(w) * rr;
          const y = Math.sin(w) * rr;
          const pg = c.createRadialGradient(x, y, 0, x, y, R * 0.05);
          pg.addColorStop(0, rgba(hell, 0.95 * ist.orbit));
          pg.addColorStop(1, rgba(farbe, 0));
          c.fillStyle = pg;
          c.beginPath();
          c.arc(x, y, R * 0.05, 0, Math.PI * 2);
          c.fill();
        }
      }

      // Kern
      const rK = R * (0.3 + puls * 0.05 + atem * 0.015 * ist.atmen);
      const kern = c.createRadialGradient(0, 0, 0, 0, 0, rK * 1.25);
      kern.addColorStop(0, rgba(hell, 1 * E));
      kern.addColorStop(0.2, rgba(hell, 0.75 * E));
      kern.addColorStop(0.5, rgba(farbe, 0.32 * E));
      kern.addColorStop(0.8, rgba(farbe, 0.08 * E));
      kern.addColorStop(1, rgba(farbe, 0));
      c.fillStyle = kern;
      c.beginPath();
      c.arc(0, 0, rK * 1.25, 0, Math.PI * 2);
      c.fill();

      // Speichen im Kern (langsam drehend)
      c.save();
      c.rotate(-winkelInnen * 0.5);
      c.lineWidth = Math.max(1, dpr);
      for (let i = 0; i < 12; i++) {
        const w = (i / 12) * Math.PI * 2;
        c.strokeStyle = rgba(hell, (i % 3 === 0 ? 0.35 : 0.14) * E);
        c.beginPath();
        c.moveTo(Math.cos(w) * R * 0.13, Math.sin(w) * R * 0.13);
        c.lineTo(Math.cos(w) * R * (i % 3 === 0 ? 0.33 : 0.27), Math.sin(w) * R * (i % 3 === 0 ? 0.33 : 0.27));
        c.stroke();
      }
      c.restore();

      // Kernring
      c.strokeStyle = rgba(hell, 0.65 * E);
      c.lineWidth = Math.max(1, dpr * 1.5);
      c.beginPath();
      c.arc(0, 0, R * 0.36, 0, Math.PI * 2);
      c.stroke();

      // Wellenform beim Sprechen
      if (ist.wellen > 0.01) {
        const punkte = 120;
        for (const [lage, faktor] of [
          [0, 1],
          [1, -0.7],
        ] as const) {
          c.beginPath();
          for (let i = 0; i <= punkte; i++) {
            const w = (i / punkte) * Math.PI * 2;
            const amp =
              (Math.sin(w * 6 + t * 7 * faktor) * 0.5 +
                Math.sin(w * 11 - t * 5) * 0.3 +
                Math.sin(w * 3 + t * 3) * 0.2) *
              (0.25 + puls * 0.9) *
              ist.wellen;
            const rr = R * (0.24 + amp * 0.09 * (lage === 0 ? 1 : 0.6));
            const x = Math.cos(w) * rr;
            const y = Math.sin(w) * rr;
            if (i === 0) c.moveTo(x, y);
            else c.lineTo(x, y);
          }
          c.strokeStyle = rgba(lage === 0 ? hell : farbe, (lage === 0 ? 0.9 : 0.5) * ist.wellen);
          c.lineWidth = Math.max(1, dpr * (lage === 0 ? 1.6 : 1));
          c.stroke();
        }
      }

      // Zentrum
      c.fillStyle = rgba([255, 255, 255], 0.85 * E);
      c.beginPath();
      c.arc(0, 0, R * 0.045 * (1 + puls * 0.6), 0, Math.PI * 2);
      c.fill();

      c.restore();
      c.globalCompositeOperation = 'source-over';
    }

    const schleife = (jetzt: number) => {
      zeichnen(jetzt);
      raf = requestAnimationFrame(schleife);
    };
    const starten = () => {
      if (raf || reduziert || !aktiv || document.hidden) return;
      zuletzt = performance.now();
      raf = requestAnimationFrame(schleife);
    };
    const anhalten = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };
    const sichtbarkeit = () => (document.hidden ? anhalten() : starten());

    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(anpassen) : null;
    ro?.observe(huelle);
    anpassen();
    document.addEventListener('visibilitychange', sichtbarkeit);

    let abmelden: (() => void) | null = null;
    if (reduziert) {
      // Ohne Bewegung: nur bei Änderungen neu zeichnen.
      zeichnen(performance.now());
      abmelden = useJarvis.subscribe((s, v) => {
        if (s.zustand !== v.zustand || s.verbindung !== v.verbindung || s.freigaben !== v.freigaben || Math.abs(s.pegel - v.pegel) > 0.1)
          zeichnen(performance.now());
      });
    } else if (aktiv) {
      starten();
    } else {
      zeichnen(performance.now());
    }

    return () => {
      anhalten();
      ro?.disconnect();
      abmelden?.();
      document.removeEventListener('visibilitychange', sichtbarkeit);
    };
  }, [aktiv]);

  return (
    <div ref={huelleRef} className={`orb ${className ?? ''}`} aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  );
}
