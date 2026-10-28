// Kleine Beispielfläche (Kennzahl, Badge, Text, Button) zur Vorschau eines Stils.
import type { BuehnenKomponente, StilWerte } from '../../api/types';
import { FlaechenAnsicht } from '../../buehne/renderer';

const KOMPONENTEN: Record<string, BuehnenKomponente> = Object.fromEntries(
  (
    [
      { id: 'root', component: 'Column', children: ['kopf', 'zahlen', 'text', 'knoepfe'] },
      { id: 'kopf', component: 'Row', children: ['titel', 'status'], justify: 'spaceBetween', align: 'center' },
      { id: 'titel', component: 'Text', text: 'Hafenweg 3', variant: 'h4' },
      { id: 'status', component: 'Badge', text: 'Neu', ton: 'ok' },
      { id: 'zahlen', component: 'Row', children: ['preis', 'flaeche'], gap: 24 },
      { id: 'preis', component: 'Kennzahl', wert: { call: 'formatCurrency', args: { value: 425000, currency: 'EUR', maximumFractionDigits: 0 } }, label: 'Kaufpreis' },
      { id: 'flaeche', component: 'Kennzahl', wert: 92, einheit: 'm²', label: 'Wohnfläche', trend: 3 },
      { id: 'text', component: 'Text', text: 'Helle 3-Zimmer-Wohnung mit **Elbblick**.', variant: 'body' },
      { id: 'knoepfe', component: 'Row', children: ['expose', 'notiz'] },
      { id: 'expose', component: 'Button', text: 'Exposé', variant: 'primary', icon: 'open_in_new' },
      { id: 'notiz', component: 'Button', text: 'Notiz', icon: 'edit' },
    ] as BuehnenKomponente[]
  ).map((k) => [k.id, k]),
);

export function StilVorschau({ werte, name }: { werte: StilWerte; name: string }) {
  return (
    <div className="stil-vorschau" aria-label={`Vorschau ${name}`} role="group">
      <FlaechenAnsicht surfaceId="vorschau" komponenten={KOMPONENTEN} daten={{}} werte={werte} vorschau />
    </div>
  );
}
