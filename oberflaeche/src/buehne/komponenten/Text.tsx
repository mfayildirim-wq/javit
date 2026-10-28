// Text: Überschriften als reiner Text, sonst Markdown ohne HTML; Links nur https, keine Bilder.
import type { ReactNode } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { BausteinProps } from '../register';
import { useBaustein } from '../kontext';
import { istHttps } from '../binder';
import { klassen, tonKlasse, wahl } from './hilfen';

const VARIANTEN = ['h1', 'h2', 'h3', 'h4', 'h5', 'body', 'caption'] as const;

const MD_KOMPONENTEN = {
  a: ({ href, children }: { href?: string; children?: ReactNode }) =>
    istHttps(href) ? (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  // Bilder nur über den Baustein Image (geprüfte URLs).
  img: ({ alt }: { alt?: string }) => (alt ? <span>{alt}</span> : null),
};

export function Text({ k, basis, tiefe }: BausteinProps) {
  const h = useBaustein(k, basis, tiefe);
  const variante = wahl(k.variant, VARIANTEN, 'body');
  const text = h.t('text');
  const klasse = klassen('b-text', `b-text-${variante}`, tonKlasse(k.ton));
  if (variante.startsWith('h')) {
    const Tag = variante as 'h1' | 'h2' | 'h3' | 'h4' | 'h5';
    return <Tag className={klasse}>{text}</Tag>;
  }
  return (
    <div className={klasse}>
      <Markdown remarkPlugins={[remarkGfm]} skipHtml components={MD_KOMPONENTEN}>
        {text}
      </Markdown>
    </div>
  );
}
