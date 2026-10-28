// Anzeige-Bausteine: Image, Icon, Badge, Kennzahl, Fortschritt, Karte.
import { MapPin } from 'lucide-react';
import type { BausteinProps } from '../register';
import { useBaustein } from '../kontext';
import { alsText, alsZahl, istSichereBildUrl } from '../binder';
import { klassen, tonKlasse, wahl } from './hilfen';
import { Symbolbild } from './symbole';

const BILD_VARIANTEN = ['icon', 'avatar', 'smallFeature', 'mediumFeature', 'largeFeature', 'header'] as const;

export function Image({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const url = h.w('url');
  const alt = h.t('alt');
  const variante = `b-bild-${wahl(k.variant, BILD_VARIANTEN, 'mediumFeature')}`;
  if (!istSichereBildUrl(url))
    return (
      <div role="img" aria-label={`${alt || 'Bild'} (nicht geladen)`} className={klassen('b-bild', 'b-bild-platzhalter', variante)}>
        <Symbolbild name="image" />
      </div>
    );
  return <img src={url} alt={alt} loading="lazy" referrerPolicy="no-referrer" className={klassen('b-bild', variante, `b-fit-${wahl(k.fit, ['cover', 'contain'] as const, 'cover')}`)} />;
}

export function Icon({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const name = h.t('name');
  return (
    <span className={klassen('b-icon', tonKlasse(k.ton))} title={name}>
      <Symbolbild name={name} groesse={20} />
    </span>
  );
}

export function Badge({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  return <span className={klassen('b-badge', tonKlasse(k.ton, 'b-ton-neutral'))}>{h.t('text')}</span>;
}

export function Kennzahl({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const trendRoh = h.w('trend');
  const trend = alsZahl(trendRoh);
  const einheit = h.t('einheit');
  const label = h.t('label');
  return (
    <div className="b-kennzahl">
      <div className="b-kennzahl-wert">
        <span>{h.t('wert')}</span>
        {einheit && <span className="b-kennzahl-einheit">{einheit}</span>}
        {trend !== null && trend !== 0 && (
          <span className={trend > 0 ? 'b-trend b-trend-hoch' : 'b-trend b-trend-runter'} aria-label={`Trend ${trend > 0 ? '+' : '−'}${alsText(Math.abs(trend))}`}>
            {trend > 0 ? '▲' : '▼'} {alsText(Math.abs(trend))}
          </span>
        )}
      </div>
      {label && <div className="b-kennzahl-label">{label}</div>}
    </div>
  );
}

export function Fortschritt({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const wert = Math.min(1, Math.max(0, alsZahl(h.w('wert')) ?? 0));
  const prozent = Math.round(wert * 100);
  const label = h.t('label');
  return (
    <div className="b-fortschritt">
      <div className="b-fortschritt-kopf">
        {label && <span>{label}</span>}
        <span className="b-fortschritt-zahl">{prozent} %</span>
      </div>
      <div role="progressbar" aria-label={label || 'Fortschritt'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={prozent} className="b-fortschritt-bahn">
        <div className="b-fortschritt-balken" style={{ width: `${prozent}%` }} />
      </div>
    </div>
  );
}

/** Link auf OpenStreetMap: Koordinaten bevorzugt, sonst Adresssuche. */
export function kartenLink(adresse: string, lat: number | null, lon: number | null): string | null {
  if (lat !== null && lon !== null && Math.abs(lat) <= 90 && Math.abs(lon) <= 180)
    return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=16/${lat}/${lon}`;
  if (adresse.trim()) return `https://www.openstreetmap.org/search?query=${encodeURIComponent(adresse.trim())}`;
  return null;
}

export function Karte({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const adresse = h.t('adresse');
  const lat = alsZahl(h.w('lat'));
  const lon = alsZahl(h.w('lon'));
  const link = kartenLink(adresse, lat, lon);
  const anzeige = adresse || (lat !== null && lon !== null ? `${alsText(lat)}, ${alsText(lon)}` : 'Ort unbekannt');
  return (
    <div className="b-karte">
      <MapPin size={18} aria-hidden="true" className="b-karte-nadel" />
      <span className="b-karte-adresse">{anzeige}</span>
      {link && (
        <a href={link} target="_blank" rel="noopener noreferrer" className="b-karte-link">
          Karte öffnen
        </a>
      )}
    </div>
  );
}
