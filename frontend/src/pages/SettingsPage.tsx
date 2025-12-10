import React, { useState } from 'react';
import { useSettings } from '../settings/SettingsContext';
import { useHttpClient } from '../lib/httpClient';

export const SettingsPage: React.FC = () => {
  const settings = useSettings();
  const { request } = useHttpClient();
  const [form, setForm] = useState({
    apiBaseUrl: settings.apiBaseUrl,
    defaultProjectId: settings.defaultProjectId,
    basicAuthUser: settings.basicAuthUser,
    basicAuthPass: settings.basicAuthPass,
    rememberPassword: settings.rememberPassword
  });
  const [status, setStatus] = useState<'idle' | 'testing' | 'ok' | 'error'>(
    'idle'
  );
  const [error, setError] = useState<string | null>(null);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value, type, checked } = e.target;
    setForm(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleSave = () => {
    settings.setSettings(prev => ({
      ...prev,
      ...form
    }));
  };

  const handleTestConnection = async () => {
    setStatus('testing');
    setError(null);
    try {
      await request('/api/v1/');
      if (form.defaultProjectId) {
        await request(
          `/api/v1/nlp/index/info/${encodeURIComponent(
            form.defaultProjectId
          )}`
        );
      }
      setStatus('ok');
    } catch (err: any) {
      setStatus('error');
      setError(err.message || 'Connection failed');
    }
  };

  return (
    <section className="flex-1 overflow-y-auto p-4">
      <div className="app-card-soft px-5 py-3 mb-3">
        <h1 className="text-sm font-semibold text-slate-900">Settings</h1>
      </div>
      <div className="max-w-lg space-y-3 text-xs app-card bg-white p-5">
        <div>
          <label className="block text-slate-600 mb-1 text-[11px]">
            API Base URL
          </label>
          <input
            name="apiBaseUrl"
            className="w-full rounded-xl bg-slate-50 border border-slate-200 px-3 py-1.5"
            value={form.apiBaseUrl}
            onChange={handleChange}
          />
        </div>
        <div>
          <label className="block text-slate-600 mb-1 text-[11px]">
            Default Project ID
          </label>
          <input
            name="defaultProjectId"
            className="w-full rounded-xl bg-slate-50 border border-slate-200 px-3 py-1.5"
            value={form.defaultProjectId}
            onChange={handleChange}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-slate-600 mb-1 text-[11px]">
              Basic Auth Username
            </label>
            <input
              name="basicAuthUser"
              className="w-full rounded-xl bg-slate-50 border border-slate-200 px-3 py-1.5"
              value={form.basicAuthUser}
              onChange={handleChange}
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1 text-[11px]">
              Basic Auth Password
            </label>
            <input
              name="basicAuthPass"
              type="password"
              className="w-full rounded-xl bg-slate-50 border border-slate-200 px-3 py-1.5"
              value={form.basicAuthPass}
              onChange={handleChange}
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            id="rememberPassword"
            name="rememberPassword"
            type="checkbox"
            checked={form.rememberPassword}
            onChange={handleChange}
          />
          <label
            htmlFor="rememberPassword"
            className="text-slate-600 select-none text-[11px]"
          >
            Remember password on this device
          </label>
        </div>
        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            onClick={handleSave}
            className="inline-flex items-center justify-center rounded-full bg-sky-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-sky-500"
          >
            Save Settings
          </button>
          <button
            type="button"
            onClick={handleTestConnection}
            className="inline-flex items-center justify-center rounded-full border border-sky-600 px-4 py-1.5 text-xs font-semibold text-sky-600 hover:bg-sky-50"
          >
            Test Connection
          </button>
          {status === 'testing' && (
            <span className="text-xs text-slate-500">Testing...</span>
          )}
          {status === 'ok' && (
            <span className="text-xs text-emerald-600">Connection OK</span>
          )}
          {status === 'error' && (
            <span className="text-xs text-red-500">
              {error || 'Connection failed'}
            </span>
          )}
        </div>
      </div>
    </section>
  );
};
