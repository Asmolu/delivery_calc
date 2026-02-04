import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { adminListFactoriesCatalog, adminSetFactoryActive, adminSetProductActive } from "../api";

export default function AdminFactories() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();
  const [factories, setFactories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const reload = async () => {
    setLoading(true);
    try {
      const rows = await adminListFactoriesCatalog();
      setFactories(Array.isArray(rows) ? rows : []);
      setMessage("");
    } catch (e) {
      const hint = e?.status === 401 ? " (нужно войти как админ через /login)" : "";
      setMessage((e?.message || "Ошибка загрузки заводов/товаров") + hint);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const factoriesList = useMemo(() => {
    const arr = Array.isArray(factories) ? factories : [];
    return arr.slice().sort((a, b) => String(a?.name || "").localeCompare(String(b?.name || "")));
  }, [factories]);

  const setFactoryActiveLocal = (factoryId, nextActive) => {
    setFactories((prev) => {
      const arr = Array.isArray(prev) ? prev.slice() : [];
      return arr.map((f) => {
        if (f?.id !== factoryId) return f;
        const next = { ...f, is_active: !!nextActive };
        // Требование: если завод выключен — все его товары выключаются
        if (!next.is_active) {
          next.products = (Array.isArray(next.products) ? next.products : []).map((p) => ({ ...p, is_active: false }));
        }
        return next;
      });
    });
  };

  const setProductActiveLocal = (productId, nextActive) => {
    setFactories((prev) => {
      const arr = Array.isArray(prev) ? prev.slice() : [];
      return arr.map((f) => {
        const products = Array.isArray(f?.products) ? f.products : [];
        const has = products.some((p) => p?.id === productId);
        if (!has) return f;
        return {
          ...f,
          products: products.map((p) => (p?.id === productId ? { ...p, is_active: !!nextActive } : p)),
        };
      });
    });
  };

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
            {factoriesList.map((f) => {
              const products = Array.isArray(f?.products) ? f.products : [];
              const isFactoryActive = !!f?.is_active;

              return (
                <div key={f?.id ?? f?.name} className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
                  <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between mb-3">
                    <div className="min-w-0">
                      <h3 className="text-lg font-semibold text-slate-900 truncate">🏢 {f?.name || "Без названия"}</h3>
                      <div className="text-xs text-slate-500 whitespace-pre-line">
                        {f?.contact ? String(f.contact) : "—"}
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        Дата актуализации: {f?.update_date || "—"}
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className="text-xs px-2 py-1 rounded-full bg-slate-50 text-slate-700 border border-slate-200">
                        {products.length} позиций
                      </span>
                      <label className="flex items-center gap-2 text-sm text-slate-700 select-none">
                        <input
                          type="checkbox"
                          checked={isFactoryActive}
                          disabled={loading}
                          onChange={async (e) => {
                            const next = !!e.target.checked;
                            setFactoryActiveLocal(f.id, next);
                            try {
                              await adminSetFactoryActive(f.id, next);
                            } catch (err) {
                              // откат
                              setFactoryActiveLocal(f.id, !next);
                              setMessage(err?.message || "Ошибка изменения активности завода");
                            }
                          }}
                          className="w-4 h-4 accent-indigo-600"
                        />
                        Активен
                      </label>
                    </div>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left text-slate-700 border border-slate-200 rounded-lg">
                      <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                        <tr>
                          <th className="px-3 py-2 w-20">Активен</th>
                          <th className="px-3 py-2">Категория</th>
                          <th className="px-3 py-2">Подтип</th>
                          <th className="px-3 py-2">Вес (т)</th>
                          <th className="px-3 py-2">Цена (₽)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {products
                          .slice()
                          .sort((a, b) => String(a?.subtype || "").localeCompare(String(b?.subtype || "")))
                          .map((p) => {
                            const canToggle = isFactoryActive && !loading;
                            return (
                              <tr
                                key={p?.id ?? `${p?.category}||${p?.subtype}`}
                                className="border-t border-slate-100 hover:bg-slate-900/30 transition-colors"
                              >
                                <td className="px-3 py-2">
                                  <input
                                    type="checkbox"
                                    checked={isFactoryActive ? !!p?.is_active : false}
                                    disabled={!canToggle}
                                    onChange={async (e) => {
                                      const next = !!e.target.checked;
                                      setProductActiveLocal(p.id, next);
                                      try {
                                        await adminSetProductActive(p.id, next);
                                      } catch (err) {
                                        // откат
                                        setProductActiveLocal(p.id, !next);
                                        setMessage(err?.message || "Ошибка изменения активности товара");
                                      }
                                    }}
                                    className="w-4 h-4 accent-indigo-600 disabled:opacity-50"
                                    title={!isFactoryActive ? "Завод выключен — товары недоступны" : ""}
                                  />
                                </td>
                                <td className="px-3 py-2">{p?.category || "—"}</td>
                                <td className="px-3 py-2">{p?.subtype || "—"}</td>
                                <td className="px-3 py-2">{p?.weight_per_item ?? 0}</td>
                                <td className="px-3 py-2 font-medium text-slate-900">{p?.price ?? 0}</td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </MotionDiv>
  );
}

