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
  const [addManipulator, setAddManipulator] = useState(false);
  const [selectedSpecial, setSelectedSpecial] = useState("");
  const [specialVehicles, setSpecialVehicles] = useState([]);

  useEffect(() => {
    async function load() {
      const data = await getCategories();
      setCategories(data || {});

      try {
        const res = await fetch(`${API_BASE}/api/tariffs`);
        const tariffs = await res.json();

        // поддержка русских и английских ключей
        const specials = (tariffs || []).filter(
          (t) => t.tag === "special" || t["тег"] === "special"
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
          quantity: parseInt(it.quantity, 10),
        })),
      };

      const data = await getQuote(payload);
      if (data?.variants) {
        setResult({ ...data, selectedVariant: 0 });
      } else {
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
      const message = err?.message || "Ошибка при расчёте стоимости";
      alert(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      className="space-y-8"
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      <div className="card-glass p-6 md:p-8">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="pill mb-3">Полный контроль стоимости</p>
            <h1 className="text-3xl md:text-4xl font-bold mb-2 flex items-center gap-2">
              📦 Калькулятор доставки
            </h1>
            <p className="text-slate-600 max-w-2xl">
              Сравниваем все заводы, тарифы и типы транспорта. Данные легко вводить с телефона, а таблицы
              удобно просматривать на десктопе.
            </p>
          </div>
          <button
            onClick={() => (window.location.href = "/")}
            className="px-4 py-2 bg-white border border-slate-200 rounded-lg shadow-sm text-sm font-semibold hover:border-indigo-200"
          >
            ← На главную
          </button>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <div className="card-glass p-5 md:p-6 md:col-span-2 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center md:gap-3">
            <label className="text-sm font-semibold text-slate-700">Координаты выгрузки</label>
            <div className="flex flex-col sm:flex-row gap-3 w-full">
              <input
                type="text"
                placeholder="Например: 55.7558, 37.6173"
                value={coords}
                onChange={(e) => setCoords(e.target.value)}
                className="flex-1 bg-white border border-slate-200 rounded-lg px-4 py-3 text-slate-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-200"
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
                className="px-4 py-3 bg-indigo-50 text-indigo-700 font-semibold rounded-lg border border-indigo-100 hover:bg-indigo-100"
              >
                📍 Определить
              </button>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="block mb-2 text-sm font-semibold text-slate-700">Тип транспорта</label>
              <select
                value={transportType}
                onChange={(e) => setTransportType(e.target.value)}
                className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
              >
                <option value="auto">Автоматически</option>
                <option value="manipulator">Манипулятор</option>
                <option value="long_haul">Длинномер</option>
              </select>
            </div>
            <div className="space-y-3">
              <label className="block text-sm font-semibold text-slate-700">Дополнительно</label>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={addManipulator}
                  onChange={(e) => setAddManipulator(e.target.checked)}
                  className="w-4 h-4 accent-indigo-600"
                />
                <span>Обязательный +1 манипулятор</span>
              </label>

              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-600">🛠 Спецтранспорт:</span>
                <select
                  value={selectedSpecial}
                  onChange={(e) => setSelectedSpecial(e.target.value)}
                  className="bg-white text-slate-800 rounded-lg px-3 py-2 border border-slate-200"
                >
                  <option value="">Не выбирать</option>
                  {specialVehicles.map((v) => (
                    <option key={v.name} value={v.name}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className="card-glass p-5 md:p-6">
          <h3 className="text-lg font-semibold mb-3">Товары</h3>
          <p className="text-sm text-slate-600 mb-3">
            Можно добавлять несколько строк, система рассчётит комбинированные перевозки.
          </p>
          <div className="space-y-3">
            {items.map((it, i) => (
              <div
                key={i}
                className="rounded-xl border border-slate-200 bg-white p-3 flex flex-col gap-3"
              >
                <select
                  value={it.category}
                  onChange={(e) => handleChangeItem(i, "category", e.target.value)}
                  className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-slate-800"
                >
                  <option value="">Категория</option>
                  {Object.keys(categories).map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>

                <select
                  value={it.subtype}
                  onChange={(e) => handleChangeItem(i, "subtype", e.target.value)}
                  className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-slate-800"
                  disabled={!it.category}
                >
                  <option value="">Подтип</option>
                  {it.category &&
                    categories[it.category]?.map((sub) => (
                      <option key={sub} value={sub}>
                        {sub}
                      </option>
                    ))}
                </select>

                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    min="1"
                    value={it.quantity}
                    onChange={(e) => handleChangeItem(i, "quantity", e.target.value)}
                    className="bg-white border border-slate-200 rounded-lg px-3 py-2 w-24"
                  />
                  {items.length > 1 && (
                    <button
                      onClick={() => handleRemoveItem(i)}
                      className="px-3 py-2 rounded-lg bg-red-900/40 text-red-100 border border-red-500/40 hover:bg-red-800/50"
                    >
                      Удалить
                    </button>
                  )}
                </div>
              </div>
            ))}

            <button
              onClick={handleAddItem}
              className="w-full px-4 py-3 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 font-semibold rounded-lg border border-indigo-100"
            >
              ➕ Добавить товар
            </button>
          </div>
        </div>
      </div>

      <div className="card-glass p-6 md:p-8 flex flex-col gap-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <h2 className="text-2xl font-semibold">Готовы посчитать?</h2>
            <p className="text-slate-600">Запускаем расчёт по всем комбинациям транспорта и заводов.</p>
          </div>
          <button
            onClick={handleCalculate}
            disabled={loading}
            className={`px-6 py-3 rounded-xl text-lg font-semibold transition shadow-lg shadow-indigo-200 bg-indigo-600 text-white hover:bg-indigo-500 ${
              loading ? "opacity-70 cursor-wait" : ""
            }`}
          >
            {loading ? "🔄 Расчёт..." : "🚚 Рассчитать стоимость"}
          </button>
        </div>
      </div>

      {result?.variants ? (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="card-glass p-6 md:p-8">
          <div className="flex flex-col gap-3 mb-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="pill mb-2">Найдено {result.variants.length} вариантов</p>
              <h3 className="text-2xl font-semibold">Сравнение предложений</h3>
              <p className="text-slate-600">Кликните на карточку, чтобы увидеть детали рейсов и тарифов.</p>
            </div>
          </div>

          <div className="grid md:grid-cols-3 gap-4">
            {result.variants.map((variant, idx) => (
              <button
                type="button"
                key={idx}
                onClick={() => setResult({ ...result, selectedVariant: idx })}
                className={`text-left rounded-xl p-4 transition shadow-sm border ${
                  result.selectedVariant === idx
                    ? "bg-indigo-50 border-indigo-200 shadow-md"
                    : "bg-white border-slate-200 hover:border-indigo-200"
                }`}
              >
                <div className="text-sm text-slate-500 mb-1">Вариант #{idx + 1}</div>
                <div className="text-lg font-semibold mb-1">🚛 {variant.transportName || "Комбинация"}</div>
                <p className="text-indigo-700 font-bold text-xl mb-1">
                  {variant.totalCost != null ? `${variant.totalCost.toLocaleString()} ₽` : "—"}
                </p>
                <p className="text-sm text-slate-600">📦 {variant.totalWeight} т · 🔁 {variant.tripCount} рейс(ов)</p>
                <p className="text-xs text-slate-500 mt-1">Доставка: {variant.deliveryCost.toLocaleString()} ₽</p>
              </button>
            ))}
          </div>

          {result.selectedVariant !== undefined && (() => {
            const activeVariant = result.variants[result.selectedVariant] || {};
            const tripItems = activeVariant.tripItems || [];
            const detailRows = activeVariant.details || [];

            return (
              <div className="mt-10 space-y-6">
                <div className="overflow-auto rounded-xl border border-slate-200 bg-slate-900/70 shadow-sm">
                  <table className="w-full text-sm text-slate-200">
                    <thead className="bg-slate-900/50 text-slate-300 border-b border-slate-800">
                      <tr>
                        <th className="p-3 text-left">Производство</th>
                        <th className="p-3 text-left">Контакт</th>
                        <th className="p-3 text-left">Товар</th>
                        <th className="p-3 text-left">Машина</th>
                        <th className="p-3 text-left">Расстояние (км)</th>
                        <th className="p-3 text-left">Материал (₽)</th>
                        <th className="p-3 text-left">Доставка (₽)</th>
                        <th className="p-3 text-left">Итого (₽)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailRows.map((d, idx) => (
                        <tr key={idx} className="border-b border-slate-800">
                          <td className="p-3 whitespace-nowrap">{d["завод"]}</td>
                          <td className="p-3 whitespace-pre-line text-slate-400">{d["контакт"] || "—"}</td>
                          <td className="p-3">{d["товар"]}</td>
                          <td className="p-3">{d["машина"]}</td>
                          <td className="p-3">{d["расстояние_км"]}</td>
                          <td className="p-3">{d["стоимость_материала"]?.toLocaleString()}</td>
                          <td className="p-3">{d["стоимость_доставки"]?.toLocaleString()}</td>
                          <td className="p-3 text-indigo-300 font-semibold">{d["итого"]?.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {Array.isArray(tripItems) && tripItems.length > 0 && (
                  <div className="overflow-auto rounded-xl border border-slate-200 bg-slate-900/70 shadow-sm">
                    <div className="p-4 border-b border-slate-800 flex items-center gap-2 text-slate-200">
                      🚚 Что везёт каждая машина
                    </div>
                    <table className="w-full text-sm text-slate-200">
                      <thead className="bg-slate-900/50 text-slate-300 border-b border-slate-800">
                        <tr>
                          <th className="p-3 text-left">Производство</th>
                          <th className="p-3 text-left">Машина</th>
                          <th className="p-3 text-left">Тариф</th>
                          <th className="p-3 text-left">Расстояние (км)</th>
                          <th className="p-3 text-left">Загрузка (т)</th>
                          <th className="p-3 text-left">Товары</th>
                          <th className="p-3 text-left">Доставка (₽)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tripItems.map((trip, i) => (
                          <tr key={i} className="border-b border-slate-800 align-top">
                            <td className="p-3 whitespace-nowrap">{trip["завод"]}</td>
                            <td className="p-3">{trip["машина"]}</td>
                            <td className="p-3 text-slate-300 whitespace-pre-line">{trip["тариф"] || "—"}</td>
                            <td className="p-3">{trip["расстояние_км"]}</td>
                            <td className="p-3">{trip["загрузка_т"]}</td>
                            <td className="p-3 text-slate-100">{trip["товары"]}</td>
                            <td className="p-3">{Number(trip["стоимость_доставки"] || 0).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })()}
        </motion.div>
      ) : null}
    </motion.div>
  );
}
