import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

export const SignupPage: React.FC = () => {
  const navigate = useNavigate();
  const { apiBaseUrl, uiLanguage } = useSettings();
  const uiText = (key: Parameters<typeof t>[1]) => t(uiLanguage, key);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setError(uiText('signupValidationUserPass'));
      return;
    }
    if (username.length < 3) {
      setError(uiText('signupValidationUserLen'));
      return;
    }
    if (password.length < 6) {
      setError(uiText('signupValidationPassLen'));
      return;
    }
    setLoading(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch(
        `${apiBaseUrl.replace(/\/$/, '')}/api/v1/users/register`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ username, password })
        }
      );
      if (!res.ok) {
        const text = await res.text();
        let message = '';
        try {
          const parsed = JSON.parse(text);
          if (res.status === 409 || parsed?.signal === 'user_already_exists') {
            message = uiText('signupUserExists');
          } else if (parsed?.detail && Array.isArray(parsed.detail)) {
            // Pydantic validation errors
            message = parsed.detail
              .map((d: any) => d.msg)
              .join(' ');
          } else if (typeof parsed?.detail === 'string') {
            message = parsed.detail;
          }
        } catch {
          // ignore JSON parse errors
        }
        if (!message) {
          message =
            res.status >= 500
              ? uiText('friendlyServerIssue')
              : uiText('signupFailed');
        }
        throw new Error(message);
      }
      setSuccess(true);
      setUsername('');
      setPassword('');
    } catch (err: any) {
      setError(err.message || uiText('signupFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-shell flex items-center justify-center">
      <div className="w-full max-w-sm app-card bg-white px-6 py-7">
        <h1 className="text-xl font-semibold mb-1 text-center text-slate-900">
          {uiText('signupTitle')}
        </h1>
        <p className="text-xs text-slate-500 mb-5 text-center">
          {uiText('signupSubtitle')}
        </p>
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
              autoComplete="new-password"
            />
          </div>
          {error && <div className="text-xs text-red-500">{error}</div>}
          {success && (
            <div className="text-xs text-emerald-600">
              {uiText('signupSuccess')}
            </div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="mt-3 inline-flex w-full items-center justify-center rounded-full bg-sky-600 px-4 py-2 text-xs font-semibold text-white shadow-md hover:bg-sky-500 disabled:opacity-50"
          >
            {loading ? uiText('signingIn') : uiText('signupSubmit')}
          </button>
        </form>
        <div className="mt-4 flex justify-between items-center text-[11px] text-slate-500">
          <button
            type="button"
            className="underline underline-offset-2 hover:text-sky-500"
            onClick={() => navigate('/login')}
          >
            {uiText('backToLogin')}
          </button>
        </div>
      </div>
    </div>
  );
};
