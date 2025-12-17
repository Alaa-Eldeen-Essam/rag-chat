import { useCallback } from 'react';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

export interface StreamCallbacks<TEvent = any> {
  onStart?: (event: TEvent) => void;
  onDelta?: (deltaText: string, rawEvent: TEvent) => void;
  onDone?: (finalPayload: TEvent) => void;
  onError?: (errorPayload: TEvent | Error) => void;
}

export const useStreamClient = () => {
  const {
    apiBaseUrl,
    basicAuthUser,
    basicAuthPass,
    authToken,
    uiLanguage
  } = useSettings();

  const streamFetch = useCallback(
    async (
      path: string,
      init: RequestInit,
      callbacks: StreamCallbacks
    ) => {
      const url = path.startsWith('http')
        ? path
        : `${apiBaseUrl.replace(/\/$/, '')}${path}`;

      let auth: string | undefined;
      if (authToken) {
        auth = `Bearer ${authToken}`;
      } else if (basicAuthUser && basicAuthPass) {
        auth = `Basic ${btoa(`${basicAuthUser}:${basicAuthPass}`)}`;
      }

      const res = await fetch(url, {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          ...(auth ? { Authorization: auth } : {}),
          ...(init.headers ?? {})
        }
      });

      const friendlyServerMessage = t(uiLanguage, 'friendlyServerIssue');

      if (!res.ok) {
        let body: any;
        const isJson = res.headers
          .get('content-type')
          ?.includes('application/json');
        if (isJson) {
          body = await res.json().catch(() => undefined);
        } else {
          const text = await res.text().catch(() => '');
          body = text ? { detail: text } : undefined;
        }
        const message =
          res.status >= 500
            ? friendlyServerMessage
            : body?.detail ||
              body?.message ||
              res.statusText ||
              friendlyServerMessage;
        if (body) {
          const payload = { ...body };
          if (!payload.detail) {
            payload.detail = message;
          }
          callbacks.onError?.(payload);
        } else {
          callbacks.onError?.(new Error(message));
        }
        return;
      }

      if (!res.body) {
        callbacks.onError?.(
          new Error('Streaming not supported on this response')
        );
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let newlineIndex: number;
          // eslint-disable-next-line no-cond-assign
          while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, newlineIndex).trim();
            buffer = buffer.slice(newlineIndex + 1);
            if (!line) continue;
            try {
              const event = JSON.parse(line);
              const signal = event.signal as string | undefined;
              if (!signal) continue;
              if (signal.endsWith('_stream_start')) {
                callbacks.onStart?.(event);
              } else if (signal.endsWith('_stream_delta')) {
                let deltaText = '';
                const delta = event.delta;
                if (typeof delta === 'string') {
                  deltaText = delta;
                } else if (delta && typeof delta === 'object') {
                  deltaText =
                    delta.text ??
                    delta.content ??
                    '';
                } else if (typeof event.text === 'string') {
                  deltaText = event.text;
                }
                callbacks.onDelta?.(deltaText, event);
              } else if (
                signal.endsWith('_success') ||
                signal.endsWith('_generation_success')
              ) {
                callbacks.onDone?.(event);
              } else if (
                signal.endsWith('_error') ||
                signal === 'error'
              ) {
                callbacks.onError?.(event);
              }
            } catch (err) {
              callbacks.onError?.(err as Error);
            }
          }
        }
        if (buffer.trim()) {
          try {
            const event = JSON.parse(buffer.trim());
            callbacks.onDone?.(event);
          } catch (err) {
            callbacks.onError?.(err as Error);
          }
        }
      } catch (err) {
        callbacks.onError?.(err as Error);
      } finally {
        reader.releaseLock();
      }
    },
    [apiBaseUrl, basicAuthUser, basicAuthPass, authToken, uiLanguage]
  );

  return { streamFetch };
};
