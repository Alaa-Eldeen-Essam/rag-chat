import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useHttpClient } from '../lib/httpClient';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

interface Asset {
  asset_id: number;
  project_id?: number;
  user_id?: number;
  name?: string;
  original_name?: string;
  doc_type?: string;
  size?: number;
  is_private?: boolean;
  visibility?: string;
  department?: string[] | string | null;
  created_at?: string;
}

interface AssetsResponse {
  assets?: Asset[];
  no_of_assets?: number;
}

export const AdminFilesPage: React.FC = () => {
  const { request } = useHttpClient();
  const navigate = useNavigate();
  const { setSettings, currentUserId, currentUserIsAdmin, uiLanguage } = useSettings();
  const uiText = (key: Parameters<typeof t>[1]) => t(uiLanguage, key);
  const isRTL = uiLanguage === 'ar';
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [showBulkDelete, setShowBulkDelete] = useState(false);
  const [editingDocTypeId, setEditingDocTypeId] = useState<number | null>(null);
  const [editingDocTypeValue, setEditingDocTypeValue] = useState('');
  const [savingDocType, setSavingDocType] = useState(false);

  const loadAssets = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await request<AssetsResponse>('/api/v1/data/assets');
      setAssets(Array.isArray(res.assets) ? res.assets : []);
    } catch (err: any) {
      setError(err.message || uiText('loadingAssets'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAssets();
  }, []);

  const handleDelete = async (assetId: number) => {
    try {
      await request(`/api/v1/data/assets/${assetId}`, {
        method: 'DELETE'
      });
      await loadAssets();
      setSettings(prev => ({
        ...prev,
        docTypesVersion: (prev.docTypesVersion || 0) + 1
      }));
    } catch (err: any) {
      const msg =
        err?.detail ||
        err?.message ||
        uiText('delete');
      setError(msg);
    }
  };

  const filteredAssets = assets.filter(a =>
    [a.original_name, a.name, a.doc_type]
      .filter(Boolean)
      .some(value =>
        (value as string).toLowerCase().includes(search.toLowerCase())
      )
  );

  const toggleSelect = (assetId: number, checked: boolean) => {
    setSelectedIds(prev =>
      checked ? [...prev, assetId] : prev.filter(id => id !== assetId)
    );
  };

  const toggleSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filteredAssets.map(a => a.asset_id));
    }
  };

  const canEditDocType = (asset: Asset): boolean => {
    if (currentUserIsAdmin) return true;
    if (currentUserId == null) return false;
    return asset.user_id === currentUserId;
  };

  const handleStartEditDocType = (asset: Asset) => {
    if (!canEditDocType(asset)) return;
    setEditingDocTypeId(asset.asset_id);
    setEditingDocTypeValue(asset.doc_type || '');
  };

  const handleSaveDocType = async (assetId: number) => {
    const value = editingDocTypeValue.trim() || 'general';
    setSavingDocType(true);
    setError(null);
    try {
      await request(`/api/v1/data/assets/${assetId}/doc-type`, {
        method: 'PATCH',
        body: JSON.stringify({ doc_type: value })
      });
      setAssets(prev =>
        prev.map(a =>
          a.asset_id === assetId ? { ...a, doc_type: value } : a
        )
      );
      setSettings(prev => ({
        ...prev,
        docTypesVersion: (prev.docTypesVersion || 0) + 1
      }));
      setEditingDocTypeId(null);
      setEditingDocTypeValue('');
    } catch (err: any) {
      const msg =
        err?.detail ||
        err?.message ||
        'Failed to update document type.';
      setError(msg);
    } finally {
      setSavingDocType(false);
    }
  };

  const handleCancelEditDocType = () => {
    setEditingDocTypeId(null);
    setEditingDocTypeValue('');
  };

  return (
    <section className="flex-1 overflow-y-auto p-4 space-y-3">
      <div className="app-card-soft px-5 py-3 flex items-center justify-between">
        <h1 className="text-sm font-semibold text-slate-900">
          {uiText('adminFiles')}
        </h1>
        <div className="flex items-center gap-3">
          <input
            className="rounded-full bg-white border border-slate-200 px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            placeholder={uiText('searchAssetsPlaceholder')}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <button
            type="button"
            onClick={loadAssets}
            className="btn-chip px-3 py-1 text-xs"
          >
            {uiText('refresh')}
          </button>
          <button
            type="button"
            disabled={selectedIds.length === 0}
            onClick={() => setShowBulkDelete(true)}
            className="btn-action btn-action-danger px-3 py-1 text-xs disabled:opacity-40"
          >
            {uiText('deleteSelected')} ({selectedIds.length})
          </button>
        </div>
      </div>
      {error && <div className="text-xs text-red-500">{error}</div>}
      {loading && (
        <div className="text-xs text-slate-400">{uiText('loadingAssets')}</div>
      )}
      {!loading && filteredAssets.length === 0 && (
        <div className="text-xs text-slate-500">
          {uiText('noAssets')}
        </div>
      )}
      {filteredAssets.length > 0 && (
        <div className="overflow-x-auto app-card mt-2">
          <table
            className={`min-w-full text-xs ${isRTL ? 'text-right' : 'text-left'}`}
            dir={isRTL ? 'rtl' : 'ltr'}
          >
            <thead className="bg-slate-50">
              <tr>
                <th className={`px-3 py-2 border-b border-slate-200 ${isRTL ? 'text-right' : 'text-left'}`}>
                  <input
                    type="checkbox"
                    checked={
                      filteredAssets.length > 0 &&
                      selectedIds.length === filteredAssets.length
                    }
                    onChange={e => toggleSelectAll(e.target.checked)}
                  />
                </th>
                <th className={`px-3 py-2 border-b border-slate-200 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('id')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('name')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('docType')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('size')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('private')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('visibility')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('created')}
                </th>
                <th className="px-2 py-1 border-b border-slate-800 text-right">
                  {uiText('actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredAssets.map(a => (
                <tr key={a.asset_id} className="odd:bg-white even:bg-slate-50/60 hover:bg-sky-50 transition">
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(a.asset_id)}
                      onChange={e => toggleSelect(a.asset_id, e.target.checked)}
                    />
                  </td>
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    <div className="max-w-xs truncate text-slate-700 font-medium">
                      {a.asset_id}
                    </div>
                  </td>
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    <div className="max-w-xs truncate text-slate-700">
                      {a.original_name || a.name}
                    </div>
                  </td>
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {editingDocTypeId === a.asset_id ? (
                      <div className="flex items-center gap-1">
                        <input
                          className="w-full rounded bg-slate-950 border border-slate-700 px-1 py-0.5 text-[11px]"
                          value={editingDocTypeValue}
                          onChange={e =>
                            setEditingDocTypeValue(e.target.value)
                          }
                          disabled={savingDocType}
                        />
                        <button
                          type="button"
                          className="text-[10px] text-theme-accent"
                          disabled={savingDocType}
                          onClick={() => handleSaveDocType(a.asset_id)}
                        >
                          {uiText('save')}
                        </button>
                        <button
                          type="button"
                          className="text-[10px] text-theme-muted"
                          disabled={savingDocType}
                          onClick={handleCancelEditDocType}
                        >
                          {uiText('cancel')}
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between gap-1">
                        <span>{a.doc_type || '-'}</span>
                        {canEditDocType(a) && (
                          <button
                            type="button"
                            className="btn-chip px-2 py-0.5 text-[10px]"
                            onClick={() => handleStartEditDocType(a)}
                          >
                            {uiText('edit')}
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 border-b border-slate-100">
                    {a.size != null ? `${a.size} ${uiText('bytes')}` : '—'}
                  </td>
                  <td className="px-3 py-2 border-b border-slate-100">
                    {a.is_private ? uiText('yes') || 'Yes' : uiText('no') || 'No'}
                  </td>
                  <td className="px-3 py-2 border-b border-slate-100">
                    {a.visibility === 'department'
                      ? `${uiText('department')}: ${Array.isArray(a.department) ? a.department.join(', ') : a.department || '—'}`
                      : a.visibility === 'global'
                      ? uiText('public')
                      : uiText('private')}
                  </td>
                  <td className="px-2 py-1 border-b border-slate-900">
                    {a.created_at
                      ? new Date(a.created_at).toLocaleString()
                      : '-'}
                  </td>
                  <td className="px-3 py-2 border-b border-slate-100 text-right space-x-2">
                    <button
                      type="button"
                      onClick={() =>
                        navigate(
                          `/chat?project=${a.project_id}&asset_id=${a.asset_id}`
                        )
                      }
                      className="btn-action px-3 py-1 text-[11px]"
                    >
                      {uiText('navChat')}
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        navigate(
                          `/chat?project=${a.project_id}&asset_id=${a.asset_id}&mode=summary`
                        )
                      }
                      className="btn-action px-3 py-1 text-[11px]"
                    >
                      {uiText('summarizeAction')}
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(a)}
                      className="btn-action btn-action-danger px-3 py-1 text-[11px]"
                    >
                      {uiText('delete')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {deleteTarget && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.45)] backdrop-blur-sm p-4">
          <div className="app-card w-full max-w-sm p-5 text-xs space-y-3">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-theme-muted">
                {uiText('deleteFileTitle')}
              </p>
              <h3 className="text-lg font-semibold text-slate-900">
                {uiLanguage === 'ar'
                  ? 'حذف هذا الملف؟'
                  : 'Delete this file?'}
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                {uiText('deleteFileBody')} &quot;
                {deleteTarget.original_name || deleteTarget.name || uiText('file')}&quot;
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-chip px-4 py-2"
                onClick={() => setDeleteTarget(null)}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="btn-action btn-action-danger px-4 py-2"
                onClick={async () => {
                  await handleDelete(deleteTarget.asset_id);
                  setDeleteTarget(null);
                }}
              >
                {uiText('delete')}
              </button>
            </div>
          </div>
        </div>
      )}
      {showBulkDelete && selectedIds.length > 0 && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.45)] backdrop-blur-sm p-4">
          <div className="app-card w-full max-w-md p-5 text-xs space-y-3">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-theme-muted">
                {uiText('bulkDeleteTitle')}
              </p>
              <h3 className="text-lg font-semibold text-slate-900">
                {uiLanguage === 'ar'
                  ? 'حذف الملفات المحددة'
                  : 'Delete selected items'}
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                {uiLanguage === 'ar'
                  ? `سيتم حذف ${selectedIds.length} ملف وفهارسها بشكل دائم.`
                  : `This will permanently remove ${selectedIds.length} file${selectedIds.length > 1 ? 's' : ''} and their indexed vectors.`}
              </p>
            </div>
            <div className="flex justify-end gap-2 text-xs">
              <button
                type="button"
                className="btn-chip px-4 py-2"
                onClick={() => setShowBulkDelete(false)}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="btn-action btn-action-danger px-4 py-2"
                onClick={async () => {
                  for (const id of selectedIds) {
                    await handleDelete(id);
                  }
                  setSelectedIds([]);
                  setShowBulkDelete(false);
                }}
              >
                {uiText('deleteAll')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
