import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { getCurrentUser, listOrders, getOrder, manualConfirmOrder, approveOrder, declineOrder } from "../api";
import { useNavigate } from "react-router-dom";

function statusLabel(s) {
  if (s === "confirmed_auto") return "Подтверждён (сценарий)";
  if (s === "rejected_for_manual") return "Отклонён (нужно вручную)";
  if (s === "confirmed_manual") return "Подтверждён (вручную)";
  return s || "—";
}

export default function Orders() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [forbidden, setForbidden] = useState(false);
  const [orders, setOrders] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [variantOpen, setVariantOpen] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);

  // manual confirm form (for rejected)
  const [manualTransportName, setManualTransportName] = useState("");
  const [manualNotes, setManualNotes] = useState("");

  useEffect(() => {
    getCurrentUser()
      .then((u) => {
        setUser(u);
        const roleNorm = String(u?.role || "").toLowerCase();
        if (roleNorm !== "admin") {
          setForbidden(true);
        } else {
          setForbidden(false);
        }
      })
      .catch(() => navigate("/login", { replace: true }));
  }, [navigate]);

  const reload = async () => {
    if (forbidden) return;
    setLoading(true);
    try {
      const data = await listOrders();
      setOrders(data || []);
      setMessage("");

      // "Выбранный" заказ = тот, который был открыт/сохранён из калькулятора после расчёта
      const preferredIdRaw = sessionStorage.getItem("selected_order_id");
      const preferredId = preferredIdRaw ? Number(preferredIdRaw) : null;

      if (!selectedId && preferredId && data?.some((o) => o.id === preferredId)) {
        setSelectedId(preferredId);
        sessionStorage.removeItem("selected_order_id");
      } else if (!selectedId && data?.length) {
        setSelectedId(data[0].id);
      }
    } catch (e) {
      setMessage(e?.message || "Ошибка загрузки заказов");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forbidden]);

  useEffect(() => {
    if (forbidden) return;
    if (!selectedId) return;
    setDetailLoading(true);
    getOrder(selectedId)
      .then((o) => {
        setSelected(o);
        setManualTransportName(o?.manualTransportName || "");
        setManualNotes(o?.manualNotes || "");
      })
      .catch((e) => setMessage(e?.message || "Ошибка загрузки заказа"))
      .finally(() => setDetailLoading(false));
  }, [selectedId, forbidden]);

  const selectedStatus = selected?.status;
  const canManualConfirm = selectedStatus === "rejected_for_manual";
  const decision = selected?.decision || null;

  const requestedItems = useMemo(() => {
    const items = selected?.request?.items;
    return Array.isArray(items) ? items : [];
  }, [selected]);

  const variantsSnapshot = useMemo(() => {
    const v = selected?.variants;
    return Array.isArray(v) ? v : [];
  }, [selected]);

  const selectedVariantSnapshot = useMemo(() => {
    // Для прозрачности: если в БД нет selectedVariantSnapshot (например, старые заказы),
    // пробуем восстановить из variants по индексу.
    if (selected?.selectedVariantSnapshot) return selected.selectedVariantSnapshot;
    const idx = Number.isFinite(selected?.selectedVariant) ? selected.selectedVariant : null;
    if (idx == null) return null;
    return variantsSnapshot[idx] || null;
  }, [selected, variantsSnapshot]);

  const variantDetailsRows = useMemo(() => {
    const rows = selectedVariantSnapshot?.details;
    return Array.isArray(rows) ? rows : [];
  }, [selectedVariantSnapshot]);

  const variantTripItems = useMemo(() => {
    const rows = selectedVariantSnapshot?.tripItems;
    return Array.isArray(rows) ? rows : [];
  }, [selectedVariantSnapshot]);

  const quoteRequest = useMemo(() => {
    return selected?.request || {};
  }, [selected]);

  const variantsSummary = useMemo(() => {
    return (variantsSnapshot || []).map((v, idx) => ({
      idx,
      transportName: v?.transportName || "—",
      totalCost: v?.totalCost,
      deliveryCost: v?.deliveryCost,
      materialCost: v?.materialCost,
      totalWeight: v?.totalWeight,
      tripCount: v?.tripCount,
      hasDetails: Array.isArray(v?.details) && v.details.length > 0,
      hasTripItems: Array.isArray(v?.tripItems) && v.tripItems.length > 0,
    }));
  }, [variantsSnapshot]);

  const handleManualConfirm = async () => {
    if (!selectedId) return;
    if (!manualTransportName.trim()) {
      alert("Выберите транспорт");
      return;
    }
    try {
      setMessage("");
      await manualConfirmOrder(selectedId, {
        transportName: manualTransportName.trim(),
        notes: manualNotes || null,
        payload: {},
      });
      await reload();
      const o = await getOrder(selectedId);
      setSelected(o);
      setMessage("✅ Заказ подтверждён вручную");
    } catch (e) {
      setMessage(e?.message || "Ошибка ручного подтверждения");
    }
  };

  const reloadSelected = async () => {
    if (!selectedId) return;
    const o = await getOrder(selectedId);
    setSelected(o);
    setManualTransportName(o?.manualTransportName || "");
    setManualNotes(o?.manualNotes || "");
  };

  const handleApprove = async () => {
    if (!selectedId) return;
    try {
      setDecisionBusy(true);
      setMessage("");
      await approveOrder(selectedId, {});
      setOrders((prev) => (prev || []).map((o) => (o.id === selectedId ? { ...o, decision: "approved" } : o)));
      await reloadSelected();
      await reload();
    } catch (e) {
      setMessage(e?.message || "Ошибка подтверждения");
    } finally {
      setDecisionBusy(false);
    }
  };

  const handleDecline = async () => {
    if (!selectedId) return;
    try {
      setDecisionBusy(true);
      setMessage("");
      await declineOrder(selectedId, {});
      setOrders((prev) => (prev || []).map((o) => (o.id === selectedId ? { ...o, decision: "declined" } : o)));
      await reloadSelected();
      await reload();
    } catch (e) {
      setMessage(e?.message || "Ошибка отклонения");
    } finally {
      setDecisionBusy(false);
    }
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
          <p className="pill mb-2">admin-only</p>
          <h1 className="text-2xl font-bold">📋 Заказы</h1>
          <p className="text-slate-600 text-sm">
            История подтверждений/отклонений и ручных решений. {user ? `Вы: ${user.username}` : ""}
          </p>
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

      {forbidden ? (
        <div className="card-glass p-6 border border-slate-200 bg-white">
          <div className="text-lg font-semibold mb-2">Доступ ограничен</div>
          <div className="text-sm text-slate-700">
            Страница заказов доступна только администраторам. Текущая роль:{" "}
            <span className="font-semibold">{user?.role || "—"}</span>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => navigate("/admin")}
              className="px-4 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
            >
              ← В админку
            </button>
            <button
              onClick={() => navigate("/login")}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-500"
            >
              Перелогиниться
            </button>
          </div>
        </div>
      ) : (
      <div className="grid lg:grid-cols-3 gap-6">
        <div className="card-glass p-4 lg:col-span-1">
          <div className="text-sm font-semibold mb-3">Список</div>
          <div className="space-y-2 max-h-[70vh] overflow-auto pr-1">
            {(orders || []).map((o) => (
              (() => {
                const isSelected = selectedId === o.id;
                const d = o?.decision || null;
                const border =
                  d === "approved"
                    ? "border-emerald-400"
                    : d === "declined"
                    ? "border-red-400"
                    : isSelected
                    ? "border-indigo-200"
                    : "border-slate-200";
                const bg = isSelected ? "bg-indigo-50" : "bg-white";
                const hover = isSelected ? "" : "hover:border-indigo-200";

                return (
              <button
                key={o.id}
                type="button"
                onClick={() => setSelectedId(o.id)}
                className={`w-full text-left rounded-xl border-2 p-3 transition ${bg} ${border} ${hover}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold">#{o.id}</div>
                  <div className="text-xs text-slate-500">{o.createdAt ? new Date(o.createdAt).toLocaleString() : ""}</div>
                </div>
                <div className="text-sm text-slate-700 mt-1">{statusLabel(o.status)}</div>
                {o.warningText ? <div className="text-xs text-amber-700 mt-1">⚠️ {o.warningText}</div> : null}
                {o.manualTransportName ? (
                  <div className="text-xs text-slate-600 mt-1">🛻 {o.manualTransportName}</div>
                ) : null}
              </button>
                );
              })()
            ))}
            {orders?.length === 0 ? <div className="text-sm text-slate-500">Пока нет заказов</div> : null}
          </div>
        </div>

        <div className="card-glass p-4 lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm font-semibold">Детали</div>
            {selected ? (
              <div className="text-xs text-slate-500">
                {selected.createdAt ? `создан: ${new Date(selected.createdAt).toLocaleString()}` : ""}
              </div>
            ) : null}
          </div>

          {detailLoading ? (
            <div className="text-sm text-slate-500">Загрузка...</div>
          ) : selected ? (
            <div className="space-y-5">
              <div
                className={`rounded-xl bg-white p-4 border-2 ${
                  decision === "approved"
                    ? "border-emerald-400"
                    : decision === "declined"
                    ? "border-red-400"
                    : "border-slate-200"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-semibold">Статус: {statusLabel(selected.status)}</div>
                  <div className="text-xs text-slate-500">selectedVariant: {selected.selectedVariant ?? "—"}</div>
                </div>

                <div className="mt-2 text-xs text-slate-600">
                  составил: <span className="font-semibold">{selected.createdBy || "—"}</span>
                  {" · "}
                  принял: <span className="font-semibold">{selected.acceptedBy || "—"}</span>
                  {selected.acceptedAt ? ` (${new Date(selected.acceptedAt).toLocaleString()})` : ""}
                  {" · "}
                  последнее действие: <span className="font-semibold">{selected.lastEventBy || "—"}</span>
                  {selected.lastEventAt ? ` (${new Date(selected.lastEventAt).toLocaleString()})` : ""}
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={decisionBusy}
                    onClick={handleApprove}
                    className={`px-4 py-2 rounded-lg bg-white font-semibold border-2 transition disabled:opacity-60 ${
                      decision === "approved"
                        ? "border-emerald-500 text-emerald-700"
                        : "border-slate-200 text-slate-800 hover:border-emerald-200"
                    }`}
                  >
                    Подтвердить
                  </button>
                  <button
                    type="button"
                    disabled={decisionBusy}
                    onClick={handleDecline}
                    className={`px-4 py-2 rounded-lg bg-white font-semibold border-2 transition disabled:opacity-60 ${
                      decision === "declined"
                        ? "border-red-500 text-red-700"
                        : "border-slate-200 text-slate-800 hover:border-red-200"
                    }`}
                  >
                    Отклонить
                  </button>

                  {selectedVariantSnapshot ? (
                    <button
                      type="button"
                      onClick={() => setVariantOpen(true)}
                      className="px-4 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
                    >
                      Открыть принятый вариант
                    </button>
                  ) : null}
                </div>
                {selected.warningText ? <div className="text-sm text-amber-800 mt-2">⚠️ {selected.warningText}</div> : null}
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="font-semibold mb-2">Позиции заказа</div>
                {requestedItems.length ? (
                  <ul className="text-sm text-slate-700 space-y-1">
                    {requestedItems.map((it, idx) => (
                      <li key={idx}>
                        {it.category} / {it.subtype} × {it.quantity}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-sm text-slate-500">Нет позиций</div>
                )}
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                <div className="font-semibold">Запрос /quote (как вводили в калькуляторе)</div>
                <div className="grid md:grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs text-slate-500">Координаты выгрузки</div>
                    <div className="font-semibold">
                      {quoteRequest.upload_lat ?? "—"}, {quoteRequest.upload_lon ?? "—"}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs text-slate-500">Тип транспорта</div>
                    <div className="font-semibold">{quoteRequest.transport_type ?? "—"}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs text-slate-500">+1 манипулятор</div>
                    <div className="font-semibold">{quoteRequest.addManipulator ? "да" : "нет"}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs text-slate-500">Спецтранспорт</div>
                    <div className="font-semibold">{quoteRequest.selectedSpecial || "—"}</div>
                  </div>
                </div>

                {Array.isArray(quoteRequest.forbidden_types) && quoteRequest.forbidden_types.length ? (
                  <div className="text-sm text-slate-700">
                    Запрещённые типы:{" "}
                    <span className="font-semibold">{quoteRequest.forbidden_types.join(", ")}</span>
                  </div>
                ) : null}
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-semibold">Все варианты (снимок расчёта)</div>
                  <div className="text-xs text-slate-500">всего: {variantsSummary.length}</div>
                </div>

                {variantsSummary.length ? (
                  <div className="overflow-auto rounded-xl border border-slate-200">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                        <tr>
                          <th className="p-3 text-left">#</th>
                          <th className="p-3 text-left">Транспорт</th>
                          <th className="p-3 text-left">Итого (₽)</th>
                          <th className="p-3 text-left">Материал (₽)</th>
                          <th className="p-3 text-left">Доставка (₽)</th>
                          <th className="p-3 text-left">Вес (т)</th>
                          <th className="p-3 text-left">Рейсы</th>
                          <th className="p-3 text-left">Детали</th>
                        </tr>
                      </thead>
                      <tbody>
                        {variantsSummary.map((v) => {
                          const isSel = v.idx === selected?.selectedVariant;
                          return (
                            <tr key={v.idx} className={`border-b border-slate-100 ${isSel ? "bg-indigo-50" : ""}`}>
                              <td className="p-3 font-semibold">{v.idx + 1}</td>
                              <td className="p-3">{v.transportName}</td>
                              <td className="p-3 font-semibold text-indigo-700">
                                {v.totalCost != null ? Number(v.totalCost).toLocaleString() : "—"}
                              </td>
                              <td className="p-3">{v.materialCost != null ? Number(v.materialCost).toLocaleString() : "—"}</td>
                              <td className="p-3">{v.deliveryCost != null ? Number(v.deliveryCost).toLocaleString() : "—"}</td>
                              <td className="p-3">{v.totalWeight ?? "—"}</td>
                              <td className="p-3">{v.tripCount ?? "—"}</td>
                              <td className="p-3 text-xs text-slate-600">
                                {v.hasTripItems ? "машины" : ""}
                                {v.hasTripItems && v.hasDetails ? " + " : ""}
                                {v.hasDetails ? "таблица" : ""}
                                {!v.hasTripItems && !v.hasDetails ? "—" : ""}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-sm text-slate-500">Снимок вариантов отсутствует</div>
                )}

                <details className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                    Показать raw JSON вариантов (variants)
                  </summary>
                  <pre className="mt-2 text-xs overflow-auto">{JSON.stringify(variantsSnapshot, null, 2)}</pre>
                </details>
              </div>

              {selectedVariantSnapshot ? (
                <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold">Принятый вариант</div>
                      <div className="text-xs text-slate-500">
                        {selectedVariantSnapshot.transportName ? `🚛 ${selectedVariantSnapshot.transportName}` : ""}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs text-slate-500">Итого</div>
                      <div className="text-lg font-bold text-indigo-700">
                        {selectedVariantSnapshot.totalCost != null
                          ? `${Number(selectedVariantSnapshot.totalCost).toLocaleString()} ₽`
                          : "—"}
                      </div>
                    </div>
                  </div>

                  <div className="grid md:grid-cols-4 gap-3 text-sm">
                    <div className="rounded-lg border border-slate-200 p-3">
                      <div className="text-xs text-slate-500">Материал</div>
                      <div className="font-semibold">
                        {selectedVariantSnapshot.materialCost != null
                          ? `${Number(selectedVariantSnapshot.materialCost).toLocaleString()} ₽`
                          : "—"}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 p-3">
                      <div className="text-xs text-slate-500">Доставка</div>
                      <div className="font-semibold">
                        {selectedVariantSnapshot.deliveryCost != null
                          ? `${Number(selectedVariantSnapshot.deliveryCost).toLocaleString()} ₽`
                          : "—"}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-200 p-3">
                      <div className="text-xs text-slate-500">Вес</div>
                      <div className="font-semibold">{selectedVariantSnapshot.totalWeight ?? "—"} т</div>
                    </div>
                    <div className="rounded-lg border border-slate-200 p-3">
                      <div className="text-xs text-slate-500">Рейсы</div>
                      <div className="font-semibold">{selectedVariantSnapshot.tripCount ?? "—"}</div>
                    </div>
                  </div>

                  {variantTripItems.length ? (
                    <div className="overflow-auto rounded-xl border border-slate-200">
                      <div className="p-3 border-b border-slate-200 font-semibold text-sm">🚚 Что везёт каждая машина</div>
                      <table className="w-full text-sm">
                        <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
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
                          {variantTripItems.map((trip, i) => (
                            <tr key={i} className="border-b border-slate-100 align-top">
                              <td className="p-3 whitespace-nowrap">{trip["завод"]}</td>
                              <td className="p-3">{trip["машина"]}</td>
                              <td className="p-3 whitespace-pre-line text-slate-600">{trip["тариф"] || "—"}</td>
                              <td className="p-3">{trip["расстояние_км"]}</td>
                              <td className="p-3">{trip["загрузка_т"]}</td>
                              <td className="p-3">{trip["товары"]}</td>
                              <td className="p-3">{Number(trip["стоимость_доставки"] || 0).toLocaleString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500">Нет данных по загрузке машин</div>
                  )}

                  {variantDetailsRows.length ? (
                    <div className="overflow-auto rounded-xl border border-slate-200">
                      <div className="p-3 border-b border-slate-200 font-semibold text-sm">📑 Детализация расчёта</div>
                      <table className="w-full text-sm">
                        <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
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
                          {variantDetailsRows.map((d, idx) => (
                            <tr key={idx} className="border-b border-slate-100 align-top">
                              <td className="p-3 whitespace-nowrap">{d["завод"]}</td>
                              <td className="p-3 whitespace-pre-line text-slate-600">{d["контакт"] || "—"}</td>
                              <td className="p-3">{d["товар"]}</td>
                              <td className="p-3">{d["машина"]}</td>
                              <td className="p-3">{d["расстояние_км"]}</td>
                              <td className="p-3">{d["стоимость_материала"]?.toLocaleString?.() ?? d["стоимость_материала"]}</td>
                              <td className="p-3">{d["стоимость_доставки"]?.toLocaleString?.() ?? d["стоимость_доставки"]}</td>
                              <td className="p-3 font-semibold text-indigo-700">{d["итого"]?.toLocaleString?.() ?? d["итого"]}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {canManualConfirm ? (
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="font-semibold mb-2">Ручное решение логиста</div>
                  <div className="grid md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-semibold text-slate-600 mb-1">Транспорт</label>
                      <input
                        value={manualTransportName}
                        onChange={(e) => setManualTransportName(e.target.value)}
                        placeholder="Например: Манипулятор 10т"
                        className="w-full border border-slate-200 rounded-lg px-3 py-2"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-slate-600 mb-1">Комментарий</label>
                      <input
                        value={manualNotes}
                        onChange={(e) => setManualNotes(e.target.value)}
                        placeholder="Опционально"
                        className="w-full border border-slate-200 rounded-lg px-3 py-2"
                      />
                    </div>
                  </div>
                  <button
                    onClick={handleManualConfirm}
                    className="mt-3 px-4 py-2 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-500"
                  >
                    Подтвердить вручную
                  </button>
                </div>
              ) : null}

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="font-semibold mb-2">События</div>
                {Array.isArray(selected.events) && selected.events.length ? (
                  <ul className="text-sm text-slate-700 space-y-2">
                    {selected.events.map((e) => (
                      <li key={e.id} className="border border-slate-100 rounded-lg p-2">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold">{e.type}</span>
                          <span className="text-xs text-slate-500">
                            {e.createdAt ? new Date(e.createdAt).toLocaleString() : ""}
                          </span>
                        </div>
                        <div className="text-xs text-slate-500">user: {e.user || "—"}</div>
                        {e.payload ? (
                          <pre className="mt-2 text-xs bg-slate-50 border border-slate-200 rounded-lg p-2 overflow-auto">
                            {JSON.stringify(e.payload, null, 2)}
                          </pre>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-sm text-slate-500">Пока нет событий</div>
                )}
              </div>

              <details className="rounded-xl border border-slate-200 bg-white p-4">
                <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                  Показать raw JSON заказа (полностью)
                </summary>
                <pre className="mt-3 text-xs bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-auto">
                  {JSON.stringify(selected, null, 2)}
                </pre>
              </details>
            </div>
          ) : (
            <div className="text-sm text-slate-500">Выберите заказ слева</div>
          )}
        </div>
      </div>
      )}

      {variantOpen && selectedVariantSnapshot ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-6xl max-h-[90vh] overflow-auto rounded-2xl bg-white border border-slate-200 shadow-2xl p-5">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-lg font-bold">Принятый вариант (крупно)</div>
                <div className="text-xs text-slate-500">
                  Заказ #{selected?.id || "—"} • вариант #{(selected?.selectedVariant ?? 0) + 1}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setVariantOpen(false)}
                className="px-3 py-2 rounded-lg bg-white border border-slate-200 hover:border-indigo-200"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              {variantTripItems.length ? (
                <div className="overflow-auto rounded-xl border border-slate-200">
                  <div className="p-3 border-b border-slate-200 font-semibold text-sm">🚚 Что везёт каждая машина</div>
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
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
                      {variantTripItems.map((trip, i) => (
                        <tr key={i} className="border-b border-slate-100 align-top">
                          <td className="p-3 whitespace-nowrap">{trip["завод"]}</td>
                          <td className="p-3">{trip["машина"]}</td>
                          <td className="p-3 whitespace-pre-line text-slate-600">{trip["тариф"] || "—"}</td>
                          <td className="p-3">{trip["расстояние_км"]}</td>
                          <td className="p-3">{trip["загрузка_т"]}</td>
                          <td className="p-3">{trip["товары"]}</td>
                          <td className="p-3">{Number(trip["стоимость_доставки"] || 0).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {variantDetailsRows.length ? (
                <div className="overflow-auto rounded-xl border border-slate-200">
                  <div className="p-3 border-b border-slate-200 font-semibold text-sm">📑 Детализация расчёта</div>
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
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
                      {variantDetailsRows.map((d, idx) => (
                        <tr key={idx} className="border-b border-slate-100 align-top">
                          <td className="p-3 whitespace-nowrap">{d["завод"]}</td>
                          <td className="p-3 whitespace-pre-line text-slate-600">{d["контакт"] || "—"}</td>
                          <td className="p-3">{d["товар"]}</td>
                          <td className="p-3">{d["машина"]}</td>
                          <td className="p-3">{d["расстояние_км"]}</td>
                          <td className="p-3">{d["стоимость_материала"]?.toLocaleString?.() ?? d["стоимость_материала"]}</td>
                          <td className="p-3">{d["стоимость_доставки"]?.toLocaleString?.() ?? d["стоимость_доставки"]}</td>
                          <td className="p-3 font-semibold text-indigo-700">{d["итого"]?.toLocaleString?.() ?? d["итого"]}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </MotionDiv>
  );
}

