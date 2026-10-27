import { useEffect, useState } from 'react';
import { Boot } from './components/Boot';
import { TopBar } from './components/TopBar';
import { SystemsPanel } from './components/SystemsPanel';
import { ActivityPanel } from './components/ActivityPanel';
import { Konsole } from './components/Konsole';
import { ApprovalDialog } from './components/ApprovalDialog';
import { CommandPalette } from './components/CommandPalette';
import { VerbindungsHinweis, Hinweise } from './components/Hinweise';
import { IntegrationsAnsicht } from './views/Integrations';
import { EinstellungenAnsicht } from './views/Settings';
import { useKernVerbindung } from './state/verbindung';
import { useFenstertitel, useJarvis } from './state/store';
import { useTastenkuerzel } from './lib/tasten';

export default function App() {
  useKernVerbindung();
  useTastenkuerzel();
  const ansicht = useJarvis((s) => s.ansicht);
  useFenstertitel();
  const [bootFertig, setBootFertig] = useState(() => sessionStorageWert('jarvis.boot') === '1');

  useEffect(() => {
    if (bootFertig) sessionStorageSetzen('jarvis.boot', '1');
  }, [bootFertig]);

  return (
    <div className="app" data-ansicht={ansicht}>
      <div className="raster" aria-hidden="true" />
      <TopBar />
      <div className="buehne">
        <SystemsPanel />
        <main className="mitte" id="inhalt">
          <Konsole aktiv={ansicht === 'konsole' && bootFertig} />
          {ansicht === 'integrationen' && <IntegrationsAnsicht />}
          {ansicht === 'einstellungen' && <EinstellungenAnsicht />}
        </main>
        <ActivityPanel />
      </div>
      <VerbindungsHinweis />
      <Hinweise />
      <ApprovalDialog />
      <CommandPalette />
      <div className="scanlinien" aria-hidden="true" />
      {!bootFertig && <Boot onFertig={() => setBootFertig(true)} />}
    </div>
  );
}

function sessionStorageWert(k: string): string | null {
  try {
    return sessionStorage.getItem(k);
  } catch {
    return null;
  }
}
function sessionStorageSetzen(k: string, v: string): void {
  try {
    sessionStorage.setItem(k, v);
  } catch {
    /* egal */
  }
}
