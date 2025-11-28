import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { getCategories, getQuote } from "../api";
import { API_BASE } from "../api";

export default function Calculator() {
  const [categories, setCategories] = useState({});
  const [items, setItems] = useState([{ category: "", subtype: "", quantity: 1 }]);
  const [coords, setCoords] = useState("");
  const [transportType, setTransportType] = useState("auto");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  // 🔹 новые состояния
  const [addManipulator, setAddManipulator] = useState(false);
  const [selectedSpecial, setSelectedSpecial] = useState("");
  const [specialVehicles, setSpecialVehicles] = useState([]); // <-- добавили

  useEffect(() => {
    async function load() {
      const data = await getCategories();
      setCategories(data || {});

      // подгружаем тарифы, чтобы достать список машин с тегом 'special'
      
      try {
        const res = await fetch(`${API_BASE}/api/tariffs`);
        const tariffs = await res.json();

        // поддержка русских и английских ключей
        const specials = (tariffs || []).filter(
          t => t.tag === "special" || t["тег"] === "special"
        );

        const uniqueSpecials = [];
        const seenNames = new Set();

        for (const t of specials) {
          const name = t.name || t["название"];
          if (!seenNames.has(name)) {
            seenNames.add(name);
            uniqueSpecials.push({
              name,
              tag: t.tag || t["тег"],
            });
          }
        }

        setSpecialVehicles(uniqueSpecials);


      } catch (err) {
        console.error("Ошибка загрузки тарифов:", err);
      }

      const demo = sessionStorage.getItem("demo_coords");
      if (demo) {
        setCoords(demo);
        sessionStorage.removeItem("demo_coords");
      }
    }
    load();
  }, []);

  const handleAddItem = () => {
    setItems([...items, { category: "", subtype: "", quantity: 1 }]);
  };

  const handleRemoveItem = (i) => {
    setItems(items.filter((_, idx) => idx !== i));
  };

  const handleChangeItem = (i, field, value) => {
    const updated = [...items];
    updated[i][field] = value;
    setItems(updated);
  };

  const handleCalculate = async () => {
    try {
      const [lat, lon] = coords.split(",").map((x) => parseFloat(x.trim()));
      if (isNaN(lat) || isNaN(lon)) {
        alert("Введите координаты в формате: широта, долгота (через запятую)");
        return;
      }

      setLoading(true);
      const payload = {
        upload_lat: lat,
        upload_lon: lon,
        transport_type: transportType,
        addManipulator,
        selectedSpecial,
        items: items.map((it) => ({
          category: it.category,
          subtype: it.subtype,
          quantity: parseInt(it.quantity),
        })),
      };
      console.log("📤 Payload отправляется в /quote:", payload);
      
      const data = await getQuote(payload);
      console.log("📥 Ответ от сервера:", data);
      if (data?.variants) {
        // если сервер вернул несколько вариантов (новый формат)
        setResult({ ...data, selectedVariant: 0 });
      } else {
        // старый формат (на всякий случай, чтобы не сломать обратную совместимость)
        const localized = {
          variants: [
            {
              totalCost: data.totalCost,
              materialCost: data.materialCost,
              deliveryCost: data.deliveryCost,
              totalWeight: data.totalWeight,
              transportName: data.transportName,
              tripCount: data.trip_count || 0,
              transportDetails: data.transport_details || {},
              details: data.details || [],
            },
          ],
          selectedVariant: 0,
        };
        setResult(localized);
      }
    } catch (err) {
      console.error("Ошибка расчёта:", err);
      alert("Ошибка при расчёте стоимости");
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      className="min-h-screen bg-neutral-900 text-gray-100 px-6 py-10"
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      <button
        onClick={() => (window.location.href = "/")}
        className="mb-6 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded"
      >
        ← Назад
      </button>

      <h1 className="text-4xl font-bold mb-6 flex items-center gap-2">
        📦 Калькулятор доставки
      </h1>

      {/* Координаты одной строкой */}
      <div className="mb-6 flex items-center gap-3">
        <input
          type="text"
          placeholder="Например: 55.7558, 37.6173"
          value={coords}
          onChange={(e) => setCoords(e.target.value)}
          className="flex-1 bg-gray-800 border border-gray-700 rounded px-4 py-2"
        />
        <button
          onClick={() =>
            navigator.geolocation.getCurrentPosition(
              (pos) => {
                const { latitude, longitude } = pos.coords;
                setCoords(`${latitude.toFixed(6)}, ${longitude.toFixed(6)}`);
              },
              () => alert("Не удалось определить координаты"),
              { enableHighAccuracy: true }
            )
          }
          className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded"
        >
          📍 Определить
        </button>
      </div>

      {/* Тип транспорта */}
      <div className="mb-8">
        <label className="block mb-2 text-lg font-semibold">
          Тип транспорта:
        </label>
        <select
          value={transportType}
          onChange={(e) => setTransportType(e.target.value)}
          className="px-3 py-2 rounded bg-gray-800 border border-gray-700 w-1/3"
        >
          <option value="auto">Автоматически</option>
          <option value="manipulator">Манипулятор</option>
          <option value="long_haul">Длинномер</option>
        </select>
      </div>

      <label className="flex items-center gap-2 mt-2">
        <input
          type="checkbox"
          checked={addManipulator}
          onChange={(e) => setAddManipulator(e.target.checked)}
          className="w-4 h-4 accent-green-500"
        />
        <span>+1 манипулятор</span>
      </label>

      <div className="mt-2">
        <label className="text-sm text-gray-300">🛠 Спецтранспорт:</label>
        <select
          value={selectedSpecial}
          onChange={(e) => setSelectedSpecial(e.target.value)}
          className="bg-gray-800 text-white rounded-lg px-3 py-2 ml-2"
        >
          <option value="">Не выбирать</option>
          {/* опции подгрузи из /api/tariffs (фильтр по тегу 'special') если у тебя есть эти данные на фронте; 
            если не хранишь — просто отправь выбранное имя строкой, а на бэке найдём */}
          {specialVehicles.map((v) => (
            <option key={v.name} value={v.name}>
              {v.name}
            </option>
          ))}
        </select>
      </div>


      {/* === Выбор товаров === */}
      <div className="space-y-4">
        {items.map((it, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="card-glass p-5 rounded-xl flex flex-col md:flex-row gap-3 md:items-center"
          >
            <select
              value={it.category}
              onChange={(e) => handleChangeItem(i, "category", e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 flex-1"
            >
              <option value="">Категория</option>
              {Object.keys(categories).map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>

            <select
              value={it.subtype}
              onChange={(e) => handleChangeItem(i, "subtype", e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 flex-1"
              disabled={!it.category}
            >
              <option value="">Подтип</option>
              {it.category &&
                categories[it.category]?.map((sub) => (
                  <option key={sub} value={sub}>{sub}</option>
                ))}
            </select>

            <input
              type="number"
              min="1"
              value={it.quantity}
              onChange={(e) => handleChangeItem(i, "quantity", e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 w-24"
            />

            {items.length > 1 && (
              <button
                onClick={() => handleRemoveItem(i)}
                className="px-3 py-2 bg-red-700 hover:bg-red-600 rounded"
              >
                ✖
              </button>
            )}
          </motion.div>
        ))}

        <button
          onClick={handleAddItem}
          className="mt-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded"
        >
          ➕ Добавить товар
        </button>
      </div>

      {/* === Кнопка расчёта === */}
      <div className="mt-10">
        <button
          onClick={handleCalculate}
          disabled={loading}
          className={`px-6 py-3 rounded-xl text-lg font-semibold transition ${
            loading
              ? "bg-gray-700 cursor-wait"
              : "bg-blue-600 hover:bg-blue-500 shadow-lg shadow-blue-500/20"
          }`}
        >
          {loading ? "🔄 Расчёт..." : "🚚 Рассчитать стоимость"}
        </button>
      </div>

      {/* === Результаты === */}
      {result?.variants ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="card-glass mt-12 p-6 rounded-xl overflow-x-auto"
        >
          <h2 className="text-2xl font-semibold mb-4">
            🧾 Найдено {result.variants.length} вариантов
          </h2>

          {/* карточки вариантов */}
          <div className="grid md:grid-cols-3 gap-4">
            {result.variants.map((variant, idx) => (
              <div
                key={idx}
                onClick={() => setResult({ ...result, selectedVariant: idx })}
                className={`cursor-pointer rounded-xl p-4 transition shadow-lg ${
                  result.selectedVariant === idx
                    ? "bg-blue-700/40 border border-blue-400"
                    : "bg-gray-800/60 hover:bg-gray-700/60"
                }`}
              >
                <h3 className="text-lg font-semibold mb-1">
                  🚛 {variant.transportName}
                </h3>
                <p className="text-blue-400 font-bold text-xl mb-1">
                  {variant.totalCost != null ? variant.totalCost.toLocaleString() + " ₽" : "—"}
                </p>
                <p>📦 {variant.totalWeight} т, 🔁 {variant.tripCount} рейс(ов)</p>
                <p className="text-sm text-gray-400 mt-1">
                  Доставка: {variant.deliveryCost.toLocaleString()} ₽
                </p>
              </div>
            ))}
          </div>

          {/* таблица выбранного варианта */}
          {result.selectedVariant !== undefined && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="mt-10 p-4 bg-gray-900/80 rounded-lg"
            >
              {(() => {
                const activeVariant = result.variants[result.selectedVariant] || {};
                const tripItems = activeVariant.tripItems || [];
                const detailRows = activeVariant.details || [];

                return (
                  <>
                    <h3 className="text-xl font-semibold mb-3">
                      📊 Детали варианта #{result.selectedVariant + 1}
                    </h3>

                    <table className="w-full text-sm border-collapse">
                      <thead className="text-gray-400 border-b border-gray-700">
                        <tr>
                          <th className="p-2 text-left">Производство</th>
                          <th className="p-2 text-left">Контакт</th>
                          <th className="p-2 text-left">Товар</th>
                          <th className="p-2 text-left">Машина</th>
                          <th className="p-2 text-left">Расстояние (км)</th>
                          <th className="p-2 text-left">Материал (₽)</th>
                          <th className="p-2 text-left">Доставка (₽)</th>
                          <th className="p-2 text-left">Итого (₽)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detailRows.map((d, idx) => (
                          <tr key={idx} className="border-b border-gray-800">
                            <td className="p-2">{d["завод"]}</td>
                            <td className="p-2 whitespace-pre-line">{d["контакт"] || "—"}</td>
                            <td className="p-2">{d["товар"]}</td>
                            <td className="p-2">{d["машина"]}</td>
                            <td className="p-2">{d["расстояние_км"]}</td>
                            <td className="p-2">{d["стоимость_материала"]?.toLocaleString()}</td>
                            <td className="p-2">{d["стоимость_доставки"]?.toLocaleString()}</td>
                            <td className="p-2 text-blue-400 font-semibold">
                              {d["итого"]?.toLocaleString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    {/* таблица погрузки по рейсам */}
                    {Array.isArray(tripItems) && tripItems.length > 0 && (
                      <div className="mt-6 bg-gray-800/40 p-4 rounded-lg">
                        <h4 className="text-lg font-semibold mb-2">🚚 Что везёт каждая машина</h4>
                        <table className="w-full text-sm">
                          <thead className="text-gray-400 border-b border-gray-700">
                            <tr>
                          <th className="p-2 text-left">Производство</th>
                          <th className="p-2 text-left">Машина</th>
                          <th className="p-2 text-left">Тариф</th>
                          <th className="p-2 text-left">Расстояние (км)</th>
                          <th className="p-2 text-left">Загрузка (т)</th>
                          <th className="p-2 text-left">Товары</th>
                          <th className="p-2 text-left">Доставка (₽)</th>
                        </tr>
                          </thead>
                          <tbody>
                            {tripItems.map((trip, i) => (
                              <tr key={i} className="border-b border-gray-800 align-top">
                                <td className="p-2">{trip["завод"]}</td>
                                <td className="p-2">{trip["машина"]}</td>
                                <td className="p-2 text-gray-300 whitespace-pre-line">{trip["тариф"] || "—"}</td>
                                <td className="p-2">{trip["расстояние_км"]}</td>
                                <td className="p-2">{trip["загрузка_т"]}</td>
                                <td className="p-2 text-gray-200">{trip["товары"]}</td>
                                <td className="p-2">{Number(trip["стоимость_доставки"] || 0).toLocaleString()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                );
              })()}
            </motion.div>
          )}
        </motion.div>
      ) : null}
    </motion.div>
  );
}
