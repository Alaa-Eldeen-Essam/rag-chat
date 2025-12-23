import { useCallback } from 'react';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

export interface HttpError extends Error {
  status?: number;
  detail?: string;
  payload?: unknown;
}

export const useHttpClient = () => {
  const {
    apiBaseUrl,
    basicAuthUser,
    basicAuthPass,
    authToken,
    uiLanguage,
    setSettings
  } = useSettings();

  const request = useCallback(
    async <T>(
      path: string,
      options: RequestInit = {}
    ): Promise<T> => {
      const url = path.startsWith('http')
        ? path
        : `${apiBaseUrl.replace(/\/$/, '')}${path}`;

      const basicAuth =
        basicAuthUser && basicAuthPass
          ? `Basic ${btoa(`${basicAuthUser}:${basicAuthPass}`)}`
          : undefined;

      const res = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...(authToken
            ? { Authorization: `Bearer ${authToken}` }
            : basicAuth
            ? { Authorization: basicAuth }
            : {}),
          ...(options.headers ?? {})
        }
      });

      const isJson = res.headers
        .get('content-type')
        ?.includes('application/json');
      const body = isJson ? await res.json().catch(() => undefined) : undefined;

      if (!res.ok) {
        if (res.status === 401 && authToken) {
          setSettings(prev => ({
            ...prev,
            authToken: null,
            authTokenExpiresAt: null
          }));
        }
        const friendlyServerMessage = t(uiLanguage, 'friendlyServerIssue');
        const isServerError = res.status >= 500;
        const rawSignal =
          (body as any)?.signal ?? (body as any)?.detail?.signal;
        let detail: string | undefined;

        if (rawSignal === 'user_already_exists') {
          detail = t(uiLanguage, 'signupUserExists');
        } else if (isServerError) {
          detail = friendlyServerMessage;
        } else if (typeof (body as any)?.detail === 'string') {
          detail = (body as any)?.detail;
        } else {
          detail = rawSignal;
        }
        const err: HttpError = new Error(
          detail || res.statusText || 'Request failed'
        );
        err.status = res.status;
        err.detail = detail;
        err.payload = body;
        throw err;
      }

      return body as T;
    },
    [apiBaseUrl, basicAuthUser, basicAuthPass, authToken, uiLanguage, setSettings]
  );

  return { request };
};
