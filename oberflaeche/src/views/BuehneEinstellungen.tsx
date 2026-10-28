// Einstellungen → Reiter „Bühne“: Vorlagen, Stile (bearbeiten, ableiten) und Zuordnung Integration → Stil.
import { useEffect, useState } from 'react';
import { api } from '../api/rest';
import type { Stil } from '../api/types';
import { useBuehne } from '../buehne/store';
import { Abschnitt } from './EinstellungsBausteine';
import { StilAbleiten } from './buehne/StilAbleiten';
import { StileListe } from './buehne/StileListe';
import { Vorlagen } from './buehne/Vorlagen';
import { Zuordnung } from './buehne/Zuordnung';

export function BuehneEinstellungen() {
  const [stile, setStile] = useState<Stil[]>([]);
  const [zuordnung, setZuordnung] = useState<Record<string, string>>({});
  const [fehler, setFehler] = useState<string | null>(null);

  const stileLaden = () => {
    api.buehneStile().then(
      (liste) => {
        setStile(liste);
        useBuehne.getState().stileSetzen(liste);
      },
      (e: Error) => setFehler(e.message),
    );
  };
  useEffect(() => {
    stileLaden();
    api.buehne().then((b) => setZuordnung(b?.zuordnung ?? {}), () => undefined);
  }, []);

  return (
    <>
      <Vorlagen stile={stile} />
      <StileListe stile={stile} neuLaden={stileLaden} />
      <Abschnitt id="buehne-ableiten" titel="Neuer Stil" text="Aus einer App-Seite, einer Stildatei oder eingefügten Klassen leitet der Assistent Farben, Schrift und Rundungen ab.">
        <StilAbleiten onAngelegt={stileLaden} />
      </Abschnitt>
      <Zuordnung stile={stile} zuordnung={zuordnung} setZuordnung={setZuordnung} />
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </>
  );
}
