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
      setMessage(
        `✅ ${data.message} (${data.factories} заводов, ${data.tariffs} тарифов)`
      );

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

  // нормализация тарифов
  const normalizedVehicles = vehicles.map(v => ({
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

  // группировка товаров
  const factoriesByName = factories.reduce((acc, f) => {
    const name = f.name || f["название"] || "Без названия";
    if (!acc[name]) acc[name] = [];
    acc[name].push(f);
    return acc;
  }, {});
  const factoriesList = Object.entries(factoriesByName);

  return (
    <motion.div
      className="min-h-screen bg-gradient-to-b from-neutral-900 to-neutral-950 text-gray-100 px-6 py-10"
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      {/* Заголовок */}
      <div className="flex flex-col md:flex-row justify-between items-center mb-8">
        <h1 className="text-3xl font-bold flex items-center gap-3 text-white">
          ⚙️ Управление данными
        </h1>
        <button
          onClick={handleReload}
          disabled={loading}
          className={`px-5 py-2 rounded-xl text-sm font-semibold transition ${
            loading
              ? "bg-gray-700 cursor-wait"
              : "bg-green-600 hover:bg-green-500 shadow-lg shadow-green-500/30"
          }`}
        >
          {loading ? "🔄 Обновление..." : "🔁 Обновить данные"}
        </button>
      </div>

      {/* Сообщения */}
      {message && (
        <div className="mb-8 p-4 bg-gray-800/60 border border-gray-700 rounded-xl text-sm text-gray-300">
          {message}
        </div>
      )}

      {/* Основная сетка */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-6">
        {/* ТОВАРЫ */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="bg-gray-900/60 rounded-2xl border border-gray-800 shadow-xl p-6"
        >
          <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
            🏭 Заводы и товары
          </h2>

          {factoriesList.length === 0 ? (
            <p className="text-gray-400">Нет данных о заводах</p>
          ) : (
            <div className="space-y-6">
              {factoriesList.map(([name, items], idx) => (
                <motion.div
                  key={idx}
                  className="bg-gray-900/60 rounded-xl border border-gray-800 p-4"
                  whileHover={{ scale: 1.01 }}
                >
                  <h3 className="text-lg font-bold text-white mb-3 flex items-center gap-2">
                    🏢 {name}
                    <span className="text-gray-400 text-sm">
                      ({items[0]?.category || "—"})
                    </span>
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left text-gray-300 border border-gray-700 rounded-lg">
                      <thead className="bg-gray-800 text-gray-200">
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
                          .sort((a, b) =>
                            (a.subtype || "").localeCompare(b.subtype || "")
                          )
                          .map((item, i) => (
                            <tr
                              key={i}
                              className="border-t border-gray-800 hover:bg-blue-900/10 transition-colors"
                            >
                              <td className="px-3 py-2">{item.subtype || "—"}</td>
                              <td className="px-3 py-2">
                                {item.weight_per_item ?? 0}
                              </td>
                              <td className="px-3 py-2">
                                {item.max_per_trip ?? 0}
                              </td>
                              <td className="px-3 py-2">
                                {item.special_threshold ?? 0}
                              </td>
                              <td className="px-3 py-2 font-medium text-gray-100">
                                {item.price ?? 0}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </motion.div>

        {/* МАШИНЫ */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="bg-gray-900/60 rounded-2xl border border-gray-800 shadow-xl p-6"
        >
          <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
            🚛 Машины и тарифы перевозки
          </h2>

          {vehiclesList.length === 0 ? (
            <p className="text-gray-400">Нет данных о тарифах</p>
          ) : (
            <div className="space-y-6">
              {vehiclesList.map(([name, tariffs], idx) => (
                <motion.div
                  key={idx}
                  className="bg-gray-900/60 rounded-xl border border-gray-800 p-4"
                  whileHover={{ scale: 1.01 }}
                >
                  <h3 className="text-lg font-bold text-white mb-3 flex items-center gap-2">
                    🚚 {name}
                    <span className="text-gray-400 text-sm">
                      ({tariffs[0]?.tag || "-"} • {tariffs[0]?.capacity_ton || "?"} т)
                    </span>
                  </h3>

                  <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left text-gray-300 border border-gray-700 rounded-lg">
                      <thead className="bg-gray-800 text-gray-200">
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
                          .sort(
                            (a, b) =>
                              (a.distance_min || 0) - (b.distance_min || 0)
                          )
                          .map((t, i) => {
                            const isExtraKm =
                              t.distance_min === t.distance_max &&
                              t.per_km > 0;
                            return (
                              <tr
                                key={i}
                                className={`border-t border-gray-800 transition-colors ${
                                  isExtraKm
                                    ? "bg-green-900/20 hover:bg-green-900/30"
                                    : "hover:bg-blue-900/10"
                                }`}
                              >
                                <td className="px-3 py-2">{t.distance_min ?? 0}</td>
                                <td className="px-3 py-2">{t.distance_max ?? 0}</td>
                                <td className="px-3 py-2 font-medium text-gray-100">
                                  {t.price ?? t.base ?? 0}
                                </td>
                                <td className="px-3 py-2">
                                  {t.per_km > 0 ? `+${t.per_km} ₽/км` : "—"}
                                </td>
                                <td className="px-3 py-2 text-gray-400 italic">
                                  {t.notes ||
                                    (isExtraKm
                                      ? "расстояние свыше — с доплатой"
                                      : "—")}
                                </td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </motion.div>
      </div>
    </motion.div>
  );
}
