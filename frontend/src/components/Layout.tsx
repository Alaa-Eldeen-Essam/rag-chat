import React, { useEffect, useState, useMemo } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useSettings } from '../settings/SettingsContext';
import { useHttpClient } from '../lib/httpClient';
import { t } from '../i18n/ui';

interface AssetSummaryOption {
  asset_id: number;
  name?: string;
  original_name?: string;
  doc_type?: string;
}

interface AssetsResponse {
  assets?: AssetSummaryOption[];
}

export const AppLayout: React.FC = () => {
  const {
    currentDocType,
    currentUserId,
    currentUserIsAdmin,
    docTypesVersion,
    uiLanguage,
    uiTheme,
    setSettings
  } = useSettings();
  const { request } = useHttpClient();
  const navigate = useNavigate();

  const [docTypes, setDocTypes] = useState<string[]>([]);
  const [assets, setAssets] = useState<AssetSummaryOption[]>([]);

  useEffect(() => {
    if (!currentUserId) {
      request<{ id: number; is_admin: boolean; department?: string | null }>(
        '/api/v1/users/me'
      )
        .then(user => {
          setSettings(prev => ({
            ...prev,
            currentUserId: user.id,
            currentUserIsAdmin: user.is_admin,
            defaultProjectId: String(user.id),
            currentUserDepartment: user.department ?? null
          }));
        })
        .catch(() => {
          // ignore; user may not be authenticated yet
        });
    }

    request<{ doc_types?: string[] }>('/api/v1/nlp/doc-types')
      .then(res => {
        const list = Array.isArray(res.doc_types) ? res.doc_types : [];
        setDocTypes(list);
      })
      .catch(() => {
        setDocTypes([]);
      });

    request<AssetsResponse>('/api/v1/data/assets')
      .then(res => {
        const items = Array.isArray(res.assets) ? res.assets : [];
        setAssets(items);
      })
      .catch(() => setAssets([]));
  }, [request, currentUserId, docTypesVersion, setSettings]);

  const filteredDocTypes = useMemo(() => {
    const assetDocTypes = new Set(assets.map(a => a.doc_type).filter(Boolean));
    return docTypes.filter(dt => assetDocTypes.has(dt));
  }, [docTypes, assets]);

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.lang = uiLanguage;
      document.documentElement.dir = uiLanguage === 'ar' ? 'rtl' : 'ltr';
    }
  }, [uiLanguage]);

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.theme = uiTheme;
    }
  }, [uiTheme]);

  return (
    <div className="app-shell flex flex-col min-h-screen">
      <header className="app-header glass-card sticky top-0 z-30 border-b border-[color:var(--border-subtle)]">
        <div className="flex items-center gap-4">
          <button
            type="button"
            className="flex items-center gap-3 group"
            onClick={() => navigate('/chat')}
            aria-label="Go to chat"
          >
            <span className="h-10 w-10 rounded-2xl bg-[var(--accent)] text-white flex items-center justify-center font-semibold text-lg shadow-lg group-hover:scale-105 transition">
              MA
            </span>
            <div className="text-left">
              <div className="text-sm font-semibold text-[color:var(--text-surface)] leading-none">
                {uiLanguage === 'ar' ? 'مركز المحادثة' : 'ChatWorkspace'}
              </div>
              {/* <div className="text-[11px] text-slate-500 leading-tight">
                {uiLanguage === 'ar' ? 'توجيه ذكي' : 'Guided mission control'}
              </div> */}
            </div>
          </button>
          <div className="hidden md:flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-wide text-slate-400">
              {t(uiLanguage, 'docType')}
            </span>
            <select
              className="app-header-select rounded-xl text-xs px-3 py-2 bg-[color:var(--bg-soft)]"
              value={currentDocType}
              onChange={e =>
                setSettings(prev => ({
                  ...prev,
                  currentDocType: e.target.value
                }))
              }
            >
              {filteredDocTypes.map(dt => (
                <option key={dt} value={dt}>
                  {dt}
                </option>
              ))}
            </select>
          </div>
        </div>


        <div className="flex items-center gap-3">
          <button
            type="button"
            className="app-header-toggle"
            onClick={() =>
              setSettings(prev => ({
                ...prev,
                uiLanguage: prev.uiLanguage === 'ar' ? 'en' : 'ar'
              }))
            }
          >
            {uiLanguage === 'ar' ? 'English' : 'العربية'}
          </button>
          <select
            className="app-header-toggle text-[11px] py-1 pr-6 pl-2"
            value={uiTheme}
            onChange={e =>
              setSettings(prev => ({
                ...prev,
                uiTheme: e.target.value as 'lumina' | 'neon' | 'dawn' | 'slate'
              }))
            }
          >
            <option value="lumina">
              {uiLanguage === 'ar' ? 'لمينا' : 'Lumina'}
            </option>
            <option value="neon">
              {uiLanguage === 'ar' ? 'نيون' : 'Neon'}
            </option>
            <option value="dawn">
              {uiLanguage === 'ar' ? 'الفجر' : 'Dawn'}
            </option>
            <option value="slate">
              {uiLanguage === 'ar' ? 'كلاسيكي' : 'Classic'}
            </option>
          </select>
          <div className="relative">
            <button
              type="button"
              className="app-header-toggle text-[11px] px-3 py-2 font-semibold text-[color:var(--text-surface)]"
              onClick={() => {
                setSettings(prev => ({
                  ...prev,
                  basicAuthUser: '',
                  basicAuthPass: '',
                  rememberPassword: false,
                  authToken: null,
                  authTokenExpiresAt: null,
                  currentUserId: null,
                  currentUserIsAdmin: false
                }));
                navigate('/login');
              }}
            >
              {t(uiLanguage, 'logout')}
            </button>
          </div>
        </div>
      </header>

      <nav className="px-6 pt-3 pb-2 flex items-center gap-2 text-sm sticky top-[82px] z-20">
        <NavLink
          to="/chat"
          className={({ isActive }) =>
            `px-3 py-2 rounded-full transition font-medium ${
              isActive
                ? 'bg-[color:var(--accent)] text-white shadow'
                : 'text-slate-500 hover:text-[color:var(--accent-strong)] hover:bg-white'
            }`
          }
        >
          {t(uiLanguage, 'navChat')}
        </NavLink>
        <NavLink
          to="/stats"
          className={({ isActive }) =>
            `px-3 py-2 rounded-full transition font-medium ${
              isActive
                ? 'bg-[color:var(--accent)] text-white shadow'
                : 'text-slate-500 hover:text-[color:var(--accent-strong)] hover:bg-white'
            }`
          }
        >
          {t(uiLanguage, 'navStats')}
        </NavLink>
        <NavLink
          to="/summaries"
          className={({ isActive }) =>
            `px-3 py-2 rounded-full transition font-medium ${
              isActive
                ? 'bg-[color:var(--accent)] text-white shadow'
                : 'text-slate-500 hover:text-[color:var(--accent-strong)] hover:bg-white'
            }`
          }
        >
          {t(uiLanguage, 'navSummaries')}
        </NavLink>
        {currentUserIsAdmin && (
          <NavLink
            to="/admin/users"
            className={({ isActive }) =>
              `px-3 py-2 rounded-full transition font-medium ${
                isActive
                  ? 'bg-[color:var(--accent)] text-white shadow'
                  : 'text-slate-500 hover:text-[color:var(--accent-strong)] hover:bg-white'
              }`
            }
          >
            {t(uiLanguage, 'navAdminUsers')}
          </NavLink>
        )}
        <NavLink
          to="/admin/files"
          className={({ isActive }) =>
            `px-3 py-2 rounded-full transition font-medium ${
              isActive
                ? 'bg-[color:var(--accent)] text-white shadow'
                : 'text-slate-500 hover:text-[color:var(--accent-strong)] hover:bg-white'
            }`
          }
        >
          {currentUserIsAdmin ? t(uiLanguage, 'navAdminFiles') : t(uiLanguage, 'navFiles')}
        </NavLink>
      </nav>

      <main className="flex-1 flex overflow-hidden px-4 pb-6 pt-2 max-w-6xl mx-auto w-full gap-4">
        <Outlet />
      </main>
    </div>
  );
};
