import React, { useEffect, useMemo, useState } from 'react';
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
  departments?: string[] | null;
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
  const [visibilityModalAsset, setVisibilityModalAsset] = useState<Asset | null>(null);
  const [visibilityValue, setVisibilityValue] = useState<'private' | 'department' | 'global'>('private');
  const [availableDepartments, setAvailableDepartments] = useState<string[]>([]);
  const [visibilityDeptQuery, setVisibilityDeptQuery] = useState('');
  const [visibilityDeptSelection, setVisibilityDeptSelection] = useState<string[]>([]);
  const [visibilityNewDepartment, setVisibilityNewDepartment] = useState('');
  const [savingVisibility, setSavingVisibility] = useState(false);
  const [visibilityError, setVisibilityError] = useState<string | null>(null);

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

  const getAssetDepartments = (asset: Asset): string[] => {
    if (Array.isArray(asset.department)) {
      return asset.department.filter(Boolean);
    }
    if (Array.isArray(asset.departments)) {
      return asset.departments.filter(Boolean);
    }
    if (typeof asset.department === 'string' && asset.department.trim()) {
      return [asset.department.trim()];
    }
    return [];
  };

  useEffect(() => {
    if (!currentUserIsAdmin) return;
    request<{ departments?: string[] }>('/api/v1/users/departments')
      .then(res => {
        const list = Array.isArray(res.departments) ? res.departments : [];
        setAvailableDepartments(list);
      })
      .catch(() => setAvailableDepartments([]));
  }, [request, currentUserIsAdmin]);

  const filteredVisibilityDepartments = useMemo(() => {
    const q = visibilityDeptQuery.trim().toLowerCase();
    if (!q) return availableDepartments;
    return availableDepartments.filter(d => d.toLowerCase().includes(q));
  }, [availableDepartments, visibilityDeptQuery]);

  const toggleVisibilityDepartment = (dept: string) => {
    const trimmed = dept.trim();
    if (!trimmed) return;
    setVisibilityDeptSelection(prev => {
      const exists = prev.some(d => d.toLowerCase() === trimmed.toLowerCase());
      if (exists) {
        return prev.filter(d => d.toLowerCase() !== trimmed.toLowerCase());
      }
      return [...prev, trimmed];
    });
  };

  const addVisibilityDepartment = () => {
    const trimmed = visibilityNewDepartment.trim();
    if (!trimmed) return;
    if (!availableDepartments.some(d => d.toLowerCase() === trimmed.toLowerCase())) {
      setAvailableDepartments(prev => [...prev, trimmed]);
    }
    if (!visibilityDeptSelection.some(d => d.toLowerCase() === trimmed.toLowerCase())) {
      setVisibilityDeptSelection(prev => [...prev, trimmed]);
    }
    setVisibilityNewDepartment('');
  };

  const openVisibilityModal = (asset: Asset) => {
    setVisibilityModalAsset(asset);
    const vis = (asset.visibility || (asset.is_private ? 'private' : 'global') || 'private')
      .toString()
      .toLowerCase();
    setVisibilityValue(vis === 'department' ? 'department' : vis === 'global' ? 'global' : 'private');
    const currentDepartments = getAssetDepartments(asset);
    setVisibilityDeptSelection(currentDepartments);
    setVisibilityDeptQuery('');
    setVisibilityNewDepartment('');
    setVisibilityError(null);
  };

  const closeVisibilityModal = () => {
    if (savingVisibility) return;
    setVisibilityModalAsset(null);
    setVisibilityDeptSelection([]);
    setVisibilityError(null);
  };

  const handleSaveVisibility = async () => {
    if (!visibilityModalAsset) return;
    if (visibilityValue === 'department' && visibilityDeptSelection.length === 0) {
      setVisibilityError(
        uiLanguage === 'ar'
          ? 'يرجى اختيار قسم واحد على الأقل.'
          : 'Please select at least one department.'
      );
      return;
    }
    setVisibilityError(null);
    setSavingVisibility(true);
    try {
      const body =
        visibilityValue === 'department'
          ? { visibility: visibilityValue, departments: visibilityDeptSelection }
          : { visibility: visibilityValue, departments: [] };
      await request(`/api/v1/data/assets/${visibilityModalAsset.asset_id}/visibility`, {
        method: 'PATCH',
        body: JSON.stringify(body)
      });
      setAssets(prev =>
        prev.map(a =>
          a.asset_id === visibilityModalAsset.asset_id
            ? {
                ...a,
                visibility: visibilityValue,
                is_private: visibilityValue === 'private',
                department:
                  visibilityValue === 'department' ? [...visibilityDeptSelection] : null,
                departments:
                  visibilityValue === 'department' ? [...visibilityDeptSelection] : []
              }
            : a
        )
      );
      closeVisibilityModal();
    } catch (err: any) {
      setError(err?.detail || err?.message || uiText('edit'));
    } finally {
      setSavingVisibility(false);
    }
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
                    <div className="max-w-xs truncate text-slate-700">
                      {a.original_name || a.name}
                    </div>
                  </td>
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {editingDocTypeId === a.asset_id ? (
                      <div className="inline-flex flex-wrap items-center gap-2 rounded-2xl border border-[color:var(--border-subtle)] bg-white px-2 py-1 shadow-sm">
                        <input
                          className="w-32 rounded-full border border-transparent bg-[color:var(--bg-soft)] px-3 py-1 text-xs focus:border-[color:var(--accent)] focus:outline-none"
                          value={editingDocTypeValue}
                          onChange={e => setEditingDocTypeValue(e.target.value)}
                          disabled={savingDocType}
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              handleSaveDocType(a.asset_id);
                            }
                          }}
                        />
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            className="btn-action px-3 py-1 text-[10px]"
                            disabled={savingDocType}
                            onClick={() => handleSaveDocType(a.asset_id)}
                          >
                            {uiText('save')}
                          </button>
                          <button
                            type="button"
                            className="btn-chip px-3 py-1 text-[10px]"
                            disabled={savingDocType}
                            onClick={handleCancelEditDocType}
                          >
                            {uiText('cancel')}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-slate-800">
                          {a.doc_type || '-'}
                        </span>
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
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        {a.visibility === 'department' ? (
                          <div className="flex flex-col gap-1">
                            <span className="text-[11px] font-semibold text-slate-600">
                              {uiText('department')}
                            </span>
                            <div className="flex flex-wrap gap-1">
                              {getAssetDepartments(a).length === 0 && (
                                <span className="text-slate-500">—</span>
                              )}
                              {getAssetDepartments(a).map(dept => (
                                <span
                                  key={`${a.asset_id}-${dept}`}
                                  className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-700"
                                >
                                  {dept}
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : a.visibility === 'global' ? (
                          <span className="text-slate-700">{uiText('public')}</span>
                        ) : (
                          <span className="text-slate-700">{uiText('private')}</span>
                        )}
                      </div>
                      {currentUserIsAdmin && (
                        <button
                          type="button"
                          className="btn-chip px-2 py-0.5 text-[10px]"
                          onClick={() => openVisibilityModal(a)}
                        >
                          {uiText('edit')}
                        </button>
                      )}
                    </div>
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
      {visibilityModalAsset && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.45)] backdrop-blur-sm p-4">
          <div className="app-card w-full max-w-md p-6 space-y-4 text-xs">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-theme-muted">
                {uiLanguage === 'ar' ? 'تحديث الرؤية' : 'Update visibility'}
              </p>
              <h3 className="text-lg font-semibold text-slate-900">
                {visibilityModalAsset.original_name || visibilityModalAsset.name}
              </h3>
              <p className="text-xs text-theme-muted mt-1">
                {uiLanguage === 'ar'
                  ? 'حدد مستوى الرؤية وأي أقسام يمكنها الوصول إلى الملف.'
                  : 'Choose who can access this document and manage department access.'}
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-[11px] font-semibold text-slate-600">
                {uiLanguage === 'ar' ? 'الرؤية' : 'Visibility'}
              </label>
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-600">
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="visibility-mode"
                    checked={visibilityValue === 'private'}
                    onChange={() => setVisibilityValue('private')}
                  />
                  {uiText('private')}
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="visibility-mode"
                    checked={visibilityValue === 'department'}
                    onChange={() => setVisibilityValue('department')}
                  />
                  {uiText('department')}
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="visibility-mode"
                    checked={visibilityValue === 'global'}
                    onChange={() => setVisibilityValue('global')}
                  />
                  {uiText('public')}
                </label>
              </div>
            </div>
            {visibilityValue === 'department' && (
              <div className="space-y-2 rounded-2xl border border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] p-3">
                <label className="text-[11px] font-semibold text-slate-600">
                  {uiText('department')}
                </label>
                <input
                  className="w-full rounded-full bg-white border border-[color:var(--border-subtle)] px-3 py-1 text-[11px] placeholder:text-slate-400"
                  placeholder={uiLanguage === 'ar' ? 'ابحث عن قسم...' : 'Search departments...'}
                  value={visibilityDeptQuery}
                  onChange={e => setVisibilityDeptQuery(e.target.value)}
                />
                <div className="max-h-36 overflow-y-auto rounded-2xl border border-[color:var(--border-subtle)] bg-white/80 p-2 space-y-1">
                  {filteredVisibilityDepartments.length === 0 && (
                    <div className="text-[11px] text-slate-400">
                      {uiLanguage === 'ar' ? 'لا توجد أقسام' : 'No departments found'}
                    </div>
                  )}
                  {filteredVisibilityDepartments.map(dept => {
                    const isChecked = visibilityDeptSelection.some(
                      d => d.toLowerCase() === dept.toLowerCase()
                    );
                    return (
                      <label
                        key={dept}
                        className="flex items-center gap-2 rounded-xl px-2 py-1 text-[11px] text-slate-600 hover:bg-[color:var(--bg-soft)]"
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleVisibilityDepartment(dept)}
                        />
                        <span>{dept}</span>
                      </label>
                    );
                  })}
                </div>
                <div className="flex items-center gap-2">
                  <input
                    className="flex-1 rounded-full bg-white border border-[color:var(--border-subtle)] px-3 py-1 text-[11px] placeholder:text-slate-400"
                    placeholder={uiLanguage === 'ar' ? 'إضافة قسم جديد' : 'Enter a new department name'}
                    value={visibilityNewDepartment}
                    onChange={e => setVisibilityNewDepartment(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        addVisibilityDepartment();
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="btn-chip px-3 py-1 text-[11px]"
                    onClick={addVisibilityDepartment}
                  >
                    {uiLanguage === 'ar' ? 'إضافة' : 'Add'}
                  </button>
                </div>
                {visibilityDeptSelection.length > 0 && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {visibilityDeptSelection.map(dept => (
                      <span
                        key={`${visibilityModalAsset.asset_id}-${dept}`}
                        className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-[11px] text-slate-700 border border-[color:var(--border-subtle)] shadow-sm"
                      >
                        {dept}
                        <button
                          type="button"
                          className="text-slate-400 hover:text-slate-600"
                          onClick={() => toggleVisibilityDepartment(dept)}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
            {visibilityError && (
              <div className="text-[11px] text-red-500">{visibilityError}</div>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-chip px-4 py-2"
                onClick={closeVisibilityModal}
                disabled={savingVisibility}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="btn-action px-4 py-2"
                onClick={handleSaveVisibility}
                disabled={savingVisibility}
              >
                {savingVisibility ? uiText('loading') : uiText('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
