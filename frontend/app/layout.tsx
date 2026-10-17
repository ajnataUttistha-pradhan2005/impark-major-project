import type { Metadata } from 'next';
import '../src/styles.css';
import App from '../src/App';

export const metadata: Metadata = {
  title: 'IMPARK · Medicinal Plant Explorer',
  description: 'Explore Indian medicinal plants with grounded, evidence-aware answers.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><App />{children}</body></html>;
}
