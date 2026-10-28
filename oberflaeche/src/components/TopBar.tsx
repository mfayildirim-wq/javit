import { Command, MessageSquarePlus } from 'lucide-react';
import { useJarvis, useName, type Ansicht } from '../state/store';
import { neueUnterhaltung } from '../state/verbindung';

const TABS: { id: Ansicht; titel: string }[] = [
  { id: 'konsole', titel: 'Konsole' },
  { id: 'integrationen', titel: 'Integrationen' },
  { id: 'einstellungen', titel: 'Einstellungen' },
];

export function TopBar() {
  const ansicht = useJarvis((s) => s.ansicht);
  const setAnsicht = useJarvis((s) => s.setAnsicht);
  const setPalette = useJarvis((s) => s.setPalette);
  const verbindung = useJarvis((s) => s.verbindung);
  const unterhaltung = useJarvis((s) => s.unterhaltung);
  const name = useName();
  const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

  const verbText = verbindung === 'offen' ? 'Kern verbunden' : verbindung === 'verbinde' ? 'Verbinde …' : 'Kern getrennt';

  return (
    <header className="kopf">
      <div className="marke" aria-label={name}>
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
          <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="6 2.4" />
          <circle cx="16" cy="16" r="7.5" fill="none" stroke="currentColor" strokeWidth="1" opacity=".55" />
          <circle cx="16" cy="16" r="3" fill="currentColor" />
        </svg>
        <span className="marke-wort">{name}</span>
      </div>

      <nav className="reiter" role="tablist" aria-label="Ansicht">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={ansicht === t.id}
            className="reiter-knopf"
            onClick={() => setAnsicht(t.id)}
          >
            {t.titel}
          </button>
        ))}
      </nav>

      <div className="kopf-rechts">
        {unterhaltung && ansicht === 'konsole' && (
          <span className="unterhaltung-titel" title="Aktuelle Unterhaltung">{unterhaltung.titel}</span>
        )}
        <button className="palette-knopf neu-knopf" onClick={() => void neueUnterhaltung()} aria-label="Neue Unterhaltung" title="Neue Unterhaltung (Alt+N)">
          <MessageSquarePlus size={14} aria-hidden="true" />
          <span>Neu</span>
        </button>
        <button className="palette-knopf" onClick={() => setPalette(true)} aria-label="Befehlspalette öffnen">
          <Command size={14} aria-hidden="true" />
          <span>Befehle</span>
          <kbd>{mac ? '⌘' : 'Strg'} K</kbd>
        </button>
        <div className={`verbindung verbindung-${verbindung}`} role="status" aria-live="polite">
          <span className="verbindung-punkt" aria-hidden="true" />
          {verbText}
        </div>
      </div>
    </header>
  );
}
