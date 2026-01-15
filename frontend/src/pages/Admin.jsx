import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { reloadAll, fetchFactories, fetchTariffs, logout, getCurrentUser } from "../api";
import { motion } from "framer-motion";

export default function Admin() {
  const MotionDiv = motion.div;
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [user, setUser] = useState(null);
  const [factoriesCount, setFactoriesCount] = useState(null);
  const [tariffsCount, setTariffsCount] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch(() => {
        navigate("/login");
      });

    async function load() {
      try {
        const [f, t] = await Promise.all([fetchFactories(), fetchTariffs()]);
        setFactoriesCount(Array.isArray(f) ? f.length : 0);
        setTariffsCount(Array.isArray(t) ? t.length : 0);
      } catch (err) {
        console.error("Ошибка при загрузке данных:", err);
        setFactoriesCount(null);
        setTariffsCount(null);
      }
    }
    load();
  }, [navigate]);

  const handleReload = async () => {
    try {
      setLoading(true);
      setMessage("⏳ Обновление данных (заводы + тарифы) из Google Sheets...");
      const data = await reloadAll();
      setMessage(`✅ Обновлено: ${data.factories_count || 0} заводов, ${data.tariffs?.length || 0} тарифов`);

      const [f, t] = await Promise.all([fetchFactories(), fetchTariffs()]);
      setFactoriesCount(Array.isArray(f) ? f.length : 0);
      setTariffsCount(Array.isArray(t) ? t.length : 0);
    } catch (err) {
      console.error("Ошибка обновления:", err);
      setMessage(`❌ Ошибка при обновлении данных: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const tiles = useMemo(
    () => [
      {
        title: "🏭 Заводы и товары",
        desc: "Просмотр товаров, веса, лимитов и цен по производствам.",
        to: "/admin/factories",
        meta:
          factoriesCount == null
            ? "—"
            : `позиций: ${Number(factoriesCount).toLocaleString()}`,
      },
      {
        title: "🚛 Машины и тарифы перевозки",
        desc: "Тарифные сетки по типам машин и диапазонам расстояний.",
        to: "/admin/tariffs",
        meta:
          tariffsCount == null
            ? "—"
            : `строк: ${Number(tariffsCount).toLocaleString()}`,
      },
      {
        title: "📋 Заказы",
        desc: "Подтверждения/отклонения, ручные решения логиста, история.",
        to: "/admin/orders",
        meta: "admin-only",
      },
    ],
    [factoriesCount, tariffsCount]
  );

  return (
    <MotionDiv
      className="space-y-8"
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      <div className="card-glass p-6 md:p-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <p className="pill">Данные из Google Sheets</p>
            {user && (
              <span className="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
                {user.username} ({user.role})
              </span>
            )}
          </div>
          <h1 className="text-3xl font-bold">⚙️ Управление данными</h1>
          <p className="text-slate-600 max-w-2xl">
            Обновляйте товары и тарифы из таблицы, сверяйте контакты заводов и следите за актуальностью цен.
          </p>
        </div>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={handleReload}
            disabled={loading}
            className={`px-5 py-3 rounded-xl text-sm font-semibold transition shadow-md shadow-emerald-100 ${
              loading
                ? "bg-slate-100 text-slate-500 cursor-wait"
                : "bg-emerald-500 text-white hover:bg-emerald-400"
            }`}
          >
            {loading ? "🔄 Обновление..." : "🔁 Обновить данные"}
          </button>
          <button
            type="button"
            onClick={handleLogout}
            className="px-5 py-3 rounded-xl text-sm font-semibold transition bg-slate-200 text-slate-700 hover:bg-slate-300"
          >
            Выйти
          </button>
        </div>
      </div>

      {message && (
        <div className="card-glass p-4 text-sm text-slate-700 border border-slate-200 bg-white">{message}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {tiles.map((t) => (
          <button
            key={t.to}
            type="button"
            onClick={() => navigate(t.to)}
            className="card-glass p-6 border border-slate-200 text-left hover:border-indigo-200 transition"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-slate-900">{t.title}</h2>
                <p className="text-sm text-slate-600 mt-2">{t.desc}</p>
              </div>
              <div className="text-xs px-2 py-1 rounded-full bg-white border border-slate-200 text-slate-600 whitespace-nowrap">
                {t.meta}
              </div>
            </div>
            <div className="mt-4 text-sm font-semibold text-indigo-700">Открыть →</div>
          </button>
        ))}
      </div>
    </MotionDiv>
  );
}
