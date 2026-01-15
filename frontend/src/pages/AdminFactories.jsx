import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { fetchFactories } from "../api";

export default function AdminFactories() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();
  const [factories, setFactories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const reload = async () => {
    setLoading(true);
    try {
      const f = await fetchFactories();
      setFactories(Array.isArray(f) ? f : []);
      setMessage("");
    } catch (e) {
      setMessage(e?.message || "Ошибка загрузки заводов/товаров");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const factoriesList = useMemo(() => {
    const byName = (factories || []).reduce((acc, f) => {
      const name = f.name || f["название"] || "Без названия";
      if (!acc[name]) acc[name] = [];
      acc[name].push(f);
      return acc;
    }, {});
    return Object.entries(byName).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  }, [factories]);

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
          <h1 className="text-2xl font-bold">🏭 Заводы и товары</h1>
          <p className="text-slate-600 text-sm">Справочник производств и прайс-лист по подтипам.</p>
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
        {factoriesList.length === 0 ? (
          <p className="text-slate-500">Нет данных о заводах</p>
        ) : (
          <div className="space-y-6 max-h-[75vh] overflow-auto pr-1">
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
                  <table className="w-full text-sm text-left text-slate-700 border border-slate-200 rounded-lg">
                    <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
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
                          <tr key={i} className="border-t border-slate-100 hover:bg-slate-50 transition-colors">
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
      </div>
    </MotionDiv>
  );
}

