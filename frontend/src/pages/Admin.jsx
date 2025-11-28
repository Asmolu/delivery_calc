import React, { useEffect, useState } from "react";
import { reloadFactories, fetchFactories, fetchTariffs } from "../api";
import { motion } from "framer-motion";

export default function Admin() {
  const [factories, setFactories] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    async function load() {
      try {
        setMessage("📦 Загружаем текущие данные...");
        const [f, t] = await Promise.all([fetchFactories(), fetchTariffs()]);
        setFactories(f || []);
        setVehicles(t || []);
        setMessage("✅ Данные успешно загружены");
      } catch (err) {
        console.error("Ошибка при загрузке данных:", err);
        setMessage("❌ Ошибка при загрузке данных");
      }
    }
    load();
  }, []);

  const handleReload = async () => {
    try {
      setLoading(true);
      setMessage("⏳ Обновление данных (заводы + тарифы) из Google Sheets...");
      const res = await fetch("/admin/reload", { method: "POST" });
      const data = await res.json();
      setMessage(`✅ ${data.message} (${data.factories} заводов, ${data.tariffs} тарифов)`);

      const [f, t] = await Promise.all([fetchFactories(), fetchTariffs()]);
      setFactories(f || []);
      setVehicles(t || []);
    } catch (err) {
      console.error("Ошибка обновления:", err);
      setMessage("❌ Ошибка при обновлении данных");
    } finally {
      setLoading(false);
    }
  };

  const normalizedVehicles = vehicles.map((v) => ({
    name: v.name || v.название || "Без названия",
    capacity_ton: v.capacity_ton || v["грузоподъёмность"] || 0,
    tag: v.tag || v["тэг"] || "",
    distance_min: v.distance_min ?? v["min_distance"] ?? 0,
    distance_max: v.distance_max ?? v["max_distance"] ?? 0,
    price: v.price ?? v.base ?? 0,
    per_km: v.per_km ?? 0,
    notes: v.notes ?? v["заметки"] ?? "",
  }));

  const vehiclesByName = normalizedVehicles.reduce((acc, v) => {
    const name = v.name || "Без названия";
    if (!acc[name]) acc[name] = [];
    acc[name].push(v);
    return acc;
  }, {});
  const vehiclesList = Object.entries(vehiclesByName);

  const factoriesByName = factories.reduce((acc, f) => {
    const name = f.name || f["название"] || "Без названия";
    if (!acc[name]) acc[name] = [];
    acc[name].push(f);
    return acc;
  }, {});
  const factoriesList = Object.entries(factoriesByName);

  return (
    <motion.div
      className="space-y-8"
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      <div className="card-glass p-6 md:p-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="pill mb-2">Данные из Google Sheets</p>
          <h1 className="text-3xl font-bold">⚙️ Управление данными</h1>
          <p className="text-slate-600 max-w-2xl">
            Обновляйте товары и тарифы из таблицы, сверяйте контакты заводов и следите за актуальностью цен.
          </p>
        </div>
        <button
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
      </div>

      {message && (
        <div className="card-glass p-4 text-sm text-slate-700 border border-slate-200 bg-white">{message}</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="card-glass p-6 border border-slate-200"
        >
          <h2 className="text-xl font-bold text-slate-900 mb-4 flex items-center gap-2">🏭 Заводы и товары</h2>

          {factoriesList.length === 0 ? (
            <p className="text-slate-500">Нет данных о заводах</p>
          ) : (
            <div className="space-y-6 max-h-[70vh] overflow-auto pr-1">
              {factoriesList.map(([name, items], idx) => (
                <div key={idx} className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h3 className="text-lg font-semibold text-slate-900">🏢 {name}</h3>
                      <p className="text-slate-500 text-sm">{items[0]?.category || "—"}</p>
                    </div>
                    <span className="text-xs px-2 py-1 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100">
                      {items.length} позиций
                    </span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left text-slate-800 border border-slate-200 rounded-lg">
                      <thead className="bg-slate-50 text-slate-600">
                        <tr>
                          <th className="px-3 py-2">Подтип</th>
                          <th className="px-3 py-2">Вес (т)</th>
                          <th className="px-3 py-2">Макс. за рейс</th>
                          <th className="px-3 py-2">Особый тариф</th>
                          <th className="px-3 py-2">Цена (₽)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items
                          .slice()
                          .sort((a, b) => (a.subtype || "").localeCompare(b.subtype || ""))
                          .map((item, i) => (
                            <tr key={i} className="border-t border-slate-200 hover:bg-indigo-50/40 transition-colors">
                              <td className="px-3 py-2">{item.subtype || "—"}</td>
                              <td className="px-3 py-2">{item.weight_per_item ?? 0}</td>
                              <td className="px-3 py-2">{item.max_per_trip ?? 0}</td>
                              <td className="px-3 py-2">{item.special_threshold ?? 0}</td>
                              <td className="px-3 py-2 font-medium text-slate-900">{item.price ?? 0}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          )}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="card-glass p-6 border border-slate-200"
        >
          <h2 className="text-xl font-bold text-slate-900 mb-4 flex items-center gap-2">🚛 Машины и тарифы перевозки</h2>

          {vehiclesList.length === 0 ? (
            <p className="text-slate-500">Нет данных о тарифах</p>
          ) : (
            <div className="space-y-6 max-h-[70vh] overflow-auto pr-1">
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
                    <table className="w-full text-sm text-left text-slate-800 border border-slate-200 rounded-lg">
                      <thead className="bg-slate-50 text-slate-600">
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
                                className={`border-t border-slate-200 transition-colors ${
                                  isExtraKm ? "bg-emerald-50/60" : "hover:bg-indigo-50/40"
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
        </motion.div>
      </div>
    </motion.div>
  );
}
