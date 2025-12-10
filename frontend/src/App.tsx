import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from './components/Layout';
import { ChatPage } from './pages/ChatPage';
import { StatsPage } from './pages/StatsPage';
import { AdminFilesPage } from './pages/AdminFilesPage';
import { LoginPage } from './pages/LoginPage';
import { SignupPage } from './pages/SignupPage';
import { useSettings } from './settings/SettingsContext';
import { AdminUsersPage } from './pages/AdminUsersPage';
import { SummariesPage } from './pages/SummariesPage';

const ProtectedLayout: React.FC = () => {
  const { basicAuthUser, basicAuthPass, authToken, authTokenExpiresAt } =
    useSettings();

  const hasBasic = !!basicAuthUser && !!basicAuthPass;
  const hasValidToken = !!authToken && (!authTokenExpiresAt || authTokenExpiresAt > Date.now());

  if (!hasBasic && !hasValidToken) {
    return <Navigate to="/login" replace />;
  }
  return <AppLayout />;
};

const App: React.FC = () => {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/" element={<ProtectedLayout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="stats" element={<StatsPage />} />
        <Route path="summaries" element={<SummariesPage />} />
        <Route path="admin">
          <Route path="users" element={<AdminUsersPage />} />
          <Route path="files" element={<AdminFilesPage />} />
        </Route>
      </Route>
    </Routes>
  );
};

export default App;
