import React, { useEffect, useRef, useState } from 'react';
import { useHttpClient } from '../lib/httpClient';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

interface SummaryListItem {
  summary_id: number;
  file_id?: number;
  file_name?: string | null;
  doc_type?: string | null;
  model?: string | null;
  focus?: string | null;
  created_at?: string | null;
}

interface SummariesResponse {
  summaries?: SummaryListItem[];
  total?: number;
}

interface SummaryDetail {
  summary_id: number;
  summary: string;
  file_id?: number;
  file_name?: string | null;
  doc_type?: string | null;
  model?: string | null;
  focus?: string | null;
  max_chunks?: number | null;
  max_output_tokens?: number | null;
  created_at?: string | null;
  prompt_text?: string | null;
}

export const SummariesPage: React.FC = () => {
  const { request } = useHttpClient();
  const { uiLanguage } = useSettings();
  const uiText = (key: Parameters<typeof t>[1]) => t(uiLanguage, key);
  const isRTL = uiLanguage === 'ar';
  const [summaries, setSummaries] = useState<SummaryListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SummaryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false);
  const [detailPanelWidth, setDetailPanelWidth] = useState(360);
  const [isResizingWidth, setIsResizingWidth] = useState(false);
  const [summaryHeight, setSummaryHeight] = useState(220);
  const [isResizingSummaryHeight, setIsResizingSummaryHeight] = useState(false);
  const detailPanelRef = useRef<HTMLDivElement | null>(null);
  const summaryBoxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await request<SummariesResponse>(
          '/api/v1/nlp/summary?limit=50'
        );
        setSummaries(Array.isArray(res.summaries) ? res.summaries : []);
        setTotal(res.total ?? 0);
      } catch (err: any) {
        setError(err.message || uiText('summaries'));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [request, uiLanguage]);

  const filtered = summaries.filter(s => {
    const haystack = [
      s.file_name,
      s.doc_type,
      s.model,
      s.focus,
      s.created_at
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    return haystack.includes(search.toLowerCase());
  });

  const loadDetail = async (id: number) => {
    setSelectedId(id);
    setDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      const res = await request<SummaryDetail>(`/api/v1/nlp/summary/${id}`);
      setDetail(res);
    } catch (err: any) {
        setError(err.message || uiText('summaries'));
    } finally {
      setDetailLoading(false);
    }
  };

  const toggleSelection = (id: number) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(existing => existing !== id) : [...prev, id]
    );
  };

  const deleteSummariesBulk = async (ids: number[]) => {
    if (!ids.length) return;
    setDeletingId(-1);
    try {
      await request(`/api/v1/nlp/summaries/bulk-delete`, {
        method: 'POST',
        body: JSON.stringify({ summary_ids: ids }),
      });
      setSummaries(prev => prev.filter(s => !ids.includes(s.summary_id)));
      setTotal(prev => Math.max(0, prev - ids.length));
      if (ids.includes(selectedId ?? -1)) {
        setSelectedId(null);
        setDetail(null);
      }
    } catch (err: any) {
      setError(err.message || uiText('summaryFailed'));
    } finally {
      setDeletingId(null);
      setSelectedIds(prev => prev.filter(id => !ids.includes(id)));
      setShowBulkDeleteConfirm(false);
    }
  };

  const handleDeleteSummary = async (id: number) => {
    setDeletingId(id);
    setError(null);
    try {
      await request(`/api/v1/nlp/summary/${id}`, { method: 'DELETE' });
      setSummaries(prev => prev.filter(s => s.summary_id !== id));
      setTotal(prev => Math.max(0, prev - 1));
      if (selectedId === id) {
        setSelectedId(null);
        setDetail(null);
      }
    } catch (err: any) {
      setError(err.message || uiText('summaryFailed'));
    } finally {
      setDeletingId(null);
      setConfirmTarget(null);
    }
  };

  useEffect(() => {
    if (!isResizingWidth) return;
    const handleMove = (e: MouseEvent) => {
      if (!detailPanelRef.current) return;
      const parent = detailPanelRef.current.parentElement;
      if (!parent) return;
      const parentRect = parent.getBoundingClientRect();
      const newWidth = parentRect.right - e.clientX;
      const minWidth = 260;
      const maxWidth = Math.max(320, parentRect.width - 280);
      const clamped = Math.min(Math.max(newWidth, minWidth), maxWidth);
      setDetailPanelWidth(clamped);
    };
    const stop = () => setIsResizingWidth(false);
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', stop);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', stop);
    };
  }, [isResizingWidth]);

  useEffect(() => {
    if (!isResizingSummaryHeight) return;
    const handleMove = (e: MouseEvent) => {
      if (!summaryBoxRef.current) return;
      const rect = summaryBoxRef.current.getBoundingClientRect();
      const newHeight = e.clientY - rect.top;
      const minHeight = 140;
      const maxHeight = 480;
      setSummaryHeight(Math.min(Math.max(newHeight, minHeight), maxHeight));
    };
    const stop = () => setIsResizingSummaryHeight(false);
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', stop);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', stop);
    };
  }, [isResizingSummaryHeight]);

  return (
    <section className="flex-1 overflow-y-auto p-4 space-y-4">
      <div className="app-card-soft px-5 py-4 flex flex-col md:flex-row md:items-center md:justify-between rounded-3xl gap-3">
        <div>
          <h1 className="text-sm font-semibold text-slate-900">
            {uiText('summaries')}
          </h1>
          <p className="text-[11px] text-slate-500">
            {uiLanguage === 'ar'
              ? 'استعرض الملخصات واحفظ أهم النقاط'
              : 'Browse generated summaries and keep the highlights handy.'}
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <input
            className="rounded-full bg-white border border-[color:var(--border-subtle)] px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
            placeholder={uiText('search')}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <button
            type="button"
            className="px-4 py-2 rounded-full border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50"
            onClick={() => setShowBulkDeleteConfirm(true)}
            disabled={selectedIds.length === 0}
          >
            {uiText('deleteSelected')}
          </button>
          <span className="text-slate-500">
            {uiText('summaries')}: {total || summaries.length}
          </span>
        </div>
      </div>
      {error && <div className="text-xs text-red-500">{error}</div>}
      {loading && (
        <div className="text-xs text-slate-400">{uiText('loading')}</div>
      )}
      {!loading && filtered.length === 0 && !error && (
        <div className="text-xs text-slate-500">
          {uiText('noSummaries')}
        </div>
      )}
      {filtered.length > 0 && (
        <div className="flex flex-col md:flex-row gap-4">
          <div className="flex-1 overflow-x-auto app-card">
            <table
              className={`min-w-full text-xs ${isRTL ? 'text-right' : 'text-left'}`}
              dir={isRTL ? 'rtl' : 'ltr'}
            >
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-3 py-2 border-b border-slate-200 text-[11px]">
                    <input
                      type="checkbox"
                      className="h-3 w-3 accent-[color:var(--accent-strong)]"
                      checked={
                        filtered.length > 0 &&
                        filtered.every(item => selectedIds.includes(item.summary_id))
                      }
                      onChange={e => {
                        if (e.target.checked) {
                          setSelectedIds(filtered.map(item => item.summary_id));
                        } else {
                          setSelectedIds([]);
                        }
                      }}
                    />
                  </th>
                  <th className={`px-3 py-2 border-b border-slate-200 text-[11px] font-semibold tracking-wide uppercase text-slate-500 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {uiText('file')}
                  </th>
                  <th className={`px-3 py-2 border-b border-slate-200 text-[11px] font-semibold tracking-wide uppercase text-slate-500 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {uiText('docType')}
                  </th>
                  <th className={`px-3 py-2 border-b border-slate-200 text-[11px] font-semibold tracking-wide uppercase text-slate-500 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {uiText('model')}
                  </th>
                  <th className={`px-3 py-2 border-b border-slate-200 text-[11px] font-semibold tracking-wide uppercase text-slate-500 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {uiText('summaryFocusLabel')}
                  </th>
                  <th className={`px-3 py-2 border-b border-slate-200 text-[11px] font-semibold tracking-wide uppercase text-slate-500 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {uiText('created')}
                  </th>
                  <th className="px-3 py-2 border-b border-slate-200 text-[11px] font-semibold tracking-wide uppercase text-slate-500">
                    {uiText('actions')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(s => (
                  <tr
                    key={s.summary_id}
                    className={`cursor-pointer odd:bg-white even:bg-slate-50/60 hover:bg-sky-50 transition ${
                      selectedId === s.summary_id ? 'ring-1 ring-sky-500' : ''
                    }`}
                    onClick={() => loadDetail(s.summary_id)}
                  >
                    <td className="px-3 py-2 border-b border-slate-100">
                      <input
                        type="checkbox"
                        className="h-3 w-3 accent-[color:var(--accent-strong)]"
                        checked={selectedIds.includes(s.summary_id)}
                        onChange={e => {
                          e.stopPropagation();
                          toggleSelection(s.summary_id);
                        }}
                      />
                    </td>
                    <td className="px-3 py-2 border-b border-slate-100">
                      <div className="max-w-xs truncate text-slate-700 font-medium">
                        {s.file_name || `${uiText('asset')} #${s.file_id ?? ''}`}
                      </div>
                    </td>
                    <td className="px-3 py-2 border-b border-slate-100">
                      <span className="text-slate-600">{s.doc_type || '-'}</span>
                    </td>
                    <td className="px-3 py-2 border-b border-slate-100">
                      <span className="text-slate-600">{s.model || '-'}</span>
                    </td>
                    <td className="px-3 py-2 border-b border-slate-100">
                      <div className="max-w-xs truncate text-slate-600">
                        {s.focus || '-'}
                      </div>
                    </td>
                    <td className="px-3 py-2 border-b border-slate-100">
                      <span className="text-slate-500 text-[11px]">
                        {s.created_at
                          ? new Date(s.created_at).toLocaleString()
                          : '-'}
                      </span>
                    </td>
                    <td className="px-3 py-2 border-b border-slate-100">
                      <button
                        type="button"
                        className="text-[11px] px-3 py-1 rounded-full border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-60"
                        onClick={e => {
                          e.stopPropagation();
                          setConfirmTarget(s.summary_id);
                        }}
                        disabled={deletingId === s.summary_id}
                      >
                        {deletingId === s.summary_id ? uiText('loading') : uiText('delete')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div
            ref={detailPanelRef}
            className="w-full md:flex-shrink-0 app-card bg-white p-4 text-xs flex flex-col gap-2 relative"
            style={{ width: detailPanelWidth, maxWidth: '100%' }}
          >
            <div
              className="hidden md:block absolute left-0 top-0 bottom-0 w-2 cursor-col-resize"
              onMouseDown={e => {
                e.preventDefault();
                setIsResizingWidth(true);
              }}
            >
              <div className="h-full w-[3px] bg-[color:var(--border-subtle)] hover:bg-[color:var(--accent)] mx-auto rounded-full" />
            </div>
            <div className="md:pl-2">
              <div className="flex items-center justify-between">
                <div className="font-semibold text-slate-900">
                  {uiText('summaryDetails')}
                </div>
                {detail && detail.created_at && (
                  <span className="text-[10px] text-emerald-600">
                    {uiText('saved')}{' '}
                    {new Date(detail.created_at).toLocaleString()}
                  </span>
                )}
              </div>
            {detailLoading && (
              <div className="text-slate-500 text-[11px]">
                {uiText('loadingSummary')}
              </div>
            )}
            {!detailLoading && !detail && (
              <div className="text-slate-400 text-[11px]">
                {uiText('selectSummary')}
              </div>
            )}
            {detail && (
              <>
                <div className="text-slate-700">
                  <span className="font-medium">{uiText('file')}: </span>
                  {detail.file_name ||
                    (detail.file_id
                      ? `${uiText('asset')} #${detail.file_id}`
                      : '-')}
                </div>
                <div className="text-slate-700">
                  <span className="font-medium">{uiText('docType')}: </span>
                  {detail.doc_type || '-'}
                </div>
                <div className="text-slate-700">
                  <span className="font-medium">{uiText('model')}: </span>
                  {detail.model || '-'}
                </div>
                {detail.focus && (
                  <div className="text-slate-700">
                    <span className="font-medium">{uiText('summaryFocusLabel')}: </span>
                    {detail.focus}
                  </div>
                )}
                <div
                  ref={summaryBoxRef}
                  className="mt-2 flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 whitespace-pre-wrap"
                  style={{ height: summaryHeight }}
                >
                  {detail.summary}
                </div>
                <div
                  className="hidden md:flex items-center justify-center h-4 cursor-row-resize"
                  onMouseDown={e => {
                    e.preventDefault();
                    setIsResizingSummaryHeight(true);
                  }}
                >
                  <div className="w-10 h-1 rounded-full bg-[color:var(--border-subtle)]" />
                </div>
                <div className="flex justify-end mt-2">
                  <button
                    type="button"
                    className="mt-2 px-4 py-2 rounded-full border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-60"
                    onClick={() => setConfirmTarget(detail.summary_id)}
                    disabled={deletingId === detail.summary_id}
                  >
                    {deletingId === detail.summary_id ? uiText('loading') : uiText('delete')}
                  </button>
                </div>
              </>
            )}
            </div>
          </div>
        </div>
      )}
      {confirmTarget !== null && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-3xl bg-white border border-[color:var(--border-subtle)] p-5 shadow-2xl text-xs">
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-[color:var(--text-surface)] mb-1">
                {uiText('deleteSummaryTitle')}
              </h2>
              <p className="text-slate-500 text-sm">
                {uiText('deleteSummaryBody')}
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="px-4 py-2 rounded-full border border-[color:var(--border-subtle)] text-slate-600 hover:border-[color:var(--accent)]"
                onClick={() => setConfirmTarget(null)}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="px-4 py-2 rounded-full bg-[color:var(--accent-strong)] text-white hover:bg-[color:var(--accent)] disabled:opacity-60"
                onClick={() => confirmTarget && handleDeleteSummary(confirmTarget)}
                disabled={deletingId === confirmTarget}
              >
                {deletingId === confirmTarget ? uiText('loading') : uiText('delete')}
              </button>
            </div>
          </div>
        </div>
      )}
      {showBulkDeleteConfirm && selectedIds.length > 0 && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-3xl bg-white border border-[color:var(--border-subtle)] p-5 shadow-2xl text-xs">
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-[color:var(--text-surface)] mb-1">
                {uiText('summariesBulkDeleteTitle')}
              </h2>
              <p className="text-slate-500 text-sm">
                {uiText('summariesBulkDeleteBody')} ({selectedIds.length})
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="px-4 py-2 rounded-full border border-[color:var(--border-subtle)] text-slate-600 hover:border-[color:var(--accent)]"
                onClick={() => setShowBulkDeleteConfirm(false)}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="px-4 py-2 rounded-full bg-[color:var(--accent-strong)] text-white hover:bg-[color:var(--accent)] disabled:opacity-60"
                onClick={() => deleteSummariesBulk(selectedIds)}
                disabled={deletingId === -1}
              >
                {deletingId === -1 ? uiText('loading') : uiText('deleteSelected')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
