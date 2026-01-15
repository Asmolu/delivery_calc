import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { fetchTariffs } from "../api";

export default function AdminTariffs() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();
  const [tariffsRaw, setTariffsRaw] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const reload = async () => {
    setLoading(true);
    try {
      const t = await fetchTariffs();
      setTariffsRaw(Array.isArray(t) ? t : []);
      setMessage("");
    } catch (e) {
      setMessage(e?.message || "Ошибка загрузки тарифов");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const vehiclesList = useMemo(() => {
    const normalized = (tariffsRaw || []).map((v) => ({
      name: v.name || v.название || "Без названия",
      capacity_ton: v.capacity_ton || v["грузоподъёмность"] || 0,
      tag: v.tag || v["тэг"] || v["тег"] || "",
      distance_min: v.distance_min ?? v["min_distance"] ?? 0,
      distance_max: v.distance_max ?? v["max_distance"] ?? 0,
      price: v.price ?? v.base ?? 0,
      per_km: v.per_km ?? 0,
      notes: v.notes ?? v["заметки"] ?? "",
    }));

    const byName = normalized.reduce((acc, v) => {
      const name = v.name || "Без названия";
      if (!acc[name]) acc[name] = [];
      acc[name].push(v);
      return acc;
    }, {});

    return Object.entries(byName).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  }, [tariffsRaw]);

  return (
    <MotionDiv
      className="space-y-6"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="card-glass p-6 flex items-center justify-between">
        <div>
          <p className="pill mb-2">admin</p>
          <h1 className="text-2xl font-bold">🚛 Машины и тарифы перевозки</h1>
          <p className="text-slate-600 text-sm">Справочник транспорта и тарифные сетки по дистанциям.</p>
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

      {message ? (
        <div className="card-glass p-4 text-sm border border-slate-200 bg-white text-slate-700">{message}</div>
      ) : null}

      <div className="card-glass p-6 border border-slate-200">
        {vehiclesList.length === 0 ? (
          <p className="text-slate-500">Нет данных о тарифах</p>
        ) : (
          <div className="space-y-6 max-h-[75vh] overflow-auto pr-1">
            {vehiclesList.map(([name, tariffs], idx) => (
              <div key={idx} className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900">🚚 {name}</h3>
                    <p className="text-slate-500 text-sm">
                      {tariffs[0]?.tag || "-"} • {tariffs[0]?.capacity_ton || "?"} т
                    </p>
                  </div>
                  <span className="text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-100">
                    {tariffs.length} тарифов
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left text-slate-700 border border-slate-200 rounded-lg">
                    <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                      <tr>
                        <th className="px-3 py-2">Мин. дистанция (км)</th>
                        <th className="px-3 py-2">Макс. дистанция (км)</th>
                        <th className="px-3 py-2">Цена (₽)</th>
                        <th className="px-3 py-2">За км (₽/км)</th>
                        <th className="px-3 py-2">Заметки</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tariffs
                        .slice()
                        .sort((a, b) => (a.distance_min || 0) - (b.distance_min || 0))
                        .map((t, i) => {
                          const isExtraKm = t.distance_min === t.distance_max && t.per_km > 0;
                          return (
                            <tr
                              key={i}
                              className={`border-t border-slate-100 transition-colors ${
                                isExtraKm ? "bg-emerald-50" : "hover:bg-slate-50"
                              }`}
                            >
                              <td className="px-3 py-2">{t.distance_min ?? 0}</td>
                              <td className="px-3 py-2">{t.distance_max ?? 0}</td>
                              <td className="px-3 py-2 font-medium text-slate-900">{t.price ?? t.base ?? 0}</td>
                              <td className="px-3 py-2">{t.per_km > 0 ? `+${t.per_km} ₽/км` : "—"}</td>
                              <td className="px-3 py-2 text-slate-500 italic">
                                {t.notes || (isExtraKm ? "расстояние свыше — с доплатой" : "—")}
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </MotionDiv>
  );
}

