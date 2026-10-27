import { useEffect, useRef } from 'react';
import { useName } from '../state/store';

const DAUER = 1400;

/** Kurzer Start-Ton, synthetisiert (keine Audiodatei). Scheitert still, wenn der Browser blockiert. */
function startTon(): void {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    if (ctx.state === 'suspended') {
      void ctx.close();
      return;
    }
    const jetzt = ctx.currentTime;
    const gesamt = ctx.createGain();
    gesamt.gain.value = 0.06;
    gesamt.connect(ctx.destination);
    [
      [440, 0],
      [660, 0.12],
      [880, 0.24],
    ].forEach(([f, t]) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.setValueAtTime(f!, jetzt + t!);
      g.gain.setValueAtTime(0, jetzt + t!);
      g.gain.linearRampToValueAtTime(1, jetzt + t! + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, jetzt + t! + 0.6);
      o.connect(g).connect(gesamt);
      o.start(jetzt + t!);
      o.stop(jetzt + t! + 0.65);
    });
    setTimeout(() => void ctx.close(), 1200);
  } catch {
    /* kein Ton */
  }
}

export function Boot({ onFertig }: { onFertig: () => void }) {
  const name = useName();
  const fertig = useRef(false);
  useEffect(() => {
    const reduziert = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    const ende = () => {
      if (fertig.current) return;
      fertig.current = true;
      onFertig();
    };
    if (!reduziert) startTon();
    const t = setTimeout(ende, reduziert ? 300 : DAUER);
    const taste = () => ende();
    window.addEventListener('keydown', taste);
    window.addEventListener('pointerdown', taste);
    return () => {
      clearTimeout(t);
      window.removeEventListener('keydown', taste);
      window.removeEventListener('pointerdown', taste);
    };
  }, [onFertig]);

  return (
    <div className="boot" role="presentation" aria-hidden="true">
      <div className="boot-ringe">
        <span />
        <span />
        <span />
      </div>
      <div className="boot-wort">{name}</div>
      <div className="boot-zeile">
        <span className="boot-balken" />
      </div>
      <div className="boot-hinweis">Klicken oder Taste drücken zum Überspringen</div>
    </div>
  );
}
