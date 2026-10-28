// Button mit Aktion (event oder openUrl), Varianten default|primary|borderless|gefahr.
import type { BausteinProps } from '../register';
import { useBaustein } from '../kontext';
import { wahl } from './hilfen';
import { Symbolbild } from './symbole';

const VARIANTEN = ['default', 'primary', 'borderless', 'gefahr'] as const;

export function Button({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const text = h.t('text');
  const icon = typeof k.icon === 'string' ? k.icon : null;
  return (
    <button type="button" className={`b-button b-button-${wahl(k.variant, VARIANTEN, 'default')}`} onClick={() => h.ausloesen(k.action)} aria-label={text || icon || 'Aktion'}>
      {icon && <Symbolbild name={icon} />}
      {text && <span>{text}</span>}
    </button>
  );
}
