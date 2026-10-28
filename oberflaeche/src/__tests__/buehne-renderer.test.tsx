import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Flaeche } from '../buehne/renderer';
import { useBuehne } from '../buehne/store';
import { useJarvis } from '../state/store';
import { anfangsZustand } from '../state/reducer';
import type { BuehnenKomponente, ClientNachricht } from '../api/types';

let gesendet: ClientNachricht[];

function zeige(komponenten: BuehnenKomponente[], daten: Record<string, unknown> = {}, stil = 'javit-dunkel') {
  act(() => {
    const b = useBuehne.getState();
    b.verarbeiten({ version: 'v0.9.1', createSurface: { surfaceId: 't', catalogId: 'jarvis:buehne/1', theme: { stil }, titel: 'Test' } });
    b.verarbeiten({ version: 'v0.9.1', updateComponents: { surfaceId: 't', components: komponenten } });
    b.verarbeiten({ version: 'v0.9.1', updateDataModel: { surfaceId: 't', path: '/', value: daten } });
  });
  return render(<Flaeche surfaceId="t" />);
}

const daten = () => useBuehne.getState().flaechen.t?.daten ?? {};
const aktionen = () => gesendet.filter((n) => n.typ === 'buehne_aktion');
const datenNachrichten = () => gesendet.filter((n) => n.typ === 'buehne_daten');

const IMMOBILIEN = {
  immobilien: [
    { id: 'hafenweg-3', titel: 'Hafenweg 3', preis: 425000, status: 'neu', zeit: '2026-10-28T14:05:00' },
    { id: 'elbchaussee', titel: 'Elbchaussee 1', preis: 1250000, status: 'reserviert', zeit: '2026-10-01T09:00:00' },
  ],
};

beforeEach(() => {
  gesendet = [];
  useBuehne.getState().zuruecksetzen();
  useJarvis.setState({
    ...anfangsZustand,
    verbindung: 'offen',
    sender: (n) => {
      gesendet.push(n);
      return true;
    },
  });
});
afterEach(() => vi.restoreAllMocks());

describe('Fläche', () => {
  it('puffert ohne root und zeigt einen Aufbau-Hinweis', () => {
    act(() => {
      useBuehne.getState().verarbeiten({ version: 'v0.9.1', createSurface: { surfaceId: 't', titel: 'T' } });
      useBuehne.getState().verarbeiten({ version: 'v0.9.1', updateComponents: { surfaceId: 't', components: [{ id: 'x', component: 'Text', text: 'Teil' }] } });
    });
    render(<Flaeche surfaceId="t" />);
    expect(screen.getByText(/wird aufgebaut/)).toBeInTheDocument();
    expect(screen.queryByText('Teil')).toBeNull();
  });

  it('setzt Schema und Stilvariablen am Container', () => {
    act(() =>
      useBuehne.getState().stileSetzen([
        {
          id: 'papier', name: 'Papier', quelle: { art: 'vordefiniert' }, vorlieben: { liste: 'kacheln', bildgroesse: 'mittel', kennzahlenOben: true },
          werte: { schema: 'hell', farben: { primaer: '#7a4a1f', akzent: '#b2622a', hintergrund: '#f8f3e8', flaeche: '#fffdf7', text: '#2b2117', dezent: '#7a6a58', ok: '#3d7a3a', warn: '#a86f00', fehler: '#a83232' }, schrift: { familie: 'Georgia, serif', basisgroesse: 15 }, rundung: 8, abstand: 14, dichte: 'normal', schatten: 'weich' },
        },
      ]),
    );
    const { container } = zeige([{ id: 'root', component: 'Text', text: 'Hallo' }], {}, 'papier');
    const f = container.querySelector('.buehne-flaeche') as HTMLElement;
    expect(f.dataset.schema).toBe('hell');
    expect(f.style.getPropertyValue('--b-primaer')).toBe('#7a4a1f');
    expect(f.style.getPropertyValue('--b-basis')).toBe('15px');
  });

  it('unbekannte Bausteine werden übersprungen, Zyklen enden an der Tiefengrenze', () => {
    zeige([
      { id: 'root', component: 'Column', children: ['boese', 'a'] },
      { id: 'boese', component: 'Skript', text: 'nein' },
      { id: 'a', component: 'Column', children: ['a'] },
    ]);
    expect(screen.queryByText('nein')).toBeNull();
  });
});

