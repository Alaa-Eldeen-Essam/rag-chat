import React, { useEffect, useState } from 'react';
import { useHttpClient } from '../lib/httpClient';
import { useSettings } from '../settings/SettingsContext';
import { t } from '../i18n/ui';

type Role = 'user' | 'admin';
type RoleFilter = 'all' | Role;

interface UserRow {
  id: number;
  username: string;
  is_admin: boolean;
  department?: string | null;
  created_at?: string | null;
  last_login?: string | null;
}

interface UsersResponse {
  users?: UserRow[];
  total?: number;
  page?: number;
  limit?: number;
}

export const AdminUsersPage: React.FC = () => {
  const { request } = useHttpClient();
  const { uiLanguage } = useSettings();
  const uiText = (key: Parameters<typeof t>[1]) => t(uiLanguage, key);
  const isRTL = uiLanguage === 'ar';

  // Create user form
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<Role>('user');
  const [newDepartment, setNewDepartment] = useState('');
  const [creating, setCreating] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // List + search + editing
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [editingDeptId, setEditingDeptId] = useState<number | null>(null);
  const [editingDeptValue, setEditingDeptValue] = useState('');
  const [editingUsernameId, setEditingUsernameId] = useState<number | null>(
    null
  );
  const [editingUsernameValue, setEditingUsernameValue] = useState('');
  const [roleFilter, setRoleFilter] = useState<RoleFilter>('all');
  const [userPendingDelete, setUserPendingDelete] = useState<UserRow | null>(null);
  const [deletingUserId, setDeletingUserId] = useState<number | null>(null);

  const pageSize = 50;

  const loadUsers = async (pageNo: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await request<UsersResponse>(
        `/api/v1/users/?page=${pageNo}&limit=${pageSize}`
      );
      setUsers(Array.isArray(res.users) ? res.users : []);
      setTotal(res.total ?? 0);
      setPage(res.page ?? pageNo);
    } catch (err: any) {
      setError(err.message || uiText('loadingUsers'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers(1);
  }, [uiLanguage]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername || !newPassword) return;
    setCreating(true);
    setError(null);
    try {
      const body: any = {
        username: newUsername,
        password: newPassword,
        role: newRole,
        department:
          newRole === 'admin'
            ? newDepartment || uiText('adminUsers')
            : newDepartment || uiText('global')
      };
      await request('/api/v1/users/create', {
        method: 'POST',
        body: JSON.stringify(body)
      });
      setNewUsername('');
      setNewPassword('');
      setNewRole('user');
      setNewDepartment('');
      await loadUsers(page);
    } catch (err: any) {
      setError(err.message || uiText('createUser'));
    } finally {
      setCreating(false);
    }
  };

  const handleToggleAdmin = async (user: UserRow) => {
    try {
      await request(`/api/v1/users/users/${user.id}/admin`, {
        method: 'PATCH',
        body: JSON.stringify({ is_admin: !user.is_admin })
      });
      setUsers(prev =>
        prev.map(u =>
          u.id === user.id ? { ...u, is_admin: !u.is_admin } : u
        )
      );
    } catch (err: any) {
      setError(err.message || uiText('edit'));
    }
  };

  const handleSaveDepartment = async (userId: number) => {
    const value = editingDeptValue.trim();
    if (!value) return;
    try {
      await request(`/api/v1/users/users/${userId}/department`, {
        method: 'PATCH',
        body: JSON.stringify({ department: value })
      });
      setUsers(prev =>
        prev.map(u =>
          u.id === userId ? { ...u, department: value } : u
        )
      );
      setEditingDeptId(null);
      setEditingDeptValue('');
    } catch (err: any) {
      setError(err.message || uiText('edit'));
    }
  };

  const handleSaveUsername = async (userId: number) => {
    const value = editingUsernameValue.trim();
    if (!value) return;
    try {
      await request(`/api/v1/users/users/${userId}`, {
        method: 'PATCH',
        body: JSON.stringify({ username: value })
      });
      setUsers(prev =>
        prev.map(u =>
          u.id === userId ? { ...u, username: value } : u
        )
      );
      setEditingUsernameId(null);
      setEditingUsernameValue('');
    } catch (err: any) {
      setError(err.message || uiText('edit'));
    }
  };

  const handleResetPassword = async (user: UserRow) => {
    try {
      await request(`/api/v1/users/users/${user.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ reset_password: true })
      });
    } catch (err: any) {
      setError(err.message || uiText('resetPassword'));
    }
  };

  const requestDeleteUser = (user: UserRow) => {
    setUserPendingDelete(user);
    setError(null);
  };

  const confirmDeleteUser = async () => {
    if (!userPendingDelete) return;
    setDeletingUserId(userPendingDelete.id);
    try {
      await request(`/api/v1/users/users/${userPendingDelete.id}`, {
        method: 'DELETE'
      });
      setUsers(prev => prev.filter(u => u.id !== userPendingDelete.id));
      setUserPendingDelete(null);
    } catch (err: any) {
      setError(err.message || uiText('delete'));
    } finally {
      setDeletingUserId(null);
    }
  };

  const cancelDeleteUser = () => {
    if (deletingUserId) return;
    setUserPendingDelete(null);
  };

  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 1;

  const filteredUsers = users.filter(u => {
    const matchesText = [u.username, u.department]
      .filter(Boolean)
      .some(value =>
        (value as string).toLowerCase().includes(search.toLowerCase().trim())
      );
    const matchesRole =
      roleFilter === 'all' ? true : roleFilter === 'admin' ? u.is_admin : !u.is_admin;
    return matchesText && matchesRole;
  });
  const adminCount = users.filter(u => u.is_admin).length;
  const memberCount = users.length - adminCount;

  return (
    <section className="flex-1 overflow-y-auto p-4 space-y-4">
      <div className="app-card-soft px-5 py-4 mb-2">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-[11px] text-slate-500 uppercase tracking-wide">
              {uiText('adminUsers')}
            </p>
            <h2 className="text-lg font-semibold text-slate-900">
              {uiText('createUser')}
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              {uiLanguage === 'ar'
                ? 'أضف أعضاء جدد وحدد صلاحياتهم وقسمهم في خطوة واحدة.'
                : 'Add teammates, choose their role, and place them into the right department in one flow.'}
            </p>
          </div>
          <div className="flex gap-4 text-center">
            <div className="rounded-2xl bg-white/70 px-4 py-2 shadow-sm">
              <div className="text-[11px] uppercase text-slate-500">
                {uiText('admin')}
              </div>
              <div className="text-lg font-semibold">{adminCount}</div>
            </div>
            <div className="rounded-2xl bg-white/70 px-4 py-2 shadow-sm">
              <div className="text-[11px] uppercase text-slate-500">
                {uiText('user')}
              </div>
              <div className="text-lg font-semibold">{memberCount}</div>
            </div>
            <div className="rounded-2xl bg-white/70 px-4 py-2 shadow-sm">
              <div className="text-[11px] uppercase text-slate-500">
                {uiText('totalUsersLabel')}
              </div>
              <div className="text-lg font-semibold">
                {total || users.length}
              </div>
            </div>
          </div>
        </div>
        <form
          onSubmit={handleCreateUser}
          className="mt-4 grid grid-cols-1 md:grid-cols-5 gap-3 text-xs"
        >
          <div className="md:col-span-2">
            <label className="block text-slate-600 mb-1 text-[11px]">
              {uiText('username')}
            </label>
            <input
              className="w-full rounded-2xl bg-white border border-slate-200 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              value={newUsername}
              onChange={e => setNewUsername(e.target.value)}
            />
          </div>
          <div className="relative">
            <label className="block text-slate-600 mb-1 text-[11px]">
              {uiText('password')}
            </label>
            <input
              type={showPassword ? 'text' : 'password'}
              className="w-full rounded-2xl bg-white border border-slate-200 px-4 py-2 pr-12 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
            />
            <button
              type="button"
              className="absolute top-7 right-3 text-[11px] text-theme-accent"
              onClick={() => setShowPassword(prev => !prev)}
            >
              {showPassword
                ? uiLanguage === 'ar'
                  ? 'إخفاء'
                  : 'Hide'
                : uiLanguage === 'ar'
                ? 'إظهار'
                : 'Show'}
            </button>
          </div>
          <div>
            <label className="block text-slate-600 mb-1 text-[11px]">
              {uiText('role')}
            </label>
            <select
              className="w-full rounded-2xl bg-white border border-slate-200 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              value={newRole}
              onChange={e => setNewRole(e.target.value as Role)}
            >
              <option value="user">{uiText('user')}</option>
              <option value="admin">{uiText('admin')}</option>
            </select>
          </div>
          <div>
            <label className="block text-slate-600 mb-1 text-[11px]">
              {uiText('department')}
            </label>
            <input
              className="w-full rounded-2xl bg-white border border-slate-200 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
              placeholder={newRole === 'admin' ? uiText('adminUsers') : uiText('global')}
              value={newDepartment}
              onChange={e => setNewDepartment(e.target.value)}
            />
          </div>
          <div className="flex flex-col justify-end gap-2">
            <button
              type="submit"
              disabled={creating}
              className="btn-primary-rounded px-4 py-2 text-xs"
            >
              {creating ? uiText('create') : uiText('createUser')}
            </button>
            {/* <p className="text-[11px] text-slate-500 text-center">
              {uiLanguage === 'ar'
                ? 'سيتم إرسال كلمة مرور مؤقتة إلى المستخدم.'
                : 'We’ll issue a temporary password that the user can change later.'}
            </p> */}
          </div>
        </form>
      </div>

      <div className="app-card-soft px-5 py-3 mb-2 flex flex-col gap-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {(['all', 'admin', 'user'] as RoleFilter[]).map(filter => (
              <button
                key={filter}
                type="button"
                onClick={() => setRoleFilter(filter)}
                className={`btn-chip px-3 py-1 text-[11px] ${
                  roleFilter === filter ? 'btn-chip-active' : ''
                }`}
              >
                {filter === 'all'
                  ? uiText('all')
                  : filter === 'admin'
                  ? uiText('admin')
                  : uiText('user')}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <div className="relative w-full md:w-64">
              <input
                className="w-full rounded-full bg-white border border-slate-200 pl-9 pr-10 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                placeholder={uiText('searchUsersPlaceholder')}
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs">
                🔎
              </span>
              {search && (
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-theme-accent text-[11px]"
                  onClick={() => setSearch('')}
                >
                  {uiText('clear')}
                </button>
              )}
            </div>
            <div className="text-xs text-slate-500">
              {uiText('totalUsersLabel')}: {filteredUsers.length} /{' '}
              {total || users.length}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
          <span>
            {uiLanguage === 'ar'
              ? 'استخدم البحث للعثور على المستخدمين حسب الاسم أو القسم'
              : 'Search by username or department and refine by role.'}
          </span>
          {roleFilter !== 'all' && (
            <button
              type="button"
              className="btn-chip px-3 py-1 text-[11px] text-theme-accent"
              onClick={() => setRoleFilter('all')}
            >
              {uiLanguage === 'ar' ? 'إلغاء التصفية' : 'Clear role filter'}
            </button>
          )}
        </div>
      </div>

      {error && <div className="text-xs text-red-400">{error}</div>}
      {loading && (
        <div className="text-xs text-slate-400">{uiText('loadingUsers')}</div>
      )}
      {!loading && filteredUsers.length === 0 && !error && (
        <div className="text-xs text-slate-500">
          {uiText('noUsers')}
        </div>
      )}
      {filteredUsers.length > 0 && (
        <div className="overflow-x-auto app-card">
          <table
            className={`min-w-full text-xs ${isRTL ? 'text-right' : 'text-left'}`}
            dir={isRTL ? 'rtl' : 'ltr'}
          >
            <thead className="bg-slate-50">
              <tr>
                <th className={`px-3 py-2 border-b border-slate-200 text-[11px] font-semibold tracking-wide uppercase text-slate-500 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('username')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('role')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('department')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('created')}
                </th>
                <th className={`px-2 py-1 border-b border-slate-800 ${isRTL ? 'text-right' : 'text-left'}`}>
                  {uiText('lastLogin')}
                </th>
                <th className="px-2 py-1 border-b border-slate-800 text-right">
                  {uiText('actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map(u => (
                <tr key={u.id} className="odd:bg-white even:bg-slate-50/60 hover:bg-sky-50 transition">
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {editingUsernameId === u.id ? (
                      <div className="flex items-center gap-1">
                        <input
                          className="w-28 rounded bg-slate-950 border border-slate-700 px-1 py-0.5"
                          value={editingUsernameValue}
                          onChange={e =>
                            setEditingUsernameValue(e.target.value)
                          }
                        />
                        <button
                          type="button"
                          className="text-[10px] text-theme-accent"
                          onClick={() => handleSaveUsername(u.id)}
                        >
                          {uiText('save')}
                        </button>
                        <button
                          type="button"
                          className="text-[10px] text-theme-muted"
                          onClick={() => setEditingUsernameId(null)}
                        >
                          {uiText('cancel')}
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="text-slate-800 hover:text-sky-600"
                        onClick={() => {
                          setEditingUsernameId(u.id);
                          setEditingUsernameValue(u.username);
                        }}
                      >
                        {u.username}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 border-b border-slate-100">
                    <button
                      type="button"
                      onClick={() => handleToggleAdmin(u)}
                  className={`px-2 py-0.5 rounded text-[11px] ${
                    u.is_admin
                      ? 'bg-emerald-700 text-white'
                      : 'bg-slate-800 text-slate-200'
                  }`}
                >
                      {u.is_admin ? uiText('admin') : uiText('user')}
                </button>
                  </td>
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {editingDeptId === u.id ? (
                      <div className="flex items-center gap-1">
                        <input
                          className="w-24 rounded bg-slate-950 border border-slate-700 px-1 py-0.5"
                          value={editingDeptValue}
                          onChange={e => setEditingDeptValue(e.target.value)}
                        />
                        <button
                          type="button"
                          className="text-[10px] text-theme-accent"
                          onClick={() => handleSaveDepartment(u.id)}
                        >
                          {uiText('save')}
                        </button>
                        <button
                          type="button"
                          className="text-[10px] text-theme-muted"
                          onClick={() => setEditingDeptId(null)}
                        >
                          {uiText('cancel')}
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="text-slate-700 hover:text-sky-600"
                        onClick={() => {
                          setEditingDeptId(u.id);
                          setEditingDeptValue(u.department || '');
                        }}
                     >
                        {u.department || uiText('public')}
                      </button>
                    )}
                  </td>
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {u.created_at
                      ? new Date(u.created_at).toLocaleString()
                      : '-'}
                  </td>
                  <td className={`px-3 py-2 border-b border-slate-100 ${isRTL ? 'text-right' : 'text-left'}`}>
                    {u.last_login
                      ? new Date(u.last_login).toLocaleString()
                      : '-'}
                  </td>
                  <td className="px-3 py-2 border-b border-slate-100">
                    <div className={`flex ${isRTL ? 'justify-start' : 'justify-end'} gap-2`}>
                      <button
                        type="button"
                        onClick={() => handleResetPassword(u)}
                        className="btn-action px-3 py-1 text-[11px]"
                      >
                        {uiText('resetPassword')}
                      </button>
                      <button
                        type="button"
                        onClick={() => requestDeleteUser(u)}
                        className="btn-action btn-action-danger px-3 py-1 text-[11px]"
                      >
                        {uiText('delete')}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-2 text-xs text-slate-300">
          <button
            type="button"
            disabled={page <= 1}
            className="btn-chip px-3 py-1 text-[11px]"
            onClick={() => loadUsers(page - 1)}
          >
            {uiText('previous')}
          </button>
          <span>
            {uiText('page')} {page} / {totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            className="btn-chip px-3 py-1 text-[11px]"
            onClick={() => loadUsers(page + 1)}
          >
            {uiText('next')}
          </button>
        </div>
      )}
      {userPendingDelete && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.45)] backdrop-blur-sm p-4">
          <div className="app-card w-full max-w-md p-6 space-y-4">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-theme-muted">
                {uiText('delete')}
              </p>
              <h3 className="text-lg font-semibold text-slate-900">
                {uiLanguage === 'ar'
                  ? `حذف المستخدم "${userPendingDelete.username}"؟`
                  : `Delete user "${userPendingDelete.username}"?`}
              </h3>
              <p className="text-xs text-slate-500 mt-2">
                {uiLanguage === 'ar'
                  ? 'سيتم حذف جميع المحادثات والسجلات المرتبطة بهذا المستخدم بشكل دائم.'
                  : 'This will permanently remove all conversations, summaries, and assets connected to this user.'}
              </p>
            </div>
            <div className="flex justify-end gap-2 text-xs">
              <button
                type="button"
                className="btn-chip px-4 py-2"
                onClick={cancelDeleteUser}
                disabled={deletingUserId === userPendingDelete.id}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="btn-action btn-action-danger px-4 py-2"
                onClick={confirmDeleteUser}
                disabled={deletingUserId === userPendingDelete.id}
              >
                {deletingUserId === userPendingDelete.id
                  ? uiText('loading')
                  : uiText('delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
