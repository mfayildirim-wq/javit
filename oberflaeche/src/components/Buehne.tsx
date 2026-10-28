// Bühne über dem Gespräch: Reiter je Fläche (Schließen, Stil-Menü), Inhalt, ziehbarer Teiler.
import { useEffect, useRef, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { ChevronDown, ChevronUp, X } from 'lucide-react';
import { api } from '../api/rest';
import { Flaeche } from '../buehne/renderer';
import { useBuehne } from '../buehne/store';
import { useJarvis } from '../state/store';

const SCHRITT = 0.05;

function hinweis(text: string) {
  useJarvis.getState().verarbeiten({ typ: 'lokal_hinweis', text });
}

function StilMenue({ surfaceId }: { surfaceId: string }) {
  const stil = useBuehne((s) => s.flaechen[surfaceId]?.stil ?? '');
  const vorlage = useBuehne((s) => s.flaechen[surfaceId]?.vorlage ?? null);
  const stile = useBuehne((s) => s.stile);
  const liste = Object.values(stile).sort((a, b) => a.name.localeCompare(b.name, 'de'));
  const waehlen = async (neu: string) => {
    useBuehne.getState().stilSetzen(surfaceId, neu);
    // createSurface nennt die Vorlage nicht immer – dann im Stand des Kerns nachschlagen.
    let kennung = vorlage;
    if (!kennung) {
      try {
        const stand = await api.buehne();
        kennung = stand?.flaechen?.find((f) => f.surfaceId === surfaceId)?.vorlage ?? null;
        if (kennung) useBuehne.getState().vorlageSetzen(surfaceId, kennung);
      } catch {
        kennung = null;
      }
    }
    if (kennung) api.buehneVorlageAendern(kennung, { stil: neu }).catch((e: Error) => hinweis(`Stil nicht gespeichert: ${e.message}`));
  };
  return (
    <select className="buehne-stil" aria-label="Stil der Fläche" value={stil} onChange={(e) => void waehlen(e.target.value)}>
      {!stile[stil] && <option value={stil}>{stil || 'Standard'}</option>}
      {liste.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name}
        </option>
      ))}
    </select>
  );
}

function Teiler() {
  const hoehe = useBuehne((s) => s.hoehe);
  const ref = useRef<HTMLDivElement>(null);
  const abmelden = useRef<(() => void) | null>(null);
  useEffect(() => () => abmelden.current?.(), []);

  const ziehen = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const behaelter = ref.current?.closest('.konsole') as HTMLElement | null;
    if (!behaelter) return;
    const bewegen = (ev: PointerEvent | MouseEvent) => {
      const r = behaelter.getBoundingClientRect();
      if (r.height > 0) useBuehne.getState().hoeheSetzen((ev.clientY - r.top) / r.height);
    };
    const ende = () => abmelden.current?.();
    window.addEventListener('pointermove', bewegen);
    window.addEventListener('pointerup', ende);
    window.addEventListener('pointercancel', ende);
    abmelden.current?.();
    abmelden.current = () => {
      window.removeEventListener('pointermove', bewegen);
      window.removeEventListener('pointerup', ende);
      window.removeEventListener('pointercancel', ende);
      abmelden.current = null;
    };
  };

  const tasten = (e: KeyboardEvent) => {
    const st = useBuehne.getState();
    if (e.key === 'ArrowDown') st.hoeheSetzen(st.hoehe + SCHRITT);
    else if (e.key === 'ArrowUp') st.hoeheSetzen(st.hoehe - SCHRITT);
    else return;
    e.preventDefault();
  };

  return (
    <div
      ref={ref}
      className="buehne-teiler"
      role="separator"
      aria-orientation="horizontal"
      aria-label="Höhe der Bühne"
      aria-valuemin={20}
      aria-valuemax={80}
      aria-valuenow={Math.round(hoehe * 100)}
      tabIndex={0}
      onPointerDown={ziehen}
      onKeyDown={tasten}
    />
  );
}

export function Buehne() {
  const reihenfolge = useBuehne((s) => s.reihenfolge);
  const flaechen = useBuehne((s) => s.flaechen);
  const aktiv = useBuehne((s) => s.aktiv);
  const hoehe = useBuehne((s) => s.hoehe);
  const eingeklappt = useBuehne((s) => s.eingeklappt);
  const stileLeer = useBuehne((s) => Object.keys(s.stile).length === 0);

  useEffect(() => {
    if (stileLeer) api.buehneStile().then((l) => useBuehne.getState().stileSetzen(l), () => undefined);
  }, [stileLeer]);

  if (reihenfolge.length === 0) return null;
  const aktuell = aktiv && flaechen[aktiv] ? aktiv : reihenfolge[0]!;

  const schliessen = (id: string) => {
    useBuehne.getState().flaecheEntfernen(id);
    api.buehneFlaecheSchliessen(id).catch((e: Error) => hinweis(`Fläche nicht geschlossen: ${e.message}`));
  };

  return (
    <>
      <section className={`buehne-oben ${eingeklappt ? 'eingeklappt' : ''}`} aria-label="Bühne" style={eingeklappt ? undefined : { flexBasis: `${Math.round(hoehe * 100)}%` }}>
        <div className="buehne-kopf">
          <div className="buehne-reiter" role="tablist" aria-label="Flächen">
            {reihenfolge.map((id) => {
              const titel = flaechen[id]?.titel ?? id;
              return (
                <div key={id} className={`buehne-reiter-eintrag ${id === aktuell ? 'an' : ''}`}>
                  <button
                    type="button"
                    role="tab"
                    id={`buehne-reiter-${id}`}
                    aria-selected={id === aktuell}
                    aria-controls="buehne-inhalt"
                    className="buehne-reiter-knopf"
                    onClick={() => {
                      useBuehne.getState().aktivSetzen(id);
                      if (eingeklappt) useBuehne.getState().setEingeklappt(false);
                    }}
                  >
                    {titel}
                  </button>
                  <button type="button" className="buehne-schliessen" aria-label={`Fläche „${titel}“ schließen`} title="Schließen" onClick={() => schliessen(id)}>
                    <X size={13} aria-hidden="true" />
                  </button>
                </div>
              );
            })}
          </div>
          <div className="buehne-werkzeuge">
            {!eingeklappt && <StilMenue surfaceId={aktuell} />}
            <button
              type="button"
              className="buehne-klappe"
              aria-label={eingeklappt ? 'Bühne ausklappen' : 'Bühne einklappen'}
              title={eingeklappt ? 'Ausklappen' : 'Einklappen'}
              onClick={() => useBuehne.getState().setEingeklappt(!eingeklappt)}
            >
              {eingeklappt ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronUp size={15} aria-hidden="true" />}
            </button>
          </div>
        </div>
        {!eingeklappt && (
          <div className="buehne-inhalt" id="buehne-inhalt" role="tabpanel" aria-labelledby={`buehne-reiter-${aktuell}`}>
            <Flaeche surfaceId={aktuell} />
          </div>
        )}
      </section>
      {!eingeklappt && <Teiler />}
    </>
  );
}
