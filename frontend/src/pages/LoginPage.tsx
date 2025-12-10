import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const settings = useSettings();
  const uiText = (key: Parameters<typeof t>[1]) => t(settings.uiLanguage, key);

  const [username, setUsername] = useState(settings.basicAuthUser);
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(settings.rememberPassword);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setLoading(true);
    setError(null);

    try {
      const apiBase = settings.apiBaseUrl.replace(/\/$/, '');
      const res = await fetch(`${apiBase}/api/v1/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ username, password })
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        let message: string | undefined;
        if (body?.detail?.signal === 'invalid_credentials_error') {
          message = t(settings.uiLanguage, 'invalidCredentials');
        } else if (body?.detail?.signal) {
          message = body.detail.signal;
        } else if (res.status >= 500) {
          message = uiText('friendlyServerIssue');
        }
        throw new Error(message || `Login failed (${res.status})`);
      }

      const payload = await res.json();
      const expiresMs = (payload?.expires_in ?? 0) * 1000;
      const expiresAt = expiresMs ? Date.now() + expiresMs : null;
      const userInfo = payload?.user ?? {};
      settings.setSettings(prev => ({
        ...prev,
        basicAuthUser: remember ? username : '',
        basicAuthPass: remember ? password : '',
        rememberPassword: remember,
        authToken: payload?.access_token ?? null,
        authTokenExpiresAt: expiresAt,
        currentUserId: userInfo?.id ?? null,
        currentUserIsAdmin: !!userInfo?.is_admin,
        currentUserDepartment: userInfo?.department ?? null,
        defaultProjectId:
          userInfo?.id ? String(userInfo.id) : prev.defaultProjectId
      }));

      navigate('/chat', { replace: true });
    } catch (err: any) {
      setError(err.message || t(settings.uiLanguage, 'login'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-shell flex items-center justify-center">
      <div className="w-full max-w-sm app-card bg-white px-6 py-7">
        <h1 className="text-xl font-semibold mb-1 text-center text-slate-900">
          {uiText('loginTitle')}
        </h1>
        <p className="text-xs text-slate-500 mb-5 text-center">
          {uiText('loginSubtitle')}
        </p>
        <div className="flex justify-center mb-3">
          <button
            type="button"
            className="text-[11px] px-3 py-1 rounded-full border border-slate-200 bg-slate-50 text-slate-700 hover:border-sky-500 hover:text-sky-600"
            onClick={() =>
              settings.setSettings(prev => ({
                ...prev,
                uiLanguage: prev.uiLanguage === 'ar' ? 'en' : 'ar'
              }))
            }
          >
            {settings.uiLanguage === 'ar' ? 'English' : 'العربية'}
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3 text-xs">
          <div>
            <label className="block mb-1 text-slate-600 text-[11px]">
              {uiText('username')}
            </label>
            <input
              className="w-full rounded-xl bg-slate-50 border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-sky-500"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
            />
          </div>
          <div>
            <label className="block mb-1 text-slate-600 text-[11px]">
              {uiText('password')}
            </label>
            <input
              type="password"
              className="w-full rounded-xl bg-slate-50 border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-sky-500"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          
          {error && <div className="text-xs text-red-500">{error}</div>}
          <button
            type="submit"
            disabled={loading}
            className="mt-3 inline-flex w-full items-center justify-center rounded-full bg-sky-600 px-4 py-2 text-xs font-semibold text-white shadow-md hover:bg-sky-500 disabled:opacity-50"
          >
            {loading ? uiText('signingIn') : uiText('login')}
          </button>
        </form>
        <div className="mt-4 flex justify-between items-center text-[11px] text-slate-500">
          <button
            type="button"
            className="underline underline-offset-2 hover:text-sky-500"
            onClick={() => navigate('/signup')}
          >
            {uiText('signupSubmit')}
          </button>
        </div>
      </div>
    </div>
  );
};
