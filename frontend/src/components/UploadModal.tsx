import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useSettings } from '../settings/SettingsContext';
import { useHttpClient } from '../lib/httpClient';
import { t } from '../i18n/ui';

interface UploadSuccessInfo {
  message: string;
  assetId?: number;
  docType?: string;
}

interface UploadModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (info: UploadSuccessInfo) => void;
}

export const UploadModal: React.FC<UploadModalProps> = ({
  open,
  onClose,
  onSuccess
}) => {
  const {
    defaultProjectId,
    apiBaseUrl,
    basicAuthUser,
    basicAuthPass,
    authToken,
    currentDocType,
    currentUserDepartment,
    currentUserIsAdmin,
    setSettings,
    uiLanguage
  } = useSettings();
  const uiText = (key: Parameters<typeof t>[1]) => t(uiLanguage, key);
  const [files, setFiles] = useState<File[]>([]);
  const [status, setStatus] = useState<'idle' | 'uploading' | 'processing'>(
    'idle'
  );
  const [error, setError] = useState<string | null>(null);
  const [forceOcr, setForceOcr] = useState(false);
  const [docType, setDocType] = useState<string>(
    currentDocType && currentDocType.trim() !== ''
      ? currentDocType
      : 'general'
  );
  const [isPrivate, setIsPrivate] = useState<boolean>(true);
  const [visibility, setVisibility] = useState<'private' | 'department' | 'global'>('private');
  const [departments, setDepartments] = useState<string[]>([]);
  const [deptQuery, setDeptQuery] = useState('');
  const [selectedDepartments, setSelectedDepartments] = useState<string[]>([]);
  const [availableDepartments, setAvailableDepartments] = useState<string[]>([]);
  const [customDepartment, setCustomDepartment] = useState('');
  const [useCustomDepartment, setUseCustomDepartment] = useState(false);
  const [docTypes, setDocTypes] = useState<string[]>([]);
  const [selectedDocType, setSelectedDocType] = useState('');
  const [customDocType, setCustomDocType] = useState('');
  const [useCustomDocType, setUseCustomDocType] = useState(false);
  const { request } = useHttpClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setCustomDocType('');
    setSelectedDocType('');
    setUseCustomDocType(false);
    setForceOcr(false);
    setUseCustomDepartment(false);
    if (!currentUserIsAdmin) {
      const dept = currentUserDepartment || 'Global';
      setDepartments([dept]);
      setSelectedDepartments([dept]);
      setCustomDepartment('');
      return;
    }
    request<{ departments?: string[] }>('/api/v1/users/departments')
      .then(res => {
        const list = Array.isArray(res.departments) ? res.departments : [];
        setDepartments(list);
        if (list.length) {
          const preferred =
            (currentUserDepartment && list.includes(currentUserDepartment)) ||
            false;
          const initial = preferred
            ? (currentUserDepartment as string)
            : list[0];
          setSelectedDepartments([initial]);
        } else {
          const fallback = currentUserDepartment || uiText('adminUsers');
          setDepartments([fallback]);
          setSelectedDepartments([fallback]);
        }
        setCustomDepartment('');
        setDeptQuery('');
      })
      .catch(() => {
        const fallback = currentUserDepartment || uiText('adminUsers');
        setDepartments([fallback]);
        setSelectedDepartments([fallback]);
        setCustomDepartment('');
        setDeptQuery('');
      });
  }, [open, currentUserIsAdmin, currentUserDepartment]);

  const filteredDepartments = useMemo(() => {
    const q = deptQuery.trim().toLowerCase();
    if (!q) return departments;
    return departments.filter(d => d.toLowerCase().includes(q));
  }, [departments, deptQuery]);

  useEffect(() => {
    if (!open) return;
    request<{ doc_types?: string[] }>('/api/v1/nlp/doc-types')
      .then(res => {
        const list = Array.isArray(res.doc_types) ? res.doc_types : [];
        setDocTypes(list);
        if (list.length && !selectedDocType) {
          setSelectedDocType(list[0]);
        }
      })
      .catch(() => {
        setDocTypes([]);
      });
  }, [open, request]);

  if (!open) return null;

  const handleUpload = async () => {
    if (!files.length) return;
    setError(null);
    setStatus('uploading');

    try {
      const form = new FormData();
      files.forEach(f => form.append('files', f));
      const chosenDocType =
        (useCustomDocType
          ? customDocType && customDocType.trim()
          : selectedDocType && selectedDocType.trim()) ||
        docType.trim();
      if (!chosenDocType) {
        setError(uiText('docTypeRequired'));
        setStatus('idle');
        return;
      }
      form.append('doc_type', chosenDocType.trim());
      form.append('force_ocr', forceOcr ? 'true' : 'false');
      form.append('is_private', isPrivate ? 'true' : 'false');
      form.append('visibility', visibility);
      if (visibility === 'department') {
        let deptsToSend: string[] = [];
        if (useCustomDepartment) {
          const custom = customDepartment.trim();
          if (custom) deptsToSend = [custom];
        } else {
          deptsToSend = selectedDepartments.filter(d => d.trim());
        }
        // The backend expects a list, but FormData sends multiple entries for the same key.
        // FastAPI can interpret this as a list, but sometimes it's tricky.
        // A robust way is to send a JSON string and parse it on the backend.
        // However, the current backend seems to expect a list from Form directly.
        deptsToSend.forEach(dept => form.append('department', dept)); // This should work with FastAPI if the endpoint is correct.
      }

      let auth: string | undefined;
      if (authToken) {
        auth = `Bearer ${authToken}`;
      } else if (basicAuthUser && basicAuthPass) {
        auth = `Basic ${btoa(`${basicAuthUser}:${basicAuthPass}`)}`;
      }

      const res = await fetch(
        `${apiBaseUrl.replace(
          /\/$/,
          ''
        )}/api/v1/data/upload/process/index/batch/${defaultProjectId}`,
        {
          method: 'POST',
          headers: {
            ...(auth ? { Authorization: auth } : {})
          },
          body: form
        }
      );

      setStatus('processing');
      const data = await res.json();
      if (!res.ok) {
        const friendlyMessage = uiText('friendlyServerIssue');
        throw new Error(
          res.status >= 500
            ? friendlyMessage
            : data?.detail || uiText('uploadFailed')
        );
      }
      setStatus('idle');
      const first = Array.isArray(data?.files) ? data.files[0] : null;
      const rawAssetId = first?.asset_id ?? data?.asset_id;
      const parsedAssetId =
        typeof rawAssetId === 'number'
          ? rawAssetId
          : rawAssetId != null
          ? Number(rawAssetId)
          : undefined;
      const chunks = data?.indexed_chunks;
      const successMessage =
        Array.isArray(data?.files) && data.files.length > 1
          ? `${uiText('uploadSuccessMulti')} (${data.files.length})`
          : typeof chunks === 'number'
          ? `${uiText('uploadSuccessSingle')} (${chunks} ${uiText('chunks')}).`
          : uiText('uploadSuccessSingle');
      setSettings(prev => ({
        ...prev,
        docTypesVersion: (prev.docTypesVersion || 0) + 1
      }));
      if (onSuccess) {
        onSuccess({
          message: successMessage,
          assetId: Number.isFinite(parsedAssetId) ? parsedAssetId : undefined,
          docType: chosenDocType
        });
      }
      onClose();
    } catch (err: any) {
      setStatus('idle');
      setError(err.message || uiText('uploadFailed'));
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md app-card p-5 text-xs bg-white rounded-3xl shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold">
              {uiText('uploadTitle')}
            </h2>
            <p className="text-[11px] text-slate-500">
              {uiLanguage === 'ar'
                ? 'أضف ملفاتك مع تحديد النوع والرؤية'
                : 'Add files with doc type and visibility in one flow.'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-2 rounded-full border border-[color:var(--border-subtle)] bg-white px-3 py-1 text-[11px] font-semibold text-[color:var(--accent-strong)] shadow-sm hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
          >
            {uiText('close')}
          </button>
        </div>
        <div className="space-y-4">
          <label className="block text-slate-700">
            <span className="mb-2 block font-semibold text-[12px]">{uiText('selectFiles')}</span>
            <div className="flex items-center gap-3 rounded-2xl border border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] px-3 py-3">
              <div className="flex-1">
                <div className="text-[11px] text-slate-500">
                  {files.length > 0
                    ? `${files.length} ${uiText('filesSelected')}`
                    : uiText('noFilesSelected')}
                </div>
                <div className="text-[10px] text-slate-400">
                  {uiLanguage === 'ar'
                    ? 'اسحب الملفات أو اضغط للاختيار'
                    : 'Drag files in or tap select.'}
                </div>
              </div>
              <button
                type="button"
                className="btn-primary-rounded px-3 py-2 text-[11px]"
                onClick={() => fileInputRef.current?.click()}
              >
                {uiText('selectFiles')}
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              multiple
              onChange={e =>
                setFiles(e.target.files ? Array.from(e.target.files) : [])
              }
            />
          </label>
          <div className="rounded-2xl border border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] px-3 py-2">
            <label className="flex items-start gap-2 text-[11px] text-slate-600">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={forceOcr}
                onChange={e => setForceOcr(e.target.checked)}
              />
              <span>
                <span className="block font-semibold text-[12px] text-slate-700">
                  {uiText('forceOcr')}
                </span>
                <span className="block text-[10px] text-slate-500">
                  {uiText('forceOcrHint')}
                </span>
              </span>
            </label>
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-slate-600">
              <span className="block mb-1">{uiText('docType')}</span>
              <div className="flex items-center gap-3 text-[11px] text-slate-500 mb-1">
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="doctype-mode"
                    checked={!useCustomDocType}
                    onChange={() => setUseCustomDocType(false)}
                  />
                  <span>{uiText('chooseExisting')}</span>
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="doctype-mode"
                    checked={useCustomDocType}
                    onChange={() => setUseCustomDocType(true)}
                  />
                  <span>{uiText('enterNew')}</span>
                </label>
              </div>
              {docTypes.length > 0 && (
                <select
                  className="w-full rounded-lg bg-[color:var(--bg-soft)] border border-[color:var(--border-subtle)] px-2 py-1 text-xs mb-1 disabled:bg-slate-100 disabled:text-slate-400"
                  value={selectedDocType}
                  onChange={e => setSelectedDocType(e.target.value)}
                  disabled={useCustomDocType}
                >
                  {docTypes.map(dt => (
                    <option key={dt} value={dt}>
                      {dt}
                    </option>
                  ))}
                </select>
              )}
              <input
                className="w-full rounded-lg bg-[color:var(--bg-soft)] border border-[color:var(--border-subtle)] px-2 py-1 mt-1 text-xs disabled:bg-slate-100 disabled:text-slate-400"
                value={customDocType}
                onChange={e => setCustomDocType(e.target.value)}
                placeholder={
                  docTypes.length
                    ? uiText('docTypePlaceholder')
                    : uiText('docTypePlaceholderRequired')
                }
                disabled={!useCustomDocType}
              />
            </label>
            <div className="flex items-center gap-4">
              <span className="text-slate-600">{uiText('visibilityLabel')}</span>
              <label className="flex items-center gap-1 text-slate-600">
                <input
                  type="radio"
                  name="visibility"
                  checked={visibility === 'private'}
                  onChange={() => {
                    setVisibility('private');
                    setIsPrivate(true);
                  }}
                />
                {uiText('privateOnlyYou')}
              </label>
              <label className="flex items-center gap-1 text-slate-600">
                <input
                  type="radio"
                  name="visibility"
                  checked={visibility === 'department'}
                  onChange={() => {
                    setVisibility('department');
                    setIsPrivate(false);
                  }}
                />
                {uiText('departmentVisibility')}
              </label>
              <label className="flex items-center gap-1 text-slate-600">
                <input
                  type="radio"
                  name="visibility"
                  checked={visibility === 'global'}
                  onChange={() => {
                    setVisibility('global');
                    setIsPrivate(false);
                  }}
                />
                {uiText('globalVisibility')}
              </label>
            </div>
            {visibility === 'department' && (
              <label className="text-xs text-slate-600">
                <span className="block mb-1">
                  {uiText('departmentLabel')}
                {currentUserIsAdmin && (
                  <span className="ml-1 text-[10px] text-sky-400">
                      {uiText('chooseExisting')} / {uiText('enterNew')}
                  </span>
                )}
              </span>
              {currentUserIsAdmin ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-3 text-[11px] text-slate-500">
                    <label className="flex items-center gap-1">
                      <input
                        type="radio"
                        name="dept-mode"
                        checked={!useCustomDepartment}
                        onChange={() => setUseCustomDepartment(false)}
                      />
                      <span>{uiText('chooseExisting')}</span>
                    </label>
                    <label className="flex items-center gap-1">
                      <input
                        type="radio"
                        name="dept-mode"
                        checked={useCustomDepartment}
                        onChange={() => setUseCustomDepartment(true)}
                      />
                      <span>{uiText('enterNew')}</span>
                    </label>
                  </div>
                  <input
                    className="w-full rounded-lg bg-slate-50 border border-slate-200 px-2 py-1 text-[11px] placeholder:text-slate-400 disabled:bg-slate-100 disabled:text-slate-400"
                    placeholder={uiText('searchDepartmentsPlaceholder')}
                    value={deptQuery}
                    onChange={e => setDeptQuery(e.target.value)}
                    disabled={useCustomDepartment}
                  />
                  <div className="max-h-32 overflow-y-auto border border-slate-200 rounded-lg p-2 bg-slate-50">
                    {filteredDepartments.map(dept => (
                      <label key={dept} className="flex items-center gap-2 text-xs">
                        <input
                          type="checkbox"
                          checked={selectedDepartments.includes(dept)}
                          onChange={e => {
                            if (e.target.checked) {
                              setSelectedDepartments(prev => [...prev, dept]);
                            } else {
                              setSelectedDepartments(prev => prev.filter(d => d !== dept));
                            }
                          }}
                          disabled={useCustomDepartment}
                        />
                        {dept}
                      </label>
                    ))}
                  </div>
                  <input
                    className="w-full rounded-lg bg-slate-50 border border-slate-200 px-2 py-1 text-[11px] placeholder:text-slate-400 disabled:bg-slate-100 disabled:text-slate-400"
                    placeholder={uiText('newDepartmentPlaceholder')}
                    value={customDepartment}
                    onChange={e => setCustomDepartment(e.target.value)}
                    disabled={!useCustomDepartment}
                  />
                </div>
                ) : (
                  <div className="w-full rounded-lg bg-slate-50 border border-slate-200 px-2 py-1 text-[11px] text-slate-700">
                    {selectedDepartments[0] || currentUserDepartment || uiText('global')}
                  </div>
                )}
              </label>
            )}
          </div>
          {status !== 'idle' && (
            <div className="flex items-center gap-2 text-slate-500">
              <span className="h-3 w-3 rounded-full border-2 border-sky-500 border-t-transparent animate-spin" />
              {status === 'uploading'
                ? uiText('uploading')
                : uiText('processingIndexing')}
            </div>
          )}
          {error && <div className="text-red-500 text-[11px]">{error}</div>}
          <button
            type="button"
            onClick={handleUpload}
            disabled={files.length === 0 || status !== 'idle'}
            className="mt-2 btn-primary-rounded px-3 py-1 text-xs"
          >
            {uiText('submitUpload')}
          </button>
        </div>
      </div>
    </div>
  );
};
