// Schnellaktionen der Bühne: Knöpfe unter der Reiterzeile. Bei offener Fläche nur die Sichten derselben App
// (der Kern liefert `varianten` je Vorlage schon app-bezogen: gleiche Vorlage zuerst, dann die übrigen Sichten der
// App – eine Wetter-Fläche zeigt nur Wetter, eine GG-Fläche nur GG). Ohne Fläche die globalen Schnellaktionen.
import { api } from '../api/rest';
import type { Schnellaktion } from '../api/types';
import { useBuehne } from '../buehne/store';
import { useJarvis } from '../state/store';

export const MAX_SCHNELL = 10;

export interface SchnellKnopf { aktion: Schnellaktion; an: boolean }

/** Knöpfe: bei offener Fläche nur deren App-Varianten (aktive Sicht markiert), sonst die globalen Schnellaktionen; gleiche `id` nur einmal. */
export function schnellKnoepfe(
  varianten: Schnellaktion[],
  schnell: Schnellaktion[],
  aktiverTitel: string | null,
  flaecheOffen = aktiverTitel !== null,
): SchnellKnopf[] {
  const gesehen = new Set<string>();
  const aus: SchnellKnopf[] = [];
  const liste = flaecheOffen ? varianten : schnell;
  for (const a of liste) {
    if (gesehen.has(a.id) || aus.length >= MAX_SCHNELL) continue;
    gesehen.add(a.id);
    aus.push({ aktion: a, an: flaecheOffen && a.titel === aktiverTitel });
  }
  return aus;
}

/** Schnellaktion ausführen: über den WebSocket, sonst per REST (Fehler als Hinweis). */
export function schnellAusfuehren(a: Schnellaktion) {
  const nachricht = { vorlage: a.vorlage, argumente: a.argumente, titel: a.titel };
  const b = useBuehne.getState();
  if (b.eingeklappt) b.setEingeklappt(false);
  if (useJarvis.getState().senden({ typ: 'buehne_erneut', ...nachricht })) return;
  api.buehneErneut(nachricht).catch((e: Error) =>
    useJarvis.getState().verarbeiten({ typ: 'lokal_hinweis', text: `Schnellaktion „${a.titel}“ fehlgeschlagen: ${e.message}` }),
  );
}

export function BuehneSchnell({ vorlage, titel }: { vorlage: string | null; titel: string | null }) {
  const schnell = useBuehne((s) => s.schnellaktionen);
  const flaecheOffen = useBuehne((s) => s.reihenfolge.length > 0);
  const varianten = useBuehne((s) => (vorlage ? s.varianten[vorlage] : undefined));
  const knoepfe = schnellKnoepfe(varianten ?? [], schnell, titel, flaecheOffen);
  if (knoepfe.length === 0) return null;
  return (
    <div className="buehne-schnell" role="group" aria-label="Schnellaktionen">
      {knoepfe.map(({ aktion, an }) => (
        <button
          key={aktion.id}
          type="button"
          className={`buehne-chip ${an ? 'an' : ''}`}
          aria-label={`Schnellaktion: ${aktion.titel}`}
          aria-pressed={an || undefined}
          title={aktion.titel}
          onClick={() => schnellAusfuehren(aktion)}
        >
          {aktion.titel}
        </button>
      ))}
    </div>
  );
}
