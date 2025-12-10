import React, { useEffect, useState } from 'react';
import { useHttpClient } from '../lib/httpClient';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

interface RawUserStats {
  totals?: { queries?: number; conversations?: number; documents?: number };
  response_times?: { average_ms?: number };
  time_based?: { weekly_trend?: { week: string; count: number }[] };
  model_preferences?: { counts?: Record<string, number> };
  query_topics?: { topic: string; count: number }[];
  quality?: { average_rating?: number; fallback_count?: number };
  retrieval?: { average_retrieved_chunks?: number };
  engagement?: { conversation_length_buckets?: Record<string, number> };
}

interface UserStatsResponse {
  statistics: RawUserStats;
  activity: unknown;
}

interface UserStatsView {
  total_queries: number;
  total_conversations: number;
  total_documents: number;
  avg_response_ms: number;
  weekly_trend?: { label: string; count: number }[];
  model_usage?: { model: string; count: number }[];
  topics?: { topic: string; count: number }[];
  avg_rating?: number;
  fallback_count?: number;
  avg_retrieved_chunks?: number;
  conversation_length_buckets?: { bucket: string; count: number }[];
}

interface RawSystemStats {
  totals?: { users?: number; documents?: number; conversations?: number; queries?: number };
  document_distribution?: Record<string, number>;
  global_model_usage?: Record<string, number>;
  query_doc_types?: Record<string, number>;
  average_response_time_ms?: number;
  top_users?: { user_id: number; queries: number; username?: string | null; department?: string | null }[];
  engagement?: { dau?: number; wau?: number; new_users_last_7_days?: number };
  quality?: { average_rating?: number; fallback_count?: number };
  department_stats?: {
    queries_by_department?: Record<string, number>;
    usage_by_visibility?: Record<string, number>;
  };
  content_risk?: {
    asset_id: number;
    name?: string;
    doc_type?: string | null;
    visibility?: string;
    department?: string | null;
    queries?: number;
    avg_rating?: number | null;
    fallback_rate?: number;
  }[];
}

interface SystemStatsResponse {
  statistics: RawSystemStats;
}

interface SystemStatsView {
  total_users: number;
  total_documents: number;
  total_conversations: number;
  total_queries: number;
  avg_response_ms: number;
  doc_type_distribution?: { doc_type: string; count: number }[];
  top_users?: { user_id: number; username?: string | null; department?: string | null; queries: number }[];
  avg_rating?: number;
  dau?: number;
  wau?: number;
  new_users_last_7_days?: number;
  queries_by_department?: { department: string; count: number }[];
  usage_by_visibility?: { visibility: string; count: number }[];
  content_risk?: {
    asset_id: number;
    name: string;
    doc_type?: string | null;
    visibility: string;
    department?: string | null;
    queries: number;
    avg_rating?: number | null;
    fallback_rate?: number;
  }[];
}

interface UsersOverviewRow {
  user_id: number;
  username: string;
  department: string | null;
  is_admin: boolean;
  total_queries: number;
  total_conversations: number;
  total_documents: number;
  avg_response_ms: number;
  last_active_at?: string | null;
}

interface UsersOverviewResponse {
  users: UsersOverviewRow[];
  pagination?: { page: number; limit: number; total_users: number; total_pages: number };
}

