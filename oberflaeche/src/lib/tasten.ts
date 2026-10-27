import { useEffect } from 'react';
import { istBeschaeftigt, useJarvis } from '../state/store';

export function istEingabeElement(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    tag === 'BUTTON' ||
    el.isContentEditable ||
    el.closest('[role="dialog"]') !== null
  );
}

/**
 * Globale Tastenkürzel:
 * - Cmd/Ctrl+K: Befehlspalette
 * - Esc: Freigabe ablehnen / Arbeit abbrechen / zurück zur Konsole
 * - Leertaste (außerhalb von Eingaben): Push-to-talk – sendet `zuhoeren` (einmal zuhören ohne Weckwort)
 */
export function useTastenkuerzel(): void {
  useEffect(() => {
    let leertasteAktiv = false;

    const unten = (e: KeyboardEvent) => {
      const s = useJarvis.getState();
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        s.setPalette(!s.paletteOffen);
        return;
      }
      if (e.key === 'Escape') {
        if (s.paletteOffen) return; // Palette schließt selbst
        const freigabe = s.freigaben[0];
        if (freigabe) {
          e.preventDefault();
          s.freigabeBeantworten(freigabe.id, false);
          return;
        }
        if (istBeschaeftigt(s)) {
          e.preventDefault();
          s.abbrechen();
          return;
        }
        if (s.ansicht !== 'konsole' && !istEingabeElement(e.target)) s.setAnsicht('konsole');
        return;
      }
      if (e.code === 'Space' && !e.repeat && !leertasteAktiv && !istEingabeElement(e.target) && !s.paletteOffen) {
        if (s.freigaben.length > 0 || s.ansicht !== 'konsole') return;
        e.preventDefault();
        leertasteAktiv = true;
        // Push-to-talk (VERTRAEGE.md): einmal zuhören ohne Weckwort; das Weckwort bleibt unverändert.
        if (s.senden({ typ: 'zuhoeren' })) {
          document.documentElement.dataset.ptt = '1';
        }
      } else if (e.code === 'Space' && leertasteAktiv) {
        e.preventDefault();
      }
    };

    const oben = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || !leertasteAktiv) return;
      e.preventDefault();
      leertasteAktiv = false;
      // Die Aufnahme endet serverseitig automatisch an der Sprechpause.
      delete document.documentElement.dataset.ptt;
    };

    window.addEventListener('keydown', unten);
    window.addEventListener('keyup', oben);
    return () => {
      window.removeEventListener('keydown', unten);
      window.removeEventListener('keyup', oben);
      delete document.documentElement.dataset.ptt;
    };
  }, []);
}