describe('Layout-Bausteine', () => {
  it('Column und Row ordnen Kinder an', () => {
    const { container } = zeige([
      { id: 'root', component: 'Column', children: ['titel', 'zeile'], gap: 8 },
      { id: 'titel', component: 'Text', text: 'Immobilien', variant: 'h2' },
      { id: 'zeile', component: 'Row', children: ['a', 'b'], justify: 'spaceBetween', wrap: true },
      { id: 'a', component: 'Text', text: 'links' },
      { id: 'b', component: 'Text', text: 'rechts' },
    ]);
    expect(screen.getByRole('heading', { level: 2, name: 'Immobilien' })).toBeInTheDocument();
    const reihe = container.querySelector('.b-row') as HTMLElement;
    expect(reihe).toHaveClass('b-justify-spaceBetween', 'b-wrap');
    expect(within(reihe).getByText('links')).toBeInTheDocument();
    expect((container.querySelector('.b-column') as HTMLElement).style.gap).toBe('8px');
  });

  it('Grid mit Template: je Element eine Karte mit relativem Datenkontext', () => {
    const { container } = zeige(
      [
        { id: 'root', component: 'Grid', spalten: 3, children: { path: '/immobilien', componentId: 'kachel' } },
        { id: 'kachel', component: 'Card', child: 'kachel_titel' },
        { id: 'kachel_titel', component: 'Text', text: { path: 'titel' } },
      ],
      IMMOBILIEN,
    );
    expect(container.querySelector('.b-grid')).toHaveClass('b-spalten-3');
    expect(container.querySelectorAll('.b-card')).toHaveLength(2);
    expect(screen.getByText('Hafenweg 3')).toBeInTheDocument();
    expect(screen.getByText('Elbchaussee 1')).toBeInTheDocument();
  });

  it('List rendert Listeneinträge (horizontal)', () => {
    zeige(
      [
        { id: 'root', component: 'List', direction: 'horizontal', children: { path: '/immobilien', componentId: 'zeile' } },
        { id: 'zeile', component: 'Text', text: { call: 'formatString', args: { value: '${titel} (${/immobilien/0/id})' } } },
      ],
      IMMOBILIEN,
    );
    const liste = screen.getByRole('list');
    expect(liste).toHaveClass('b-horizontal');
    expect(within(liste).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByText('Elbchaussee 1 (hafenweg-3)')).toBeInTheDocument();
  });

  it('Tabs wechseln den Inhalt', async () => {
    const u = userEvent.setup();
    zeige([
      { id: 'root', component: 'Tabs', titles: ['Aktiv', 'Archiv'], children: ['aktiv', 'archiv'] },
      { id: 'aktiv', component: 'Text', text: 'Aktive Objekte' },
      { id: 'archiv', component: 'Text', text: 'Archivierte Objekte' },
    ]);
    expect(screen.getByRole('tab', { name: 'Aktiv' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Aktive Objekte')).toBeInTheDocument();
    await u.click(screen.getByRole('tab', { name: 'Archiv' }));
    expect(screen.getByText('Archivierte Objekte')).toBeInTheDocument();
    expect(screen.queryByText('Aktive Objekte')).toBeNull();
  });

  it('Divider ist ein Trenner', () => {
    zeige([
      { id: 'root', component: 'Row', children: ['d'] },
      { id: 'd', component: 'Divider', axis: 'vertical' },
    ]);
    expect(screen.getByRole('separator')).toHaveAttribute('aria-orientation', 'vertical');
  });

  it('Card mit Aktion löst bei Klick und Enter aus', () => {
    zeige([
      { id: 'root', component: 'Card', child: 'c', action: { event: { name: 'karte_oeffnen', context: { ort: 'Hamburg' } } } },
      { id: 'c', component: 'Text', text: 'Karte' },
    ]);
    const karte = screen.getByRole('button', { name: /Karte/ });
    fireEvent.click(karte);
    fireEvent.keyDown(karte, { key: 'Enter' });
    expect(aktionen()).toHaveLength(2);
    expect(aktionen()[0]).toMatchObject({ name: 'karte_oeffnen', sourceComponentId: 'root', context: { ort: 'Hamburg' } });
  });
});

describe('Anzeige-Bausteine', () => {
  it('Text: Markdown ja, HTML nein, nur https-Links', () => {
    const { container } = zeige([
      { id: 'root', component: 'Text', text: '**fett** <img src="x" onerror="alert(1)"><script>alert(2)</script> [sicher](https://example.org) [unsicher](http://example.org)' },
    ]);
    expect(container.querySelector('strong')).toHaveTextContent('fett');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    const sicher = screen.getByRole('link', { name: 'sicher' });
    expect(sicher).toHaveAttribute('href', 'https://example.org');
    expect(sicher).toHaveAttribute('target', '_blank');
    expect(sicher).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.queryByRole('link', { name: 'unsicher' })).toBeNull();
    expect(screen.getByText('unsicher')).toBeInTheDocument();
  });

  it('Text: Varianten und Ton', () => {
    const { container } = zeige([
      { id: 'root', component: 'Column', children: ['a', 'b'] },
      { id: 'a', component: 'Text', text: 'Überschrift', variant: 'h4' },
      { id: 'b', component: 'Text', text: 'klein', variant: 'caption', ton: 'warn' },
    ]);
    expect(screen.getByRole('heading', { level: 4, name: 'Überschrift' })).toBeInTheDocument();
    expect(container.querySelector('.b-text-caption')).toHaveClass('b-ton-warn');
  });

  it('Image: https und data:image laden, http nicht', () => {
    const { container } = zeige(
      [
        { id: 'root', component: 'Column', children: ['a', 'b', 'c'] },
        { id: 'a', component: 'Image', url: { path: '/bild' }, alt: 'Haus', variant: 'mediumFeature', fit: 'cover' },
        { id: 'b', component: 'Image', url: 'http://unsicher.example/a.png', alt: 'Unsicher' },
        { id: 'c', component: 'Image', url: 'data:image/png;base64,iVBORw0KGgo=', alt: 'Daten' },
      ],
      { bild: 'https://bilder.example/haus.jpg' },
    );
    const bilder = container.querySelectorAll('img');
    expect(bilder).toHaveLength(2);
    expect(screen.getByRole('img', { name: 'Haus' })).toHaveAttribute('src', 'https://bilder.example/haus.jpg');
    expect(screen.getByRole('img', { name: 'Haus' })).toHaveClass('b-bild-mediumFeature', 'b-fit-cover');
    expect(container.querySelector('img[src^="http:"]')).toBeNull();
    expect(screen.getByRole('img', { name: /Unsicher/ })).toHaveClass('b-bild-platzhalter');
  });

  it('Icon: bekannte Namen als Symbol, unbekannte als Punkt', () => {
    const { container } = zeige([
      { id: 'root', component: 'Row', children: ['a', 'b'] },
      { id: 'a', component: 'Icon', name: 'home', ton: 'ok' },
      { id: 'b', component: 'Icon', name: 'gibts_nicht' },
    ]);
    const symbole = container.querySelectorAll('.b-icon');
    expect(symbole[0]?.querySelector('svg')).not.toBeNull();
    expect(symbole[0]).toHaveClass('b-ton-ok');
    expect(symbole[1]).toHaveTextContent('•');
  });

  it('Badge zeigt Text mit Ton', () => {
    zeige([{ id: 'root', component: 'Badge', text: { path: '/status' }, ton: 'info' }], { status: 'Neu' });
    expect(screen.getByText('Neu')).toHaveClass('b-badge', 'b-ton-info');
  });

  it('Kennzahl mit Währung, Einheit und Trend', () => {
    zeige(
      [
        { id: 'root', component: 'Row', children: ['a', 'b'] },
        { id: 'a', component: 'Kennzahl', wert: { call: 'formatCurrency', args: { value: { path: '/preis' }, currency: 'EUR' } }, label: 'Kaufpreis', trend: -2 },
        { id: 'b', component: 'Kennzahl', wert: 21, einheit: '°C', label: 'Temperatur', trend: '+1.5' },
      ],
      { preis: 425000 },
    );
    expect(screen.getByText(/425\.000,00/)).toBeInTheDocument();
    expect(screen.getByText('Kaufpreis')).toBeInTheDocument();
    expect(screen.getByText('°C')).toBeInTheDocument();
    expect(screen.getByLabelText('Trend −2')).toHaveClass('b-trend-runter');
    expect(screen.getByLabelText('Trend +1,5')).toHaveClass('b-trend-hoch');
  });

  it('Fortschritt als progressbar (0–1 → Prozent)', () => {
    zeige([{ id: 'root', component: 'Fortschritt', wert: { path: '/f' }, label: 'Erledigt' }], { f: 0.4 });
    const balken = screen.getByRole('progressbar', { name: 'Erledigt' });
    expect(balken).toHaveAttribute('aria-valuenow', '40');
    expect(screen.getByText('40 %')).toBeInTheDocument();
  });

  it('Tabelle formatiert Spalten und sendet die Zeilenaktion mit /zeile', () => {
    zeige(
      [
        {
          id: 'root', component: 'Tabelle', zeilen: { path: '/immobilien' },
          spalten: [
            { titel: 'Objekt', path: 'titel' },
            { titel: 'Preis', path: 'preis', format: 'waehrung' },
            { titel: 'Zeit', path: 'zeit', format: 'datum' },
            { titel: 'Status', path: 'status', format: 'badge' },
          ],
          zeilenAktion: { event: { name: 'objekt_oeffnen', context: { id: { path: 'id' } } } },
        },
      ],
      IMMOBILIEN,
    );
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Objekt', 'Preis', 'Zeit', 'Status']);
    const zeilen = screen.getAllByRole('row');
    expect(zeilen).toHaveLength(3);
    expect(within(zeilen[1]!).getByText(/425\.000/)).toBeInTheDocument();
    expect(within(zeilen[1]!).getByText('28.10.2026 14:05')).toBeInTheDocument();
    expect(within(zeilen[1]!).getByText('neu')).toHaveClass('b-badge');
    fireEvent.click(zeilen[2]!);
    expect(aktionen()[0]).toMatchObject({ name: 'objekt_oeffnen', surfaceId: 't', sourceComponentId: 'root', context: { id: 'elbchaussee', zeile: IMMOBILIEN.immobilien[1] } });
    fireEvent.keyDown(zeilen[1]!, { key: 'Enter' });
    expect(aktionen()[1]).toMatchObject({ context: { id: 'hafenweg-3' } });
  });

  it('Karte verlinkt auf OpenStreetMap (Adresse bzw. Koordinaten)', () => {
    zeige([
      { id: 'root', component: 'Column', children: ['a', 'b'] },
      { id: 'a', component: 'Karte', adresse: 'Hafenweg 3, 20457 Hamburg' },
      { id: 'b', component: 'Karte', lat: 53.55, lon: 9.99 },
    ]);
    const links = screen.getAllByRole('link');
    expect(links[0]).toHaveAttribute('href', 'https://www.openstreetmap.org/search?query=Hafenweg%203%2C%2020457%20Hamburg');
    expect(links[1]?.getAttribute('href')).toContain('mlat=53.55&mlon=9.99');
    expect(links[0]).toHaveAttribute('target', '_blank');
    expect(screen.getByText('Hafenweg 3, 20457 Hamburg')).toBeInTheDocument();
  });

  it('Diagramm: Balken, Linie und Kreis als eigenes SVG', () => {
    const werte = { v: [{ x: 'Mo', y: 3 }, { x: 'Di', y: 5 }, { x: 'Mi', y: 2 }] };
    const { container } = zeige(
      [
        { id: 'root', component: 'Column', children: ['a', 'b', 'c'] },
        { id: 'a', component: 'Diagramm', typ: 'balken', titel: 'Balken', serien: [{ name: 'Temp', path: '/v' }] },
        { id: 'b', component: 'Diagramm', typ: 'linie', titel: 'Linie', serien: [{ name: 'Temp', path: '/v' }] },
        { id: 'c', component: 'Diagramm', typ: 'kreis', titel: 'Kreis', serien: [{ name: 'Temp', path: '/v' }] },
      ],
      werte,
    );
    expect(within(screen.getByRole('img', { name: /Balken/ })).getAllByTestId('balken')).toHaveLength(3);
    expect(screen.getByRole('img', { name: /Linie/ }).querySelector('polyline')).not.toBeNull();
    expect(screen.getByRole('img', { name: /Kreis/ }).querySelectorAll('path')).toHaveLength(3);
    expect(container.querySelectorAll('.b-diagramm-legende')[0]).toHaveTextContent('Temp');
  });
});

describe('Aktionen', () => {
  it('Button im Template sendet buehne_aktion mit aufgelöstem Kontext', async () => {
    const u = userEvent.setup();
    zeige(
      [
        { id: 'root', component: 'List', children: { path: '/immobilien', componentId: 'notiz' } },
        { id: 'notiz', component: 'Button', text: { call: 'formatString', args: { value: 'Notiz zu ${titel}' } }, icon: 'edit', variant: 'primary', action: { event: { name: 'notiz_anlegen', context: { objekt_id: { path: 'id' }, quelle: 'buehne', gesamt: { path: '/anzahl' } } } } },
      ],
      { ...IMMOBILIEN, anzahl: 2 },
    );
    const knopf = screen.getByRole('button', { name: 'Notiz zu Elbchaussee 1' });
    expect(knopf).toHaveClass('b-button-primary');
    await u.click(knopf);
    const a = aktionen()[0];
    expect(a).toMatchObject({ typ: 'buehne_aktion', name: 'notiz_anlegen', surfaceId: 't', sourceComponentId: 'notiz', context: { objekt_id: 'elbchaussee', quelle: 'buehne', gesamt: 2 } });
    expect(a && 'timestamp' in a && !Number.isNaN(Date.parse(a.timestamp))).toBe(true);
  });

  it('Button-Varianten borderless und gefahr', () => {
    zeige([
      { id: 'root', component: 'Row', children: ['a', 'b'] },
      { id: 'a', component: 'Button', text: 'Leise', variant: 'borderless', action: { event: { name: 'x' } } },
      { id: 'b', component: 'Button', text: 'Löschen', variant: 'gefahr', icon: 'delete', action: { event: { name: 'y' } } },
    ]);
    expect(screen.getByRole('button', { name: 'Leise' })).toHaveClass('b-button-borderless');
    expect(screen.getByRole('button', { name: 'Löschen' })).toHaveClass('b-button-gefahr');
  });

  it('openUrl öffnet nur https in einem neuen Fenster', async () => {
    const u = userEvent.setup();
    const oeffnen = vi.spyOn(window, 'open').mockReturnValue(null);
    zeige(
      [
        { id: 'root', component: 'Row', children: ['ok', 'nein'] },
        { id: 'ok', component: 'Button', text: 'Exposé', action: { functionCall: { call: 'openUrl', args: { url: { path: '/link' } } } } },
        { id: 'nein', component: 'Button', text: 'Unsicher', action: { functionCall: { call: 'openUrl', args: { url: 'http://unsicher.example' } } } },
      ],
      { link: 'https://gg.example/expose/1' },
    );
    await u.click(screen.getByRole('button', { name: 'Exposé' }));
    expect(oeffnen).toHaveBeenCalledWith('https://gg.example/expose/1', '_blank', 'noopener,noreferrer');
    await u.click(screen.getByRole('button', { name: 'Unsicher' }));
    expect(oeffnen).toHaveBeenCalledTimes(1);
    expect(useJarvis.getState().hinweise.at(-1)?.text).toMatch(/https/);
    expect(aktionen()).toHaveLength(0);
  });
});

describe('Eingaben (zweiseitige Bindung)', () => {
  it('TextField schreibt lokal und sendet buehne_daten bei Blur und Enter', async () => {
    const u = userEvent.setup();
    zeige([{ id: 'root', component: 'TextField', label: 'Suche', value: { path: '/filter/suche' } }], { filter: { suche: 'Ham' } });
    const feld = screen.getByLabelText('Suche');
    expect(feld).toHaveValue('Ham');
    await u.type(feld, 'burg');
    expect(daten()).toEqual({ filter: { suche: 'Hamburg' } });
    expect(datenNachrichten()).toHaveLength(0);
    await u.tab();
    expect(datenNachrichten()).toEqual([{ typ: 'buehne_daten', surfaceId: 't', path: '/filter/suche', value: 'Hamburg' }]);
    await u.type(feld, '!{Enter}');
    expect(datenNachrichten().at(-1)).toMatchObject({ value: 'Hamburg!' });
  });

  it('TextField-Varianten number, obscured und longText', () => {
    const { container } = zeige([
      { id: 'root', component: 'Column', children: ['a', 'b', 'c'] },
      { id: 'a', component: 'TextField', label: 'Zahl', value: { path: '/n' }, variant: 'number' },
      { id: 'b', component: 'TextField', label: 'Geheim', value: { path: '/g' }, variant: 'obscured' },
      { id: 'c', component: 'TextField', label: 'Lang', value: { path: '/l' }, variant: 'longText' },
    ]);
    expect(screen.getByLabelText('Zahl')).toHaveAttribute('type', 'number');
    expect(screen.getByLabelText('Geheim')).toHaveAttribute('type', 'password');
    expect(container.querySelector('textarea')).not.toBeNull();
    fireEvent.change(screen.getByLabelText('Zahl'), { target: { value: '42' } });
    expect(daten()).toMatchObject({ n: 42 });
  });

  it('CheckBox schaltet und sendet sofort', async () => {
    const u = userEvent.setup();
    zeige([{ id: 'root', component: 'CheckBox', label: 'Nur aktive', value: { path: '/filter/aktiv' } }]);
    await u.click(screen.getByRole('checkbox', { name: 'Nur aktive' }));
    expect(daten()).toEqual({ filter: { aktiv: true } });
    expect(datenNachrichten()).toEqual([{ typ: 'buehne_daten', surfaceId: 't', path: '/filter/aktiv', value: true }]);
  });

  it('ChoicePicker als Chips, Dropdown und Mehrfachauswahl', async () => {
    const u = userEvent.setup();
    const optionen = [{ label: 'Hamburg', value: 'HH' }, { label: 'Berlin', value: 'B' }];
    zeige([
      { id: 'root', component: 'Column', children: ['a', 'b', 'c'] },
      { id: 'a', component: 'ChoicePicker', label: 'Stadt', options: optionen, value: { path: '/stadt' }, displayStyle: 'chips' },
      { id: 'b', component: 'ChoicePicker', label: 'Ort', options: optionen, value: { path: '/ort' }, displayStyle: 'dropdown' },
      { id: 'c', component: 'ChoicePicker', label: 'Städte', options: optionen, value: { path: '/staedte' }, displayStyle: 'checkbox' },
    ]);
    await u.click(within(screen.getByRole('radiogroup', { name: 'Stadt' })).getByRole('radio', { name: 'Berlin' }));
    expect(daten()).toMatchObject({ stadt: 'B' });
    await u.selectOptions(screen.getByLabelText('Ort'), 'HH');
    expect(daten()).toMatchObject({ ort: 'HH' });
    const gruppe = screen.getByRole('group', { name: 'Städte' });
    await u.click(within(gruppe).getByRole('checkbox', { name: 'Hamburg' }));
    await u.click(within(gruppe).getByRole('checkbox', { name: 'Berlin' }));
    expect(daten()).toMatchObject({ staedte: ['HH', 'B'] });
    expect(datenNachrichten().map((n) => (n.typ === 'buehne_daten' ? n.path : ''))).toEqual(['/stadt', '/ort', '/staedte', '/staedte']);
  });

  it('DateTimeInput bindet Datum und sendet bei Blur', () => {
    zeige([{ id: 'root', component: 'DateTimeInput', label: 'Ab', value: { path: '/filter/ab' }, enableDate: true, enableTime: true }]);
    const feld = screen.getByLabelText('Ab');
    expect(feld).toHaveAttribute('type', 'datetime-local');
    fireEvent.change(feld, { target: { value: '2026-11-01T10:30' } });
    expect(daten()).toEqual({ filter: { ab: '2026-11-01T10:30' } });
    fireEvent.blur(feld);
    expect(datenNachrichten()).toEqual([{ typ: 'buehne_daten', surfaceId: 't', path: '/filter/ab', value: '2026-11-01T10:30' }]);
  });

  it('Formular: Felder aus JSON-Schema, Pflichtfelder, Absenden mit /werte', async () => {
    const u = userEvent.setup();
    zeige(
      [
        {
          id: 'root', component: 'Formular', value: { path: '/notiz' }, absenden: 'Speichern',
          schema: {
            type: 'object',
            properties: {
              text: { type: 'string', title: 'Notiz' },
              prioritaet: { type: 'string', title: 'Priorität', enum: ['niedrig', 'hoch'] },
              stunden: { type: 'number', title: 'Stunden' },
              erledigt: { type: 'boolean', title: 'Erledigt' },
            },
            required: ['text'],
          },
          action: { event: { name: 'notiz_speichern', context: { objekt_id: { path: '/auswahl/id' } } } },
        },
      ],
      { auswahl: { id: 'hafenweg-3' }, notiz: { prioritaet: 'hoch' } },
    );
    await u.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Notiz');
    expect(aktionen()).toHaveLength(0);

    await u.type(screen.getByLabelText(/Notiz/), 'Rückruf');
    await u.type(screen.getByLabelText('Stunden'), '2');
    await u.click(screen.getByRole('checkbox', { name: 'Erledigt' }));
    expect(screen.getByLabelText('Priorität')).toHaveValue('hoch');
    await u.click(screen.getByRole('button', { name: 'Speichern' }));
    const werte = { text: 'Rückruf', prioritaet: 'hoch', stunden: 2, erledigt: true };
    expect(daten()).toMatchObject({ notiz: werte });
    expect(datenNachrichten()).toEqual([{ typ: 'buehne_daten', surfaceId: 't', path: '/notiz', value: werte }]);
    expect(aktionen()[0]).toMatchObject({ name: 'notiz_speichern', sourceComponentId: 'root', context: { objekt_id: 'hafenweg-3', werte } });
  });
});

describe('Katalog', () => {
  it('registriert genau die Bausteine aus kern/jarvis/buehne/katalog.json und rendert jedes Beispiel', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const { KATALOG_BAUSTEINE } = await import('../buehne/komponenten');
    const katalog = JSON.parse(readFileSync(resolve(__dirname, '../../../kern/jarvis/buehne/katalog.json'), 'utf8')) as {
      komponenten: Record<string, { beispiel: BuehnenKomponente }>;
    };
    expect(Object.keys(KATALOG_BAUSTEINE).sort()).toEqual(Object.keys(katalog.komponenten).sort());
    for (const [name, { beispiel }] of Object.entries(katalog.komponenten)) {
      useBuehne.getState().zuruecksetzen();
      const { container, unmount } = zeige([{ ...beispiel, id: 'root' }], {});
      expect(container.querySelector('.buehne-flaeche')?.children.length, name).toBeGreaterThan(0);
      unmount();
    }
  });
});
