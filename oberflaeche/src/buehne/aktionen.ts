// Aktionen der Bühne: event → buehne_aktion an den Kern; functionCall openUrl → nur https.
import { useJarvis } from '../state/store';
import { istHttps, wertAufloesen, type BindeKontext } from './binder';

export interface AktionsQuelle {
  surfaceId: string;
  /** ID der auslösenden Komponente. */
  quelle: string;
  ctx: BindeKontext;
  /** Zusätzliche Kontextwerte (Tabellenzeile `zeile`, Formularwerte `werte`). */
  zusatz?: Record<string, unknown>;
}

function istObjekt(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x);
}

/** Kontextwerte nur aus Literalen und Bindungen auflösen. */
export function kontextAufloesen(kontext: unknown, ctx: BindeKontext): Record<string, unknown> {
  const aus: Record<string, unknown> = {};
  if (!istObjekt(kontext)) return aus;
  for (const [schluessel, wert] of Object.entries(kontext)) aus[schluessel] = wertAufloesen(wert, ctx);
  return aus;
}

/** Führt eine Katalog-Aktion aus; gibt zurück, ob etwas ausgelöst wurde. */
export function aktionAusloesen(aktion: unknown, q: AktionsQuelle): boolean {
  if (!istObjekt(aktion)) return false;
  const st = useJarvis.getState();
  if (istObjekt(aktion.event) && typeof aktion.event.name === 'string') {
    const context = { ...kontextAufloesen(aktion.event.context, q.ctx), ...(q.zusatz ?? {}) };
    return st.senden({
      typ: 'buehne_aktion',
      name: aktion.event.name,
      surfaceId: q.surfaceId,
      sourceComponentId: q.quelle,
      timestamp: new Date().toISOString(),
      context,
    });
  }
  if (istObjekt(aktion.functionCall) && aktion.functionCall.call === 'openUrl') {
    const args = istObjekt(aktion.functionCall.args) ? aktion.functionCall.args : {};
    const url = wertAufloesen(args.url, q.ctx);
    if (!istHttps(url)) {
      st.verarbeiten({ typ: 'lokal_hinweis', text: 'Link nicht geöffnet: Die Bühne öffnet nur https-Adressen.' });
      return false;
    }
    window.open(url, '_blank', 'noopener,noreferrer');
    return true;
  }
  return false;
}
