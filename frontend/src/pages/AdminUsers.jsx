import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  adminGetOrg,
  adminListOrgInvites,
  adminListOrgMembers,
  adminCreateOrgInvite,
  adminRevokeOrgInvite,
  adminUpdateOrgMember,
  getCurrentUser,
} from "../api";

const ROLE_OPTIONS = [
  { value: "owner", label: "Owner" },
  { value: "admin", label: "Admin" },
  { value: "logist", label: "Логист" },
  { value: "manager", label: "Менеджер" },
  { value: "viewer", label: "Только просмотр" },
];

export default function AdminUsers() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();

  const ORG_RANK = { viewer: 10, manager: 20, logist: 30, admin: 40, owner: 50 };
  const orgRank = (r) => ORG_RANK[String(r || "").toLowerCase()] || 0;

  const [me, setMe] = useState(null);

  const [org, setOrg] = useState(null);
  const [members, setMembers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const [email, setEmail] = useState("");
  const [role, setRole] = useState("manager");
  const [expiresDays, setExpiresDays] = useState(7);
  const [createdInvite, setCreatedInvite] = useState(null);

  const [editOpen, setEditOpen] = useState(false);
  const [editMember, setEditMember] = useState(null);
  const [editFirstName, setEditFirstName] = useState("");
  const [editLastName, setEditLastName] = useState("");
  const [editOrgRole, setEditOrgRole] = useState("manager");
  const [editMemberActive, setEditMemberActive] = useState(true);
  const [editUserActive, setEditUserActive] = useState(true);
  const isOwner = orgRank(me?.orgRole) >= ORG_RANK.owner;

  const reload = async () => {
    setLoading(true);
    setMessage("");
    try {
      const u = await getCurrentUser();
      setMe(u || null);
      const [o, m, i] = await Promise.all([adminGetOrg(), adminListOrgMembers(), adminListOrgInvites()]);
      setOrg(o || null);
      setMembers(Array.isArray(m) ? m : []);
      setInvites(Array.isArray(i) ? i : []);
    } catch (e) {
      if (e?.status === 401) {
        navigate("/login", { replace: true });
        return;
      }
      const hint = e?.status === 403 ? " (доступ: только admin/owner)" : "";
      setMessage((e?.message || "Ошибка загрузки пользователей/инвайтов") + hint);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeInvites = useMemo(() => {
    return (invites || []).filter((x) => !x.revokedAt && !x.acceptedAt);
  }, [invites]);

  const fmtTs = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  };

  const copy = async (txt) => {
    try {
      await navigator.clipboard.writeText(String(txt || ""));
      setMessage("✅ Скопировано в буфер обмена");
      setTimeout(() => setMessage(""), 1500);
    } catch {
      setMessage("Скопируйте вручную: " + String(txt || ""));
    }
  };

  const handleCreateInvite = async () => {
    setCreatedInvite(null);
    setMessage("");
    try {
      const resp = await adminCreateOrgInvite({
        email: String(email || "").trim(),
        role,
        expires_days: Number(expiresDays || 7),
      });
      setCreatedInvite(resp || null);
      setEmail("");
      await reload();
    } catch (e) {
      setMessage(e?.message || "Ошибка создания инвайта");
    }
  };

  const handleRevokeInvite = async (id) => {
    setMessage("");
    try {
      await adminRevokeOrgInvite(id);
      await reload();
    } catch (e) {
      setMessage(e?.message || "Ошибка отзыва инвайта");
    }
  };

  const openEdit = (m) => {
    if (!isOwner) return;
    setEditMember(m);
    setEditFirstName(String(m?.firstName || ""));
    setEditLastName(String(m?.lastName || ""));
    setEditOrgRole(String(m?.orgRole || "manager"));
    setEditMemberActive(!!m?.isActive);
    setEditUserActive(!!m?.userIsActive);
    setEditOpen(true);
  };

  const saveEdit = async () => {
    if (!isOwner || !editMember?.id) return;
    setMessage("");
    try {
      setLoading(true);
      await adminUpdateOrgMember(editMember.id, {
        firstName: editFirstName,
        lastName: editLastName,
        orgRole: editOrgRole,
        isActive: !!editMemberActive,
        userIsActive: !!editUserActive,
      });
      setEditOpen(false);
      setEditMember(null);
      await reload();
      setMessage("✅ Сохранено");
    } catch (e) {
      setMessage(e?.message || "Ошибка сохранения");
    } finally {
      setLoading(false);
    }
  };

  return (
    <MotionDiv className="space-y-6" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <div className="card-glass p-6 flex items-center justify-between">
        <div>
          <p className="pill mb-2">admin</p>
          <h1 className="text-2xl font-bold">👥 Пользователи</h1>
          <p className="text-slate-600 text-sm">
            Организация: <span className="font-semibold">{org?.name || "—"}</span>
            {org ? ` • участников: ${org.membersCount ?? "—"} • инвайтов: ${org.invitesCount ?? "—"}` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={reload}
            disabled={loading}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-500 disabled:opacity-60"
          >
            {loading ? "Обновляем..." : "Обновить"}
          </button>
          <button
            onClick={() => navigate("/admin")}
            className="px-4 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
          >
            ← Админка
          </button>
        </div>
      </div>

      {message ? <div className="card-glass p-4 text-sm border border-slate-200 bg-white text-slate-700">{message}</div> : null}

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="card-glass p-6 border border-slate-200">
          <div className="text-lg font-semibold mb-3">Создать приглашение</div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <div className="text-xs font-semibold text-slate-600 mb-1">Email</div>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@company.ru"
                className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              />
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-600 mb-1">Роль</div>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              >
                {ROLE_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-600 mb-1">Срок (дней)</div>
              <input
                type="number"
                min={1}
                max={30}
                value={expiresDays}
                onChange={(e) => setExpiresDays(e.target.value)}
                className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={handleCreateInvite}
                disabled={loading || !String(email || "").includes("@")}
                className="w-full px-4 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500 disabled:opacity-60"
              >
                Создать инвайт
              </button>
            </div>
          </div>

          {createdInvite?.inviteUrl ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-900/40 p-4">
              <div className="text-sm font-semibold mb-2">Ссылка приглашения</div>
              <div className="text-xs text-slate-400 break-all">{createdInvite.inviteUrl}</div>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={() => copy(createdInvite.inviteUrl)}
                  className="px-3 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
                >
                  Скопировать ссылку
                </button>
                <button
                  type="button"
                  onClick={() => setCreatedInvite(null)}
                  className="px-3 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
                >
                  Скрыть
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <div className="card-glass p-6 border border-slate-200">
          <div className="text-lg font-semibold mb-3">Активные приглашения</div>
          {activeInvites.length === 0 ? (
            <div className="text-sm text-slate-500">Нет активных приглашений</div>
          ) : (
            <div className="space-y-2 max-h-[55vh] overflow-auto pr-2">
              {activeInvites.map((inv) => (
                <div key={inv.id} className="rounded-xl border border-slate-200 bg-slate-900/30 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-semibold text-slate-200">{inv.email}</div>
                      <div className="text-xs text-slate-400">
                        роль: <span className="font-semibold">{inv.role}</span>
                        {" · "}
                        истекает: <span className="font-semibold">{fmtTs(inv.expiresAt)}</span>
                        {" · "}
                        создан: {fmtTs(inv.createdAt)}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRevokeInvite(inv.id)}
                      className="px-3 py-2 rounded-lg bg-rose-600 text-white font-semibold hover:bg-rose-500"
                    >
                      Отозвать
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card-glass p-6 border border-slate-200">
        <div className="text-lg font-semibold mb-3">Участники</div>
        {(members || []).length === 0 ? (
          <div className="text-sm text-slate-500">Пока нет участников</div>
        ) : (
          <div className="overflow-auto rounded-xl border border-slate-200 bg-slate-900/50">
            <table className="w-full text-sm text-slate-200">
              <thead className="bg-slate-900/40 text-slate-300 border-b border-slate-800">
                <tr>
                  <th className="p-3 text-left">Пользователь</th>
                  <th className="p-3 text-left">Email</th>
                  <th className="p-3 text-left">Роль</th>
                  <th className="p-3 text-left">Активен</th>
                  <th className="p-3 text-left">Добавлен</th>
                  <th className="p-3 text-left">Действия</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id} className="border-b border-slate-800 hover:bg-slate-900/30">
                    <td className="p-3">
                      <div className="font-semibold">{m.username || "—"}</div>
                      <div className="text-xs text-slate-400">
                        {String(`${m.firstName || ""} ${m.lastName || ""}`).trim() || "—"}
                      </div>
                    </td>
                    <td className="p-3 text-slate-300">{m.email || "—"}</td>
                    <td className="p-3">{m.orgRole || "—"}</td>
                    <td className="p-3">
                      <div>участие: {m.isActive ? "да" : "нет"}</div>
                      <div className="text-xs text-slate-400">аккаунт: {m.userIsActive ? "да" : "нет"}</div>
                    </td>
                    <td className="p-3 text-slate-300">{fmtTs(m.createdAt)}</td>
                    <td className="p-3">
                      {isOwner ? (
                        <button
                          type="button"
                          onClick={() => openEdit(m)}
                          className="px-3 py-2 rounded-lg bg-white border border-slate-200 text-slate-700 font-semibold hover:border-indigo-200"
                        >
                          Изменить
                        </button>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-xl rounded-2xl bg-white border border-slate-200 shadow-2xl p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-lg font-bold text-slate-900">Пользователь</div>
                <div className="text-xs text-slate-500">{editMember?.username || "—"}</div>
              </div>
              <button
                type="button"
                onClick={() => setEditOpen(false)}
                className="px-3 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
              >
                ✕
              </button>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div>
                <div className="text-xs font-semibold text-slate-600 mb-1">Имя</div>
                <input
                  value={editFirstName}
                  onChange={(e) => setEditFirstName(e.target.value)}
                  className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
                />
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-600 mb-1">Фамилия</div>
                <input
                  value={editLastName}
                  onChange={(e) => setEditLastName(e.target.value)}
                  className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
                />
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-600 mb-1">Роль</div>
                <select
                  value={editOrgRole}
                  onChange={(e) => setEditOrgRole(e.target.value)}
                  className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-end gap-4">
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={!!editMemberActive}
                    onChange={(e) => setEditMemberActive(e.target.checked)}
                  />
                  Участие активно
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={!!editUserActive}
                    onChange={(e) => setEditUserActive(e.target.checked)}
                  />
                  Аккаунт активен
                </label>
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditOpen(false)}
                className="px-4 py-3 rounded-xl bg-white border border-slate-200 text-slate-700 font-semibold hover:border-indigo-200"
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={loading}
                onClick={saveEdit}
                className="px-4 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500 disabled:opacity-60"
              >
                {loading ? "Сохраняем..." : "Сохранить"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </MotionDiv>
  );
}

