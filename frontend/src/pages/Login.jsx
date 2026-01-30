import React, { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getCurrentUser, login, isAuthenticated } from "../api";
import { motion } from "framer-motion";

export default function Login() {
  const MotionDiv = motion.div;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const fromPath = location.state?.from?.pathname || "/admin";

  // Если уже авторизован, перенаправляем
  React.useEffect(() => {
    let isMounted = true;
    const checkSession = async () => {
      if (!isAuthenticated()) return;
      setCheckingSession(true);
      try {
        await getCurrentUser();
        if (isMounted) {
          navigate(fromPath, { replace: true });
        }
      } catch (err) {
        if (isMounted) {
          setError(err?.message || "Сессия истекла. Войдите снова.");
        }
      } finally {
        if (isMounted) {
          setCheckingSession(false);
        }
      }
    };
    checkSession();
    return () => {
      isMounted = false;
    };
  }, [navigate, fromPath]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await login(username, password);
      navigate(fromPath, { replace: true });
    } catch (err) {
      setError(err.message || "Ошибка входа. Проверьте логин и пароль.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <MotionDiv
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="card-glass p-8 w-full max-w-md"
      >
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-900 mb-2">🔐 Вход в систему</h1>
          <p className="text-slate-600">Введите логин и пароль для доступа к админ-панели</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
        {checkingSession && (
            <div className="bg-amber-50 border border-amber-200 text-amber-700 px-4 py-3 rounded-lg text-sm">
              Проверяем сессию. Если база недоступна, войдите повторно позже.
            </div>
          )}
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="username" className="block text-sm font-medium text-slate-700 mb-2">
              Логин
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition"
              placeholder="Введите логин"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-2">
              Пароль
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-4 py-3 rounded-lg border border-slate-300 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition"
              placeholder="Введите пароль"
            />
          </div>

          <button
            type="submit"
            disabled={loading || checkingSession}
            className={`w-full py-3 rounded-lg font-semibold transition shadow-md ${
              loading || checkingSession
                ? "bg-slate-300 text-slate-500 cursor-wait"
                : "bg-emerald-500 text-white hover:bg-emerald-600"
            }`}
          >
            {loading || checkingSession ? "⏳ Вход..." : "Войти"}
          </button>
        </form>

      </MotionDiv>
    </div>
  );
}
