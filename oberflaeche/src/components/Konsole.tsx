import { useEffect, useRef } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Orb } from './Orb';
import { Composer } from './Composer';
import { Buehne } from './Buehne';
import { useBuehne } from '../buehne/store';
import { useJarvis, useName, useWeckwort } from '../state/store';
import { ZUSTAND_TEXT } from '../lib/format';
import type { Nachricht } from '../state/reducer';

function ZustandsAnzeige() {
  const zustand = useJarvis((s) => s.zustand);
  // Primitive Rückgabe (string), damit der Selektor stabil bleibt.
  const laufend = useJarvis((s) =>
    [...new Set(s.werkzeuge.filter((w) => w.ende === null).map((w) => w.name))].join(', '),
  );
  const freigabe = useJarvis((s) => s.freigaben.length > 0);
  const stimmeAn = useJarvis((s) => s.status?.stimme.aktiv ?? false);
  const verbunden = useJarvis((s) => s.verbindung === 'offen');
  const name = useName();
  const weckwort = useWeckwort();
  let zusatz = '';
  if (!verbunden)
    return (
      <div className="zustand z-offline" role="status" aria-live="polite">
        <span className="zustand-wort">Offline</span>
        <span className="zustand-zusatz">Warte auf den Kern von {name}</span>
      </div>
    );
  if (freigabe) zusatz = 'wartet auf Ihre Freigabe';
  else if (zustand === 'arbeitet' && laufend) zusatz = laufend;
  else if (zustand === 'bereit') zusatz = stimmeAn ? `Sagen Sie „${weckwort}“ oder tippen Sie unten` : 'Tippen Sie unten oder halten Sie die Leertaste';
  return (
    <div className={`zustand z-${zustand} ${freigabe ? 'z-warn' : ''}`} role="status" aria-live="polite">
      <span className="zustand-wort">{freigabe ? 'Freigabe nötig' : ZUSTAND_TEXT[zustand]}</span>
      {zusatz && <span className="zustand-zusatz">{zusatz}</span>}
    </div>
  );
}

const sichereLinks = {
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

function Beitrag({ n, aktiv }: { n: Nachricht; aktiv: boolean }) {
  const name = useName();
  if (n.rolle === 'nutzer') {
    return (
      <div className="beitrag nutzer">
        <span className="sprecher">Sie</span>
        <p>{n.text}</p>
      </div>
    );
  }
  return (
    <div className={`beitrag jarvis ${aktiv ? 'aktiv' : ''} ${n.fertig ? '' : 'streamt'}`}>
      <span className="sprecher">{name}</span>
      <div className="md">
        <Markdown remarkPlugins={[remarkGfm]} skipHtml components={sichereLinks}>
          {n.text || ' '}
        </Markdown>
        {!n.fertig && <span className="cursor" aria-hidden="true" />}
      </div>
    </div>
  );
}

export function Konsole({ aktiv }: { aktiv: boolean }) {
  const nachrichten = useJarvis((s) => s.nachrichten);
  const transkript = useJarvis((s) => s.transkript);
  const zustand = useJarvis((s) => s.zustand);
  const ansicht = useJarvis((s) => s.ansicht);
  const name = useName();
  const buehneOffen = useBuehne((s) => s.reihenfolge.length > 0);
  // Ohne Fläche, aber mit Schnellaktionen: nur die schmale Leiste, der Orb bleibt groß.
  const buehneLeiste = useBuehne((s) => s.reihenfolge.length === 0 && s.schnellaktionen.length > 0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const letzteJarvis = [...nachrichten].reverse().find((n) => n.rolle === 'jarvis')?.id;
  const letzterText = nachrichten[nachrichten.length - 1]?.text.length ?? 0;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [nachrichten.length, letzterText, transkript]);

  return (
    <section className={`konsole ${buehneOffen ? 'mit-buehne' : ''}`} hidden={ansicht !== 'konsole'} aria-label="Konsole">
      <div className={`orb-buehne ${buehneOffen ? 'klein' : ''}`}>
        <div className="fadenkreuz" aria-hidden="true" />
        <Orb aktiv={aktiv} />
        <ZustandsAnzeige />
      </div>
      {(buehneOffen || buehneLeiste) && <Buehne />}
      <div className="gespraech" ref={scrollRef} aria-live="polite">
        <div className="gespraech-spalte">
          {nachrichten.length === 0 && !transkript && (
            <p className="gespraech-leer">Guten Tag, hier ist {name}. Womit kann ich helfen?</p>
          )}
          {nachrichten.map((n) => (
            <Beitrag key={n.id} n={n} aktiv={n.id === letzteJarvis} />
          ))}
          {transkript && (
            <div className={`beitrag nutzer live ${zustand === 'hoert' ? 'hoert' : ''}`}>
              <span className="sprecher">Sie</span>
              <p>
                {transkript}
                <span className="cursor" aria-hidden="true" />
              </p>
            </div>
          )}
        </div>
      </div>
      <Composer />
    </section>
  );
}
