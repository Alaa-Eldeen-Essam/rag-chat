import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { SettingsProvider } from './settings/SettingsContext';
import './index.css';

const queryClient = new QueryClient();

// Derive a robust basename so the app works both when
// served at the root (dev) and under /app (production via nginx/FastAPI),
// even if the build-time BASE_URL is "/".
const rawBase = import.meta.env.BASE_URL || '/';

const getBasename = (): string => {
  if (typeof window !== 'undefined') {
    const path = window.location.pathname;
    if (path.startsWith('/app')) {
      return '/app';
    }
  }

  if (rawBase === '/') {
    return '';
  }

  return rawBase.replace(/\/+$/, '');
};

const basename = getBasename();

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <SettingsProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={basename}>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </SettingsProvider>
  </React.StrictMode>
);
