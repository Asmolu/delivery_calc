import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { reloadAll, fetchFactories, adminListTariffs, logout, getCurrentUser } from "../api";
import { motion } from "framer-motion";

export default function Admin() {
  const MotionDiv = motion.div;
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [user, setUser] = useState(null);
  const [factoriesCount, setFactoriesCount] = useState(null);
  const [tariffsCount, setTariffsCount] = useState(null);
  const [transports, setTransports] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch(() => {
        navigate("/login");
      });

    async function load() {
      try {
        const [f, t] = await Promise.all([fetchFactories(), adminListTariffs()]);
        setFactoriesCount(Array.isArray(f) ? f.length : 0);
        setTariffsCount(Array.isArray(t) ? t.length : 0);

        const rows = Array.isArray(t) ? t : [];
        const byKey = new Map();
        for (const r of rows) {
          const name = r?.name || r?.["название"] || "Без названия";
          const tag = (r?.tag || r?.["тег"] || "").toString();
          const k = `${name}||${tag}`;
          if (!byKey.has(k)) {
            byKey.set(k, {
              key: k,
              name,
              tag,
              capacity: Number(r?.capacity ?? r?.["грузоподъёмность"] ?? 0),
              is_active: r?.is_active !== false,
              updatedAt: r?.updatedAt || null,
              updatedBy: r?.updatedBy || null,
              rowCount: 0,
            });
          }
          const rec = byKey.get(k);
          rec.rowCount += 1;
          rec.capacity = Math.max(rec.capacity || 0, Number(r?.capacity ?? r?.["грузоподъёмность"] ?? 0));
          // берём самое свежее updatedAt (best-effort)
          if (r?.updatedAt && (!rec.updatedAt || String(r.updatedAt) > String(rec.updatedAt))) {
            rec.updatedAt = r.updatedAt;
            rec.updatedBy = r.updatedBy || rec.updatedBy;
          }
        }
        const list = Array.from(byKey.values()).sort((a, b) => String(a.name).localeCompare(String(b.name)));
        setTransports(list);
      } catch (err) {
        console.error("Ошибка при загрузке данных:", err);
        setFactoriesCount(null);
        setTariffsCount(null);
        setTransports([]);
      }
    }
    load();
  }, [navigate]);

  const handleReload = async () => {
    try {
      setLoading(true);
      setMessage("⏳ Обновление данных (заводы + товары) из Google Sheets...");
      const data = await reloadAll();
      setMessage(
        `✅ Обновлено: ${data.factories_count || 0} заводов. Тарифы: ${data.tariffs_count ?? "—"}`
      );

      const [f, t] = await Promise.all([fetchFactories(), adminListTariffs()]);
      setFactoriesCount(Array.isArray(f) ? f.length : 0);
      setTariffsCount(Array.isArray(t) ? t.length : 0);
      // обновляем список транспортов
      const rows = Array.isArray(t) ? t : [];
      const byKey = new Map();
      for (const r of rows) {
        const name = r?.name || r?.["название"] || "Без названия";
        const tag = (r?.tag || r?.["тег"] || "").toString();
        const k = `${name}||${tag}`;
        if (!byKey.has(k)) {
          byKey.set(k, {
            key: k,
            name,
            tag,
            capacity: Number(r?.capacity ?? r?.["грузоподъёмность"] ?? 0),
            is_active: r?.is_active !== false,
            updatedAt: r?.updatedAt || null,
            updatedBy: r?.updatedBy || null,
            rowCount: 0,
          });
        }
        const rec = byKey.get(k);
        rec.rowCount += 1;
        rec.capacity = Math.max(rec.capacity || 0, Number(r?.capacity ?? r?.["грузоподъёмность"] ?? 0));
        if (r?.updatedAt && (!rec.updatedAt || String(r.updatedAt) > String(rec.updatedAt))) {
          rec.updatedAt = r.updatedAt;
          rec.updatedBy = r.updatedBy || rec.updatedBy;
        }
      }
      setTransports(Array.from(byKey.values()).sort((a, b) => String(a.name).localeCompare(String(b.name))));
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
        title: "➕ Добавление транспорта",
        desc: "Создание/редактирование транспорта, весовых условий и тарифных сеток.",
        to: "/admin/tariffs",
        meta:
          tariffsCount == null
            ? "—"
            : `строк: ${Number(tariffsCount).toLocaleString()} / машин: ${Number(transports?.length || 0).toLocaleString()}`,
      },
      {
        title: "📋 Заказы",
        desc: "Подтверждения/отклонения, ручные решения логиста, история.",
        to: "/admin/orders",
        meta: "admin-only",
      },
    ],
    [factoriesCount, tariffsCount, transports]
  );

  const tagLabel = (tag) => {
    const t = String(tag || "").toLowerCase();
    const map = {
      container_carrier: "Контейнеровоз",
      long_haul: "Длинномер (шаланда)",
      flatbed: "Бортовой транспорт",
      manipulator: "Манипулятор",
      crane: "Кран",
    };
    return map[t] || (tag || "—");
  };

  const fmtTs = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  };

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
            <p className="pill">Google Sheets (только заводы/товары)</p>
            {user && (
              <span className="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
                {user.username} ({user.role})
              </span>
            )}
          </div>
          <h1 className="text-3xl font-bold">⚙️ Управление данными</h1>
          <p className="text-slate-600 max-w-2xl">
            Обновляйте товары/заводы из таблицы. Тарифы (машины) теперь редактируются в админке сайта.
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

      <div className="card-glass p-6 border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div>
            <h2 className="text-xl font-bold text-slate-900">🚚 Все машины</h2>
            <p className="text-sm text-slate-600">Список транспорта (группировка по названию и тегу).</p>
          </div>
          <button
            type="button"
            onClick={() => navigate("/admin/tariffs")}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-500"
          >
            Открыть редактор →
          </button>
        </div>

        {transports.length === 0 ? (
          <div className="text-slate-500 text-sm">Пока нет транспорта (или не удалось загрузить список).</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-slate-700 border border-slate-200 rounded-lg">
              <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                <tr>
                  <th className="px-3 py-2">Название</th>
                  <th className="px-3 py-2">Тег</th>
                  <th className="px-3 py-2">Г/п (т)</th>
                  <th className="px-3 py-2">Строк</th>
                  <th className="px-3 py-2">Активность</th>
                  <th className="px-3 py-2">Обновлено</th>
                  <th className="px-3 py-2">Действия</th>
                </tr>
              </thead>
              <tbody>
                {transports.map((t) => (
                  <tr key={t.key} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-3 py-2 font-medium text-slate-900">{t.name}</td>
                    <td className="px-3 py-2">{tagLabel(t.tag)}</td>
                    <td className="px-3 py-2">{Number(t.capacity || 0).toLocaleString()}</td>
                    <td className="px-3 py-2">{Number(t.rowCount || 0).toLocaleString()}</td>
                    <td className="px-3 py-2">{t.is_active ? "активен" : "выкл"}</td>
                    <td className="px-3 py-2">
                      {fmtTs(t.updatedAt)}{t.updatedBy ? ` • ${t.updatedBy}` : ""}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => {
                          sessionStorage.setItem("selected_transport_key", t.key);
                          navigate("/admin/tariffs");
                        }}
                        className="px-3 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
                      >
                        Открыть в редакторе
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </MotionDiv>
  );
}
