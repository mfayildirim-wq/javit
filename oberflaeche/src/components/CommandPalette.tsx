import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { MessageSquarePlus, Cpu, LayoutGrid, MessageSquare, Mic, Plug, Settings, Square, Volume2 } from 'lucide-react';
import { api } from '../api/rest';
import { neueUnterhaltung } from '../state/verbindung';
import type { ModellVorschlag } from '../api/types';
import { useJarvis, useName } from '../state/store';
import { statusLaden } from '../state/verbindung';

interface Befehl {
  id: string;
  titel: string;
  gruppe: string;
  icon: ReactNode;
  stichworte?: string;
  ausfuehren: () => void;
}

export function CommandPalette() {
  const offen = useJarvis((s) => s.paletteOffen);
  const setPalette = useJarvis((s) => s.setPalette);
  const name = useName();
  const [suche, setSuche] = useState('');
  const [aktiv, setAktiv] = useState(0);
  const [modelle, setModelle] = useState<ModellVorschlag[]>([]);
  const eingabe = useRef<HTMLInputElement>(null);
  const zurueck = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!offen) return;
    zurueck.current = document.activeElement as HTMLElement | null;
    setSuche('');
    setAktiv(0);
    requestAnimationFrame(() => eingabe.current?.focus());
    api
      .modelle()
      .then((m) => setModelle(m.vorschlaege))
      .catch(() => setModelle([]));
    return () => zurueck.current?.focus?.();
  }, [offen]);

  const befehle = useMemo<Befehl[]>(() => {
    const s = useJarvis.getState;
    const liste: Befehl[] = [
      { id: 'konsole', gruppe: 'Ansicht', titel: 'Konsole öffnen', icon: <LayoutGrid size={15} />, ausfuehren: () => s().setAnsicht('konsole') },
      {
        id: 'integrationen',
        gruppe: 'Ansicht',
        titel: 'Integration hinzufügen',
        stichworte: 'integrationen katalog app mcp openapi rest verbinden',
        icon: <Plug size={15} />,
        ausfuehren: () => s().setAnsicht('integrationen'),
      },
      {
        id: 'einstellungen',
        gruppe: 'Ansicht',
        titel: 'Einstellungen öffnen',
        stichworte: 'api schlüssel stimme persona gedächtnis',
        icon: <Settings size={15} />,
        ausfuehren: () => s().setAnsicht('einstellungen'),
      },
      {
        id: 'neue-unterhaltung',
        gruppe: 'Steuerung',
        titel: 'Neue Unterhaltung beginnen',
        stichworte: 'thema chat verlauf neu',
        icon: <MessageSquarePlus size={15} />,
        ausfuehren: () => {
          s().setPalette(false);
          void neueUnterhaltung();
        },
      },
      {
        id: 'mikro',
        gruppe: 'Steuerung',
        titel: 'Mikrofon an/aus',
        stichworte: 'stimme weckwort',
        icon: <Mic size={15} />,
        ausfuehren: () => {
          s().stimmeSetzen(!(s().status?.stimme.aktiv ?? false));
          s().setPalette(false);
        },
      },
      {
        id: 'vorlesen',
        gruppe: 'Steuerung',
        titel: 'Antworten vorlesen an/aus',
        stichworte: 'lautsprecher tts',
        icon: <Volume2 size={15} />,
        ausfuehren: () => {
          s().setVorlesen(!s().vorlesen);
          s().setPalette(false);
        },
      },
      {
        id: 'abbrechen',
        gruppe: 'Steuerung',
        titel: 'Laufende Arbeit abbrechen',
        stichworte: 'stopp',
        icon: <Square size={15} />,
        ausfuehren: () => {
          s().abbrechen();
          s().setPalette(false);
        },
      },
    ];
    for (const m of modelle) {
      liste.push({
        id: `modell-${m.id}`,
        gruppe: 'Modell wechseln',
        titel: `${m.name}${m.lokal ? ' (lokal)' : ''}`,
        stichworte: `modell ${m.id}`,
        icon: <Cpu size={15} />,
        ausfuehren: () => {
          s().setPalette(false);
          api
            .modellSetzen(m.id)
            .then(() => statusLaden())
            .catch((e: Error) => s().verarbeiten({ typ: 'lokal_hinweis', text: `Modellwechsel fehlgeschlagen: ${e.message}` }));
        },
      });
    }
    return liste;
  }, [modelle]);

  const q = suche.trim().toLowerCase();
  const treffer = q
    ? befehle.filter((b) => `${b.titel} ${b.gruppe} ${b.stichworte ?? ''}`.toLowerCase().includes(q))
    : befehle;
  const alle: Befehl[] = q
    ? [
        ...treffer,
        {
          id: 'fragen',
          gruppe: name,
          titel: `${name} fragen: „${suche.trim()}“`,
          icon: <MessageSquare size={15} />,
          ausfuehren: () => {
            useJarvis.getState().setAnsicht('konsole');
            useJarvis.getState().nachrichtSenden(suche.trim());
          },
        },
      ]
    : treffer;

  if (!offen) return null;

  const tasten = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setAktiv((a) => Math.min(alle.length - 1, a + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setAktiv((a) => Math.max(0, a - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      alle[aktiv]?.ausfuehren();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setPalette(false);
    }
  };

  let letzteGruppe = '';
  return (
    <div className="dialog-schleier" onMouseDown={(e) => e.target === e.currentTarget && setPalette(false)}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Befehlspalette" onKeyDown={tasten}>
        <input
          ref={eingabe}
          className="palette-suche"
          placeholder={`Befehl suchen oder ${name} etwas fragen …`}
          value={suche}
          onChange={(e) => {
            setSuche(e.target.value);
            setAktiv(0);
          }}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-liste"
          aria-activedescendant={alle[aktiv] ? `befehl-${alle[aktiv].id}` : undefined}
        />
        <ul className="palette-liste" id="palette-liste" role="listbox">
          {alle.map((b, i) => {
            const kopf = b.gruppe !== letzteGruppe ? b.gruppe : null;
            letzteGruppe = b.gruppe;
            return (
              <li key={b.id} role="presentation">
                {kopf && <div className="palette-gruppe">{kopf}</div>}
                <div
                  id={`befehl-${b.id}`}
                  role="option"
                  aria-selected={i === aktiv}
                  className={`palette-eintrag ${i === aktiv ? 'aktiv' : ''}`}
                  onMouseEnter={() => setAktiv(i)}
                  onClick={() => b.ausfuehren()}
                >
                  <span className="palette-icon" aria-hidden="true">
                    {b.icon}
                  </span>
                  {b.titel}
                </div>
              </li>
            );
          })}
          {alle.length === 0 && <li className="palette-leer">Kein Befehl gefunden.</li>}
        </ul>
        <div className="palette-fuss">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> auswählen
          </span>
          <span>
            <kbd>Enter</kbd> ausführen
          </span>
          <span>
            <kbd>Esc</kbd> schließen
          </span>
        </div>
      </div>
    </div>
  );
}