export const StatsPage: React.FC = () => {
  const { request } = useHttpClient();
  const { currentUserIsAdmin, uiLanguage } = useSettings();
  const uiText = (key: Parameters<typeof t>[1]) => t(uiLanguage, key);
  const isRTL = uiLanguage === 'ar';

  const [tab, setTab] = useState<'me' | 'system' | 'users'>('me');
  const [stats, setStats] = useState<UserStatsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [systemStats, setSystemStats] = useState<SystemStatsView | null>(null);
  const [systemError, setSystemError] = useState<string | null>(null);
  const [usersOverview, setUsersOverview] = useState<UsersOverviewRow[]>([]);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [usersSearch, setUsersSearch] = useState('');
  const [usersPage, setUsersPage] = useState(1);
  const [usersTotalPages, setUsersTotalPages] = useState(1);

  useEffect(() => {
    request<UserStatsResponse>('/api/v1/stats/user')
      .then(res => {
        const s = res.statistics || {};
        const totals = s.totals || {};
        const responseTimes = s.response_times || {};
        const timeBased = s.time_based || {};
        const modelPrefs = s.model_preferences || {};
        const quality = s.quality || {};
        const retrieval = s.retrieval || {};
        const engagement = s.engagement || {};

        const model_usage = modelPrefs.counts
          ? Object.entries(modelPrefs.counts).map(([model, count]) => ({
              model,
              count: count as number
            }))
          : undefined;

        const weekly_trend = timeBased.weekly_trend
          ? timeBased.weekly_trend.map(item => ({
              label: item.week,
              count: item.count
            }))
          : undefined;

        const convBucketsSrc = engagement.conversation_length_buckets || undefined;
        const conversation_length_buckets = convBucketsSrc
          ? Object.entries(convBucketsSrc).map(([bucket, count]) => ({
              bucket,
              count: count as number
            }))
          : undefined;

        const view: UserStatsView = {
          total_queries: totals.queries ?? 0,
          total_conversations: totals.conversations ?? 0,
          total_documents: totals.documents ?? 0,
          avg_response_ms: responseTimes.average_ms ?? 0,
          weekly_trend,
          model_usage,
          topics: s.query_topics,
          avg_rating: quality.average_rating,
          fallback_count: quality.fallback_count,
          avg_retrieved_chunks: retrieval.average_retrieved_chunks,
          conversation_length_buckets
        };
        setStats(view);
      })
      .catch(err => setError(err.message || uiText('loadingStats')));
  }, [request, uiLanguage]);

  useEffect(() => {
    if (!currentUserIsAdmin || tab !== 'system' || systemStats) return;
    setSystemError(null);
    request<SystemStatsResponse>('/api/v1/stats/system')
      .then(res => {
        const raw = res.statistics || {};
        const totals = raw.totals || {};
        const docDist = raw.document_distribution || {};
        const engagement = raw.engagement || {};
        const quality = raw.quality || {};
        const deptStats = raw.department_stats || {};
        const contentRiskRaw = raw.content_risk || [];

        const doc_type_distribution = Object.entries(docDist).map(([doc_type, count]) => ({
          doc_type,
          count: count as number
        }));

        const queriesByDeptSrc = deptStats.queries_by_department || undefined;
        const usageByVisSrc = deptStats.usage_by_visibility || undefined;

        const queries_by_department = queriesByDeptSrc
          ? Object.entries(queriesByDeptSrc).map(([department, count]) => ({
              department,
              count: count as number
            }))
          : undefined;

        const usage_by_visibility = usageByVisSrc
          ? Object.entries(usageByVisSrc).map(([visibility, count]) => ({
              visibility,
              count: count as number
            }))
          : undefined;

        const content_risk = Array.isArray(contentRiskRaw)
          ? contentRiskRaw.map(item => ({
              asset_id: item.asset_id,
              name: item.name ?? `${uiText('asset')} #${item.asset_id}`,
              doc_type: item.doc_type ?? null,
              visibility: item.visibility ?? 'private',
              department: item.department ?? null,
              queries: item.queries ?? 0,
              avg_rating: item.avg_rating ?? null,
              fallback_rate: item.fallback_rate ?? 0
            }))
          : undefined;

        const view: SystemStatsView = {
          total_users: totals.users ?? 0,
          total_documents: totals.documents ?? 0,
          total_conversations: totals.conversations ?? 0,
          total_queries: totals.queries ?? 0,
          avg_response_ms: raw.average_response_time_ms ?? 0,
          doc_type_distribution,
          top_users: raw.top_users,
          avg_rating: quality.average_rating,
          dau: engagement.dau,
          wau: engagement.wau,
          new_users_last_7_days: engagement.new_users_last_7_days,
          queries_by_department,
          usage_by_visibility,
          content_risk
        };
        setSystemStats(view);
      })
      .catch(err => setSystemError(err.message || uiText('loadingStats')));
  }, [request, currentUserIsAdmin, tab, systemStats, uiLanguage]);

  useEffect(() => {
    if (!currentUserIsAdmin || tab !== 'users') return;
    setUsersError(null);
    const params = new URLSearchParams();
    params.set('page', String(usersPage));
    params.set('limit', '20');
    if (usersSearch.trim()) {
      params.set('search', usersSearch.trim());
    }
    request<UsersOverviewResponse>(`/api/v1/stats/users?${params.toString()}`)
      .then(res => {
        setUsersOverview(Array.isArray(res.users) ? res.users : []);
        const meta = res.pagination;
        if (meta && typeof meta.total_pages === 'number') {
          setUsersTotalPages(meta.total_pages || 1);
        } else {
          setUsersTotalPages(1);
        }
      })
      .catch(err => setUsersError(err.message || uiText('loadingStats')));
  }, [request, currentUserIsAdmin, tab, usersPage, usersSearch, uiLanguage]);

  return (
    <section className="flex-1 overflow-y-auto p-4 space-y-4">
      <div className="app-card-soft px-5 py-3 flex items-center justify-between">
        <h1 className="text-base font-semibold text-theme-strong">
          {uiText('stats')}
        </h1>
      </div>

      <div className="flex items-center gap-2 text-xs mt-1">
        <button
          type="button"
          className={`btn-chip px-3 py-1.5 text-[11px] ${
            tab === 'me' ? 'btn-chip-active' : ''
          }`}
          onClick={() => setTab('me')}
        >
          {uiText('myStats')}
        </button>
        {currentUserIsAdmin && (
          <>
            <button
              type="button"
              className={`btn-chip px-3 py-1.5 text-[11px] ${
                tab === 'system' ? 'btn-chip-active' : ''
              }`}
              onClick={() => setTab('system')}
            >
              {uiText('systemTab')}
            </button>
            <button
              type="button"
              className={`btn-chip px-3 py-1.5 text-[11px] ${
                tab === 'users' ? 'btn-chip-active' : ''
              }`}
              onClick={() => setTab('users')}
            >
              {uiText('usersTab')}
            </button>
          </>
        )}
      </div>

      {tab === 'me' && (
        <>
          {error && <div className="text-xs text-theme-danger">{error}</div>}
          {!stats && !error && (
            <div className="text-xs text-theme-muted">{uiText('loadingStats')}</div>
          )}
          {stats && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('totalQueries')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {stats.total_queries}
                  </div>
                </div>
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('conversations')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {stats.total_conversations}
                  </div>
                </div>
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('documents')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {stats.total_documents}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-1 gap-3 text-xs mt-3">
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('averageRating')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {stats.avg_rating != null ? stats.avg_rating.toFixed(1) : uiText('noStats')}
                  </div>
                </div>
              </div>

              {stats.conversation_length_buckets && stats.conversation_length_buckets.length > 0 && (
                <div className="app-card p-3 text-xs mt-3">
                  <div className="mb-2 font-semibold text-theme-strong">
                    {uiText('conversationLengths')}
                  </div>
                  <div className="flex gap-4">
                    {stats.conversation_length_buckets.map(b => (
                      <div key={b.bucket} className="flex flex-col text-[11px]">
                        <span className="text-theme-strong">{b.bucket}</span>
                        <span className="text-theme-muted">
                          {b.count} {uiText('conversations')}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}

      {tab === 'system' && currentUserIsAdmin && (
        <>
          {systemError && <div className="text-xs text-theme-danger">{systemError}</div>}
          {!systemStats && !systemError && (
            <div className="text-xs text-theme-muted">{uiText('loadingStats')}</div>
          )}
          {systemStats && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mt-3">
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('users')}</div>
                  <div className="text-lg font-semibold stat-value">{systemStats.total_users}</div>
                </div>
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('documents')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {systemStats.total_documents}
                  </div>
                </div>
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('conversations')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {systemStats.total_conversations}
                  </div>
                </div>
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('totalQueries')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {systemStats.total_queries}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs mt-3">
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('dailyActive')}</div>
                  <div className="text-lg font-semibold stat-value">{systemStats.dau ?? 0}</div>
                </div>
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('weeklyActive')}</div>
                  <div className="text-lg font-semibold stat-value">{systemStats.wau ?? 0}</div>
                </div>
                <div className="app-card p-3">
                  <div className="stat-label">{uiText('newUsers7d')}</div>
                  <div className="text-lg font-semibold stat-value">
                    {systemStats.new_users_last_7_days ?? 0}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                {systemStats.doc_type_distribution && systemStats.doc_type_distribution.length > 0 && (
                  <div className="app-card p-3">
                    <div className="mb-2 font-semibold text-theme-strong">{uiText('documentsByType')}</div>
                    <div className="flex flex-wrap gap-2">
                      {systemStats.doc_type_distribution.map(d => (
                        <span key={d.doc_type} className="stat-chip">
                          <span>{d.doc_type}</span>
                          <span className="stat-chip-value">{d.count}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {systemStats.top_users && systemStats.top_users.length > 0 && (
                <div className="app-card p-3 text-xs">
                  <div className="mb-2 font-semibold text-theme-strong">{uiText('topUsersByQueries')}</div>
                  <div className="flex flex-wrap gap-2">
                    {systemStats.top_users.map(u => (
                      <span key={u.user_id} className="stat-chip stat-chip-accent">
                        <span>{u.username || `${uiText('user')} #${u.user_id}`}</span>
                        {u.department && (
                          <span className="stat-chip-muted">— {u.department}</span>
                        )}
                        <span className="stat-chip-value">
                          {u.queries} {uiText('queries')}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {systemStats.queries_by_department && systemStats.queries_by_department.length > 0 && (
                <div className="app-card p-3 text-xs">
                  <div className="mb-2 font-semibold text-theme-strong">{uiText('queriesByDepartment')}</div>
                  <div className="flex flex-wrap gap-2">
                    {systemStats.queries_by_department.map(d => (
                      <span key={d.department} className="stat-chip">
                        <span>{d.department}</span>
                        <span className="stat-chip-value">{d.count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {systemStats.usage_by_visibility && systemStats.usage_by_visibility.length > 0 && (
                <div className="app-card p-3 text-xs">
                  <div className="mb-2 font-semibold text-theme-strong">{uiText('documentsByVisibility')}</div>
                  <div className="flex flex-wrap gap-2">
                    {systemStats.usage_by_visibility.map(v => (
                      <span key={v.visibility} className="stat-chip">
                        <span>{v.visibility}</span>
                        <span className="stat-chip-value">{v.count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {systemStats.content_risk && systemStats.content_risk.length > 0 && (
                <div className="app-card p-3 text-xs">
                  <div className="mb-2 font-semibold text-theme-strong">{uiText('contentRisk')}</div>
                  <div className="overflow-x-auto">
                    <table className="theme-table text-[11px]">
                      <thead>
                        <tr>
                          <th className="px-3 py-2 text-left">
                            {uiText('documents')}
                          </th>
                          <th className="px-3 py-2 text-left">
                            {uiText('docType')}
                          </th>
                          <th className="px-3 py-2 text-left">
                            {uiText('visibility')}
                          </th>
                          <th className="px-3 py-2 text-left">
                            {uiText('department')}
                          </th>
                          <th className="px-3 py-2 text-right">
                            {uiText('queriesLabel')}
                          </th>
                          <th className="px-3 py-2 text-right">
                            {uiText('averageRating')}
                          </th>
                          <th className="px-3 py-2 text-right">
                            {uiText('fallback') || 'Fallback %'}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {systemStats.content_risk.map(doc => (
                          <tr key={doc.asset_id}>
                            <td className="px-3 py-2">
                              <div className="max-w-xs truncate text-theme-strong">{doc.name}</div>
                            </td>
                            <td className="px-3 py-2">
                              <span className="text-theme-muted">{doc.doc_type || '-'}</span>
                            </td>
                            <td className="px-3 py-2 capitalize">
                              <span className="text-theme-muted">{doc.visibility}</span>
                            </td>
                            <td className="px-3 py-2">
                              <span className="text-theme-muted">{doc.department || '-'}</span>
                            </td>
                            <td className="px-3 py-2 text-right">
                              <span className="text-theme-strong">{doc.queries}</span>
                            </td>
                            <td className="px-3 py-2 text-right">
                              {doc.avg_rating != null ? doc.avg_rating.toFixed(1) : '-'}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {doc.fallback_rate != null
                                ? `${(doc.fallback_rate * 100).toFixed(0)}%`
                                : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}

      {tab === 'users' && currentUserIsAdmin && (
        <>
          <div className="flex items-center justify-between gap-2 text-xs">
            <input
              className="flex-1 input-pill"
              placeholder={uiText('searchUsersPlaceholder')}
              value={usersSearch}
              onChange={e => {
                setUsersPage(1);
                setUsersSearch(e.target.value);
              }}
            />
            <div className="text-[11px] text-theme-muted">
              {uiText('page')} {usersPage} / {usersTotalPages}
            </div>
          </div>

          {usersError && <div className="text-xs text-theme-danger mt-2">{usersError}</div>}
          {!usersError && usersOverview.length === 0 && (
            <div className="text-xs text-theme-muted mt-2">
              {usersSearch ? uiText('noUsersMatch') : uiText('noUserStats')}
            </div>
          )}
          {usersOverview.length > 0 && (
            <div className="mt-2 overflow-x-auto app-card">
              <table
                className={`theme-table text-[11px] ${isRTL ? 'text-right' : 'text-left'}`}
                dir={isRTL ? 'rtl' : 'ltr'}
              >
                <thead>
                  <tr>
                    <th className={`px-3 py-2 text-[11px] font-semibold tracking-wide uppercase text-theme-muted ${isRTL ? 'text-right' : 'text-left'}`}>
                      {uiText('users')}
                    </th>
                    <th className={`px-3 py-2 text-[11px] font-semibold tracking-wide uppercase text-theme-muted ${isRTL ? 'text-right' : 'text-left'}`}>
                      {uiText('department')}
                    </th>
                    <th className="px-3 py-2 text-right text-[11px] font-semibold tracking-wide uppercase text-theme-muted">
                      {uiText('queries')}
                    </th>
                    <th className="px-3 py-2 text-right text-[11px] font-semibold tracking-wide uppercase text-theme-muted">
                      {uiText('conversations')}
                    </th>
                    <th className="px-3 py-2 text-right text-[11px] font-semibold tracking-wide uppercase text-theme-muted">
                      {uiText('documents')}
                    </th>
                    <th className="px-3 py-2 text-right text-[11px] font-semibold tracking-wide uppercase text-theme-muted">
                      {uiText('avgMs')}
                    </th>
                    <th className={`px-3 py-2 text-[11px] font-semibold tracking-wide uppercase text-theme-muted ${isRTL ? 'text-right' : 'text-left'}`}>
                      {uiText('lastActive')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {usersOverview.map(u => (
                    <tr key={u.user_id}>
                      <td className={`px-3 py-2 ${isRTL ? 'text-right' : 'text-left'}`}>
                        <span className="font-medium text-theme-strong">{u.username}</span>
                        {u.is_admin && (
                          <span className="ml-1 rounded-full border px-2 py-0.5 text-[9px] text-theme-accent border-[var(--border-subtle)] bg-[var(--bg-soft)]">
                            {uiText('admin')}
                          </span>
                        )}
                      </td>
                      <td className={`px-3 py-2 ${isRTL ? 'text-right' : 'text-left'}`}>
                        <span className="text-theme-muted">{u.department || '—'}</span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="text-theme-strong">{u.total_queries}</span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="text-theme-strong">{u.total_conversations}</span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="text-theme-strong">{u.total_documents}</span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="text-theme-strong">{u.avg_response_ms}</span>
                      </td>
                      <td className="px-3 py-2">
                        {u.last_active_at ? new Date(u.last_active_at).toLocaleString() : '—'}
                     </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
};
