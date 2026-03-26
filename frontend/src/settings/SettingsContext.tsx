import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState
} from 'react';

export type ModelKind = 'best';

export interface SettingsState {
  apiBaseUrl: string;
  defaultProjectId: string;
  basicAuthUser: string;
  basicAuthPass: string;
  rememberPassword: boolean;
  defaultModel: ModelKind;
  currentDocType: string;
  chatMode: 'rag' | 'regular' | 'multihop';
  currentUserId: number | null;
  currentUserIsAdmin: boolean;
  docTypesVersion: number;
  currentUserDepartment?: string | null;
  uiLanguage: 'en' | 'ar';
  uiTheme: 'slate' | 'aqua' | 'aurora' | 'ember';
  authToken: string | null;
  authTokenExpiresAt: number | null;
}

export interface SettingsContextValue extends SettingsState {
  setSettings: (updater: (prev: SettingsState) => SettingsState) => void;
}

// Use a versioned storage key so that changes to defaults (like apiBaseUrl)
// take effect for existing users without having to manually clear storage.
const STORAGE_KEY = 'mini_rag_settings_v2';
const PASSWORD_KEY = 'mini_rag_password_v1';

// Default API base URL:
// - In the browser, align with the current origin and respect the app base path (Vite `base` defaults to `/app/`).
// - In non-browser environments (SSR/tests), fall back to empty string.
const defaultApiBaseUrl =
  typeof window !== 'undefined'
    ? new URL(
        (import.meta as any)?.env?.BASE_URL || '/app/',
        window.location.origin
      )
        .toString()
        .replace(/\/$/, '')
    : '';

const defaultState: SettingsState = {
  apiBaseUrl: defaultApiBaseUrl,
  defaultProjectId: 'default',
  basicAuthUser: '',
  basicAuthPass: '',
  rememberPassword: false,
  defaultModel: 'best',
  currentDocType: '',
  chatMode: 'rag',
  currentUserId: null,
  currentUserIsAdmin: false,
  docTypesVersion: 0,
  currentUserDepartment: null,
  uiLanguage: 'en',
  uiTheme: 'slate',
  authToken: null,
  authTokenExpiresAt: null
};

const SettingsContext = createContext<SettingsContextValue | undefined>(
  undefined
);

export const SettingsProvider: React.FC<{ children: React.ReactNode }> = ({
  children
}) => {
  const [state, setState] = useState<SettingsState>(() => {
    if (typeof window === 'undefined') return defaultState;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultState;
      const parsed = JSON.parse(raw) as Partial<SettingsState>;
      const base: SettingsState = { ...defaultState, ...parsed };
      // Always enforce 'best' as the only generation model.
      base.defaultModel = 'best';
      if (parsed.uiLanguage !== 'ar' && parsed.uiLanguage !== 'en') {
        base.uiLanguage = defaultState.uiLanguage;
      }
      if (
        parsed.uiTheme !== 'slate' &&
        parsed.uiTheme !== 'aqua' &&
        parsed.uiTheme !== 'aurora' &&
        parsed.uiTheme !== 'ember'
      ) {
        base.uiTheme = defaultState.uiTheme;
      }
      if (parsed.rememberPassword) {
        const storedPass = window.localStorage.getItem(PASSWORD_KEY) ?? '';
        base.basicAuthPass = storedPass;
      }
      if (parsed.chatMode !== 'regular' && parsed.chatMode !== 'rag' && parsed.chatMode !== 'multihop') {
        base.chatMode = defaultState.chatMode;
      }
      if (
        base.authToken &&
        base.authTokenExpiresAt &&
        base.authTokenExpiresAt <= Date.now()
      ) {
        base.authToken = null;
        base.authTokenExpiresAt = null;
      }
      return base;
    } catch {
      return defaultState;
    }
  });

  // Ensure the API base aligns with the app base path (`/app`) when served behind a prefix.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const desiredBase = defaultApiBaseUrl.replace(/\/$/, '');
    const currentBase = (state.apiBaseUrl || '').replace(/\/$/, '');
    if (desiredBase && currentBase && desiredBase !== currentBase) {
      setState(prev => ({ ...prev, apiBaseUrl: desiredBase }));
    }
  }, [state.apiBaseUrl]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const { basicAuthPass, rememberPassword, ...rest } = state;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(rest));
    if (rememberPassword) {
      window.localStorage.setItem(PASSWORD_KEY, basicAuthPass);
    } else {
      window.localStorage.removeItem(PASSWORD_KEY);
    }
  }, [state]);

  const setSettings = useCallback(
    (updater: (prev: SettingsState) => SettingsState) => {
      setState(prev => updater(prev));
    },
    []
  );

  const value = useMemo(
    () => ({
      ...state,
      setSettings
    }),
    [state, setSettings]
  );

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
};

export const useSettings = (): SettingsContextValue => {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
};
