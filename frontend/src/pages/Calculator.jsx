import React, { useState, useEffect } from "react";
import { getCategories, getQuote } from "../api";
import { motion } from "framer-motion";

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
        const res = await fetch(`${window.location.origin}/api/tariffs`);
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
      setResult(data);
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
      {result ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="card-glass mt-12 p-6 rounded-xl overflow-x-auto"
        >
          <h2 className="text-2xl font-semibold mb-4">🧾 Результаты</h2>

          {Array.isArray(result.детали) && result.детали.length > 0 ? (
            <>
              <table className="w-full text-sm border-collapse">
                <thead className="text-gray-400 border-b border-gray-700">
                  <tr>
                    <th className="p-2 text-left">Производство</th>
                    <th className="p-2 text-left">Товар</th>
                    <th className="p-2 text-left">Машина</th>
                    <th className="p-2 text-left">Расстояние (км)</th>
                    <th className="p-2 text-left">Материал (₽)</th>
                    <th className="p-2 text-left">Доставка (₽)</th>
                    <th className="p-2 text-left">Тариф</th>
                    <th className="p-2 text-left">Итого (₽)</th>
                  </tr>
                </thead>
                <tbody>
                  {result.детали.map((d, idx) => (
                    <tr
                      key={idx}
                      className="border-b border-gray-800 hover:bg-gray-800/30 transition"
                    >
                      <td className="p-2">{d["завод"]}</td>
                      <td className="p-2">{d["товар"]}</td>
                      <td className="p-2">{d["реальное_имя_машины"] || d["машина"]}</td>
                      <td className="p-2">{d["расстояние_км"]}</td>
                      <td className="p-2">{d["стоимость_материала"]?.toLocaleString() || "—"}</td>
                      <td className="p-2">{d["стоимость_доставки"]?.toLocaleString() || "—"}</td>
                      <td className="p-2 text-gray-400">{d["тариф"]}</td>
                      <td className="p-2 font-semibold text-blue-300">
                        {d["итого"]?.toLocaleString() || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="mt-6 text-lg font-semibold">
                <p>🚛 Общий вес: {result["общий_вес"] ?? "—"} т</p>
                <p>🔁 Рейсы: {result["количество_рейсов"] ?? "—"}</p>
                <p className="text-blue-400 text-xl mt-2">
                  💰 Итого: {result["итого"]?.toLocaleString() ?? "—"} ₽
                </p>
              </div>
            </>
          ) : (
            <p className="text-gray-400 mt-4">
              ⚠️ Нет подходящих маршрутов для подбора транспорта.
            </p>
          )}
        </motion.div>
      ) : null}

      {/* === Транспорт (сводка + детали) === */}
      {result?.["транспорт"] && (
        <div className="mt-6 card-glass p-4 rounded-xl">
          <p className="text-gray-300 text-sm mb-2">
            <span className="font-semibold">🚚 Транспорт:</span> {result["транспорт"]}
          </p>

          {result["транспорт_детали"] && (
            <table className="text-sm">
              <tbody>
                {/* Базовый транспорт */}
                <tr>
                  <td className="pr-3 text-gray-400">Базовый:</td>
                  <td>
                    {(() => {
                      const base = result["транспорт_детали"]?.базовый || {};
                      const human =
                        base.реальное_имя ||
                        (base.тип === "manipulator"
                          ? "Манипулятор"
                          : base.тип === "long_haul"
                          ? "Длинномер"
                          : base.тип || "—");
                      const trips = base.рейсы ?? 0;
                      return `${human} × ${trips}`;
                    })()}
                  </td>
                </tr>

                {/* Доп. рейсы */}
                {Array.isArray(result["транспорт_детали"]?.доп) &&
                  result["транспорт_детали"].доп.length > 0 &&
                  result["транспорт_детали"].доп.map((e, i) => (
                    <tr key={i}>
                      <td className="pr-3 text-gray-400">
                        {i === 0 ? "Доп. рейсы:" : ""}
                      </td>
                      <td>
                        {e.реальное_имя || e.название} × {e.рейсы}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </motion.div>
  );
}
