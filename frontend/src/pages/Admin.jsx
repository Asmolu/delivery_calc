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
        setFactories(f);
        setVehicles(t);
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

      // Обновляем список данных
      const [f, t] = await Promise.all([fetchFactories(), fetchTariffs()]);
      setFactories(f);
      setVehicles(t);
    } catch (err) {
      console.error("Ошибка обновления:", err);
      setMessage("❌ Ошибка при обновлении данных");
    } finally {
      setLoading(false);
    }
  };


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
          ⚙️ Админка — управление данными
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
          {loading ? "🔄 Обновление..." : "🔁 Обновить данные (заводы + тарифы)"}
        </button>
      </div>
        
      {/* Сообщения */}
      {message && (
        <div className="mb-8 p-4 bg-gray-800/60 border border-gray-700 rounded-xl text-sm text-gray-300">
          {message}
        </div>
      )}

      {/* Производства */}
      <motion.div
        className="card-glass p-6 rounded-2xl mb-10 hover:shadow-blue-500/20 transition-shadow duration-300"
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <h2 className="text-2xl font-semibold mb-4 flex items-center gap-2">
          🏭 Производства
        </h2>
        {factories.length === 0 ? (
          <p className="text-gray-400">Нет данных о производствах</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead className="text-gray-400 border-b border-gray-700">
                <tr>
                  <th className="p-2 text-left">Название</th>
                  <th className="p-2 text-left">Координаты</th>
                  <th className="p-2 text-left">Товары</th>
                </tr>
              </thead>
              <tbody>
                {factories.map((f, idx) => (
                  <motion.tr
                    key={idx}
                    whileHover={{ scale: 1.01 }}
                    className="border-b border-gray-800 hover:bg-blue-900/30 transition-colors duration-200"
                  >
                    <td className="p-2 font-semibold text-white">{f.name}</td>
                    <td className="p-2 text-gray-300">
                      {f.lat.toFixed(3)}, {f.lon.toFixed(3)}
                    </td>
                    <td className="p-2">
                      {f.products.map((p, i) => (
                        <div
                          key={i}
                          className="text-gray-400 text-xs mb-1 border-b border-gray-800/40 pb-1"
                        >
                          <span className="text-gray-300 font-medium">
                            {p.category}
                          </span>{" "}
                          ({p.subtype}) —{" "}
                          <span className="text-gray-400">
                            {p.price}₽ / {p.weight_ton}т
                          </span>
                        </div>
                      ))}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </motion.div>

      {/* Машины и тарифы перевозки */}
      <motion.div
        className="card-glass p-6 rounded-2xl hover:shadow-green-500/20 transition-shadow duration-300"
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <h2 className="text-2xl font-semibold mb-4 flex items-center gap-2">
          🚛 Машины и тарифы перевозки
        </h2>

        {vehicles.length === 0 ? (
          <p className="text-gray-400">Нет данных о тарифах</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-gray-300 border border-gray-700 rounded-lg">
              <thead className="bg-gray-800 text-gray-200">
                <tr>
                  <th className="px-4 py-2">Название</th>
                  <th className="px-4 py-2">Грузоподъёмность (т)</th>
                  <th className="px-4 py-2">Тип</th>
                  <th className="px-4 py-2">Мин. дистанция (км)</th>
                  <th className="px-4 py-2">Макс. дистанция (км)</th>
                  <th className="px-4 py-2">Цена (₽)</th>
                  <th className="px-4 py-2">За км (₽/км)</th>
                </tr>
              </thead>
              <tbody>
                {vehicles.map((v, idx) => (
                  <motion.tr
                    key={idx}
                    whileHover={{ scale: 1.01 }}
                    className="border-t border-gray-700 hover:bg-green-900/20 transition-colors duration-200"
                  >
                    <td className="px-4 py-2 font-semibold text-white">{v.name}</td>
                    <td className="px-4 py-2 text-gray-300">{v.capacity_ton}</td>
                    <td className="px-4 py-2 text-gray-400">{v.tag}</td>
                    <td className="px-4 py-2">{v.distance_min ?? "-"}</td>
                    <td className="px-4 py-2">{v.distance_max ?? "-"}</td>
                    <td className="px-4 py-2">{v.price ?? "-"}</td>
                    <td className="px-4 py-2">{v.per_km ?? "-"}</td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

