import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate, useParams } from "react-router-dom";
import { acceptInvite, login } from "../api";

export default function InviteAccept() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();
  const params = useParams();

  const token = useMemo(() => String(params?.token || ""), [params]);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const handleAccept = async () => {
    setMessage("");
    if (!token) {
      setMessage("Ссылка приглашения некорректна (нет токена).");
      return;
    }
    if (!firstName.trim()) {
      setMessage("Введите имя.");
      return;
    }
    if (!lastName.trim()) {
      setMessage("Введите фамилию.");
      return;
    }
    if (!username.trim()) {
      setMessage("Введите логин (username).");
      return;
    }
    if (!password) {
      setMessage("Введите пароль.");
      return;
    }
    if (password !== password2) {
      setMessage("Пароли не совпадают.");
      return;
    }
    try {
      setBusy(true);
      await acceptInvite(token, username.trim(), password, firstName.trim(), lastName.trim());
      // сразу логинимся и ведём в админку
      await login(username.trim(), password);
      navigate("/admin", { replace: true });
    } catch (e) {
      setMessage(e?.message || "Ошибка принятия приглашения");
    } finally {
      setBusy(false);
    }
  };

  return (
    <MotionDiv className="space-y-6" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <div className="card-glass p-6">
        <p className="pill mb-3">invite-only</p>
        <h1 className="text-2xl font-bold">Принять приглашение</h1>
        <p className="text-slate-600 text-sm">
          Задайте логин и пароль для доступа. После создания аккаунта вы попадёте в админку вашей организации.
        </p>
      </div>

      {message ? <div className="card-glass p-4 text-sm border border-slate-200 bg-white text-slate-700">{message}</div> : null}

      <div className="card-glass p-6 border border-slate-200">
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <div className="text-xs font-semibold text-slate-600 mb-1">Имя</div>
            <input
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              placeholder="например: Иван"
              disabled={busy}
            />
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-600 mb-1">Фамилия</div>
            <input
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              placeholder="например: Петров"
              disabled={busy}
            />
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-600 mb-1">Логин (username)</div>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              placeholder="например: ivan.petrov"
              disabled={busy}
            />
          </div>
          <div />
          <div>
            <div className="text-xs font-semibold text-slate-600 mb-1">Пароль</div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              placeholder="••••••••"
              disabled={busy}
            />
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-600 mb-1">Повторите пароль</div>
            <input
              type="password"
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200"
              placeholder="••••••••"
              disabled={busy}
            />
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => navigate("/login")}
            className="px-4 py-3 rounded-xl bg-white border border-slate-200 text-slate-700 font-semibold hover:border-indigo-200"
            disabled={busy}
          >
            На вход
          </button>
          <button
            type="button"
            onClick={handleAccept}
            className="px-4 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500 disabled:opacity-60"
            disabled={busy}
          >
            {busy ? "Создаём..." : "Принять"}
          </button>
        </div>
      </div>
    </MotionDiv>
  );
}

