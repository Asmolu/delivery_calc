import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  getCurrentUser,
  listOrders,
  getOrder,
  manualConfirmOrder,
  approveOrder,
  declineOrder,
  deleteOrder,
  recalcManualOrder,
  fetchFactories,
  getTariffs,
} from "../api";
import { useNavigate } from "react-router-dom";

function statusLabel(s) {
  if (s === "confirmed_auto") return "Подтверждён (сценарий)";
  if (s === "rejected_for_manual") return "Отклонён (нужно вручную)";
  if (s === "confirmed_manual") return "Подтверждён (вручную)";
  return s || "—";
}

function transportTagLabel(tag) {
  const t = String(tag || "").toLowerCase();
  if (!t) return "—";
  if (t === "auto") return "Авто";
  if (t === "container_carrier") return "Контейнеровоз";
  if (t === "long_haul") return "Длинномер (шаланда)";
  if (t === "flatbed") return "Бортовой транспорт";
  if (t === "manipulator") return "Манипулятор";
  if (t === "crane") return "Кран";
  return tag;
}

function eventHumanLabel(type) {
  const t = String(type || "");
  if (t === "confirmed_auto") return "Сценарий подтверждён (сохранён в БД)";
  if (t === "rejected_for_manual") return "Сценарий отклонён — требуется ручное заполнение";
  if (t === "confirmed_manual") return "Заказ подтверждён вручную";
  if (t === "manual_recalc") return "Ручной перерасчёт выполнен";
  if (t === "approved") return "Заказ подтверждён (финальное решение)";
  if (t === "declined") return "Заказ отклонён (финальное решение)";
  return t || "Событие";
}

function eventSummary(type, payload) {
  const p = payload && typeof payload === "object" ? payload : null;
  if (!p) return null;

  if (type === "confirmed_auto" || type === "rejected_for_manual") {
    if (p.selectedVariant != null) return `вариант #${Number(p.selectedVariant) + 1}`;
  }
  if (type === "confirmed_manual") {
    const tn = p.transportName;
    if (tn) return `транспорт: ${tn}`;
  }
  if (type === "manual_recalc") {
    const total = p?.recalc?.totalCost;
    if (total != null) return `итого: ${Number(total).toLocaleString()} ₽`;
  }
  if (type === "approved" || type === "declined") {
    const notes = p.notes;
    if (notes) return `комментарий: ${notes}`;
  }
  return null;
}

export default function Orders() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();
  const normStr = (x) => String(x ?? "").trim();
  const ORG_RANK = { viewer: 10, manager: 20, logist: 30, admin: 40, owner: 50 };
  const orgRank = (r) => ORG_RANK[String(r || "").toLowerCase()] || 0;
  const [user, setUser] = useState(null);
  const [forbidden, setForbidden] = useState(false);
  const [orders, setOrders] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [variantOpen, setVariantOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);

  // manual confirm form (for rejected)
  const [manualTransportName, setManualTransportName] = useState("");
  const [manualNotes, setManualNotes] = useState("");
  const [manualDeliveryMachines, setManualDeliveryMachines] = useState([""]);
  const [manualUnloadingMachines, setManualUnloadingMachines] = useState([""]);
  const [manualFactoryByItem, setManualFactoryByItem] = useState([]);
  const [manualDeliveryTransportTag, setManualDeliveryTransportTag] = useState("auto");
  const [manualUnloadingTransportTag, setManualUnloadingTransportTag] = useState("auto");

  const [tariffs, setTariffs] = useState([]);
  const [factoriesFlat, setFactoriesFlat] = useState([]);

  useEffect(() => {
    getCurrentUser()
      .then((u) => {
        setUser(u);
        // Доступ к просмотру заказов: manager и выше
        if (orgRank(u?.orgRole) < ORG_RANK.manager) {
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
        // синхронизируем статус в левом списке, чтобы не "залипал" на первом значении
        setOrders((prev) =>
          (prev || []).map((row) =>
            row.id === o?.id
              ? {
                  ...row,
                  status: o?.status,
                  manualTransportName: o?.manualTransportName,
                  warningText: o?.warningText,
                  needsLogisticsCheck: o?.needsLogisticsCheck,
                }
              : row
          )
        );
      })
      .catch((e) => setMessage(e?.message || "Ошибка загрузки заказа"))
      .finally(() => setDetailLoading(false));
  }, [selectedId, forbidden]);

  const selectedStatus = selected?.status;
  const canDecide = orgRank(user?.orgRole) >= ORG_RANK.logist; // подтверждать/отклонять/ручные решения
  const canManualConfirm = canDecide && selectedStatus === "rejected_for_manual";
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

  const autoMachinesText = useMemo(() => {
    const machines = Array.from(
      new Set((variantTripItems || []).map((t) => normStr(t?.["машина"])).filter(Boolean))
    );
    if (machines.length) return machines.join(" + ");
    return normStr(selectedVariantSnapshot?.transportName);
  }, [variantTripItems, selectedVariantSnapshot]);

  const autoFactoriesByItem = useMemo(() => {
    const rows = Array.isArray(variantDetailsRows) ? variantDetailsRows : [];
    const normRows = rows
      .map((r) => {
        const product = normStr(r?.["товар"]).toLowerCase();
        const factory = normStr(r?.["завод"]);
        return { product, factory };
      })
      .filter((r) => r.product || r.factory);

    return (requestedItems || []).map((it) => {
      const cat = normStr(it?.category).toLowerCase();
      const sub = normStr(it?.subtype).toLowerCase();

      const candidates = normRows.filter((r) => {
        if (!r.product) return false;
        // match by either category or subtype (substrings), tolerant to different naming
        return (cat && r.product.includes(cat)) || (sub && r.product.includes(sub));
      });

      const pool = candidates.length ? candidates : normRows;
      const counts = new Map();
      for (const r of pool) {
        if (!r.factory) continue;
        counts.set(r.factory, (counts.get(r.factory) || 0) + 1);
      }

      let best = "";
      let bestCount = 0;
      for (const [k, v] of counts.entries()) {
        if (v > bestCount) {
          best = k;
          bestCount = v;
        }
      }
      return best || "—";
    });
  }, [requestedItems, variantDetailsRows]);

  const quoteRequest = useMemo(() => {
    return selected?.request || {};
  }, [selected]);

  // load reference data (tariffs + factories) for manual editor
  useEffect(() => {
    if (forbidden) return;
    let cancelled = false;
    Promise.all([getTariffs(), fetchFactories()])
      .then(([t, f]) => {
        if (cancelled) return;
        setTariffs(Array.isArray(t) ? t : []);
        setFactoriesFlat(Array.isArray(f) ? f : []);
      })
      .catch((e) => {
        console.error("Ошибка загрузки справочников (tariffs/factories):", e);
        if (cancelled) return;
        setTariffs([]);
        setFactoriesFlat([]);
      });
    return () => {
      cancelled = true;
    };
  }, [forbidden]);

  const manualDecisionPayload = useMemo(() => {
    // backend хранит manual_payload = decision.payload
    const p = selected?.manualPayload;
    if (p && typeof p === "object") return p;
    return {};
  }, [selected]);

  const manualDecision = useMemo(() => {
    // наша схема из калькулятора: payload.manual = {...}
    const m = manualDecisionPayload?.manual;
    if (m && typeof m === "object") return m;
    return null;
  }, [manualDecisionPayload]);

  const parseMachines = (v) => {
    if (Array.isArray(v)) return v.map((x) => normStr(x)).filter(Boolean);
    const s = normStr(v);
    if (!s) return [];
    return s.split("+").map((x) => x.trim()).filter(Boolean);
  };

  // sync manual editor state from order/request/manual payload
  useEffect(() => {
    const dTag = normStr(quoteRequest.deliveryTransportTag) || "auto";
    const uTag = normStr(quoteRequest.unloadingTransportTag) || "auto";
    setManualDeliveryTransportTag(dTag);
    setManualUnloadingTransportTag(uTag);

    const dm = manualDecision ? (manualDecision.deliveryMachines ?? manualDecision.deliveryMachineName) : null;
    const um = manualDecision ? (manualDecision.unloadingMachines ?? manualDecision.unloadingMachineName) : null;

    const deliveryMachines = parseMachines(dm) || parseMachines(manualTransportName);
    setManualDeliveryMachines(deliveryMachines.length ? deliveryMachines : [""]);
    const unloadingMachines = parseMachines(um);
    setManualUnloadingMachines(unloadingMachines.length ? unloadingMachines : [""]);

    const byIdx = (requestedItems || []).map(() => "");
    if (manualDecision && Array.isArray(manualDecision.items)) {
      for (let i = 0; i < (requestedItems || []).length; i++) {
        const it = requestedItems[i];
        const match = manualDecision.items.find(
          (x) => normStr(x?.category) === normStr(it?.category) && normStr(x?.subtype) === normStr(it?.subtype)
        );
        if (match?.factoryName) byIdx[i] = String(match.factoryName);
      }
    }
    setManualFactoryByItem(byIdx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, manualDecision, quoteRequest.deliveryTransportTag, quoteRequest.unloadingTransportTag, requestedItems.length]);

  const manualRecalc = useMemo(() => {
    const r = manualDecisionPayload?.recalc;
    if (r && typeof r === "object") return r;
    return null;
  }, [manualDecisionPayload]);

  const manualRecalcDetails = useMemo(() => {
    const rows = manualRecalc?.details;
    return Array.isArray(rows) ? rows : [];
  }, [manualRecalc]);

  const manualRecalcTripItems = useMemo(() => {
    const rows = manualRecalc?.tripItems;
    return Array.isArray(rows) ? rows : [];
  }, [manualRecalc]);

  const getTariffName = (t) => t?.name || t?.["название"] || "";
  const getTariffTag = (t) => t?.tag || t?.["тег"] || "";
  const getTariffServiceType = (t) => t?.service_type || t?.serviceType || "delivery";

  const uniqueTransportNames = useMemo(() => {
    const names = new Set();
    for (const t of tariffs || []) {
      const name = normStr(getTariffName(t));
      if (name) names.add(name);
    }
    return Array.from(names).sort((a, b) => String(a).localeCompare(String(b)));
  }, [tariffs]);

  const transportCards = useMemo(() => {
    const map = new Map();
    for (const t of tariffs || []) {
      const name = normStr(getTariffName(t));
      if (!name) continue;
      const tag = normStr(getTariffTag(t)).toLowerCase();
      const serviceType = normStr(getTariffServiceType(t)).toLowerCase() || "delivery";
      const key = `${name}||${tag}||${serviceType}`;
      if (!map.has(key)) {
        map.set(key, {
          key,
          name,
          tag,
          serviceType,
          capacity: t?.capacity ?? t?.capacity_ton ?? t?.["грузоподъёмность"] ?? null,
        });
      }
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [tariffs]);

  const deliveryMachineOptions = useMemo(() => {
    const tagFilter = normStr(manualDeliveryTransportTag || quoteRequest.deliveryTransportTag).toLowerCase();
    return transportCards.filter(
      (c) =>
        c.serviceType === "delivery" &&
        (tagFilter === "auto" || !tagFilter || c.tag === tagFilter)
    );
  }, [transportCards, manualDeliveryTransportTag, quoteRequest.deliveryTransportTag]);

  const unloadingMachineOptions = useMemo(() => {
    const tagFilter = normStr(manualUnloadingTransportTag || quoteRequest.unloadingTransportTag).toLowerCase();
    return transportCards.filter(
      (c) =>
        c.serviceType === "unloading" &&
        (tagFilter === "auto" || !tagFilter || c.tag === tagFilter)
    );
  }, [transportCards, manualUnloadingTransportTag, quoteRequest.unloadingTransportTag]);

  const TRANSPORT_TAGS = useMemo(
    () => [
      { value: "auto", label: "Авто" },
      { value: "container_carrier", label: "Контейнеровоз" },
      { value: "long_haul", label: "Длинномер (шаланда)" },
      { value: "flatbed", label: "Бортовой транспорт" },
      { value: "manipulator", label: "Манипулятор" },
      { value: "crane", label: "Кран" },
    ],
    []
  );

  const manualFactoryOptionsByIndex = useMemo(() => {
    const itemsSnap = Array.isArray(requestedItems) ? requestedItems : [];
    const byKey = new Map();
    for (const row of factoriesFlat || []) {
      const cat = normStr(row?.category);
      const sub = normStr(row?.subtype);
      const factoryName = normStr(row?.name || row?.["название"]);
      if (!cat || !sub || !factoryName) continue;
      const key = `${cat}||${sub}`;
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push(row);
    }

    return itemsSnap.map((it) => {
      const key = `${normStr(it?.category)}||${normStr(it?.subtype)}`;
      const rows = byKey.get(key) || [];
      const map = new Map();
      for (const r of rows) {
        const name = normStr(r?.name || r?.["название"]);
        if (!name) continue;
        if (!map.has(name)) map.set(name, r);
      }
      return Array.from(map.values()).sort((a, b) =>
        normStr(a?.name || a?.["название"]).localeCompare(normStr(b?.name || b?.["название"]))
      );
    });
  }, [requestedItems, factoriesFlat]);

  const variantsSummary = useMemo(() => {
    return (variantsSnapshot || []).map((v, idx) => ({
      idx,
      transportName: (() => {
        const tripItems = Array.isArray(v?.tripItems) ? v.tripItems : [];
        const names = new Set();
        for (const t of tripItems) {
          const nm = normStr(t?.["машина"] || t?.machine || t?.tariff_name || t?.tariffName);
          if (nm) names.add(nm);
        }
        if (names.size) return Array.from(names).join(", ");
        // fallback: в старом формате transportName уже обычно содержит названия машин
        return v?.transportName || "—";
      })(),
      factoriesText: (() => {
        const names = new Set();
        const tripItems = Array.isArray(v?.tripItems) ? v.tripItems : [];
        for (const t of tripItems) {
          const fn = normStr(t?.["завод"] || t?.factory || t?.factory_name || t?.factoryName);
          if (fn) names.add(fn);
        }
        const details = Array.isArray(v?.details) ? v.details : [];
        for (const d of details) {
          const fn = normStr(d?.["завод"] || d?.factory || d?.factory_name || d?.factoryName);
          if (fn) names.add(fn);
        }
        const td = Array.isArray(v?.transportDetails) ? v.transportDetails : [];
        for (const p of td) {
          const fn = normStr(p?.factory_name || p?.factoryName || p?.factory);
          if (fn) names.add(fn);
        }
        return names.size ? Array.from(names).join(", ") : "";
      })(),
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

    const deliveryNames = (manualDeliveryMachines || []).map((x) => normStr(x)).filter(Boolean);
    const unloadingNames = (manualUnloadingMachines || []).map((x) => normStr(x)).filter(Boolean);

    const canPickDeliveryMachine = deliveryMachineOptions.length > 0 || uniqueTransportNames.length > 0;
    const canPickUnloadingMachine = unloadingMachineOptions.length > 0 || uniqueTransportNames.length > 0;

    if (canPickDeliveryMachine && deliveryNames.length === 0) {
      alert("Добавьте хотя бы одну машину доставки");
      return;
    }
    if (canPickUnloadingMachine && unloadingNames.length === 0) {
      alert("Добавьте хотя бы одну машину разгрузки");
      return;
    }

    for (let i = 0; i < (requestedItems || []).length; i++) {
      const hasOptions = Array.isArray(manualFactoryOptionsByIndex?.[i]) && manualFactoryOptionsByIndex[i].length > 0;
      if (hasOptions && !normStr(manualFactoryByItem?.[i])) {
        alert("Выберите производство для всех позиций");
        return;
      }
    }

    const deliveryNameFinal = (deliveryNames.join(" + ") || "manual").trim();
    try {
      setMessage("");
      await manualConfirmOrder(selectedId, {
        transportName: deliveryNameFinal,
        notes: manualNotes || null,
        payload: {
          manual: {
            deliveryMachines: deliveryNames,
            unloadingMachines: unloadingNames,
            deliveryMachineName: deliveryNameFinal,
            unloadingMachineName: (unloadingNames.join(" + ") || "manual").trim(),
            deliveryTransportTag: normStr(manualDeliveryTransportTag || quoteRequest.deliveryTransportTag || "auto"),
            unloadingTransportTag: normStr(manualUnloadingTransportTag || quoteRequest.unloadingTransportTag || "auto"),
            items: (requestedItems || []).map((it, idx) => ({
              category: it?.category,
              subtype: it?.subtype,
              quantity: it?.quantity,
              factoryName: manualFactoryByItem?.[idx] || null,
            })),
          },
        },
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

  const handleManualRecalc = async () => {
    if (!selectedId) return;
    try {
      setMessage("");
      await recalcManualOrder(selectedId);
      await reloadSelected();
      setMessage("✅ Ручной перерасчёт выполнен");
    } catch (e) {
      setMessage(e?.message || "Ошибка перерасчёта");
    }
  };

  const canViewAdminOnly = orgRank(user?.orgRole) >= ORG_RANK.admin; // события + удаление
  const canDeleteOrder =
    canViewAdminOnly && (selected?.status === "confirmed_auto" || selected?.status === "confirmed_manual" || selected?.status === "rejected_for_manual");

  const handleDeleteOrder = async () => {
    if (!selectedId) return;
    try {
      setDeleteBusy(true);
      setMessage("");
      await deleteOrder(selectedId, deletePassword);
      setOrders((prev) => (prev || []).filter((o) => o.id !== selectedId));
      setSelectedId(null);
      setSelected(null);
      setDeleteOpen(false);
      setDeletePassword("");
      setMessage(`🗑️ Заказ #${selectedId} удалён`);
    } catch (e) {
      setMessage(e?.message || "Ошибка удаления заказа");
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <MotionDiv
      className="space-y-6"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      {deleteOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white border border-slate-200 shadow-2xl p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-lg font-bold text-slate-900">Удаление заказа</div>
                <div className="text-xs text-slate-500 mt-1">
                  Введите пароль администратора для подтверждения (личная подпись).
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  if (deleteBusy) return;
                  setDeleteOpen(false);
                  setDeletePassword("");
                }}
                className="px-3 py-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300"
              >
                ✕
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1">Пароль администратора</label>
                <input
                  type="password"
                  value={deletePassword}
                  onChange={(e) => setDeletePassword(e.target.value)}
                  className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
                  placeholder="••••••••"
                  autoFocus
                />
              </div>

              <div className="flex items-center justify-between gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    if (deleteBusy) return;
                    setDeleteOpen(false);
                    setDeletePassword("");
                  }}
                  className="px-3 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-slate-300"
                  disabled={deleteBusy}
                >
                  Отмена
                </button>
                <button
                  type="button"
                  onClick={handleDeleteOrder}
                  disabled={deleteBusy || !deletePassword.trim()}
                  className="px-3 py-2 rounded-lg bg-red-600 text-white font-semibold hover:bg-red-500 disabled:opacity-60"
                >
                  {deleteBusy ? "Удаляем..." : "Удалить заказ"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <div className="card-glass p-6 flex items-center justify-between">
        <div>
          <p className="pill mb-2">orders</p>
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
            Страница заказов доступна только менеджеру и выше. Текущая роль в организации:{" "}
            <span className="font-semibold">{user?.orgRole || "—"}</span>
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
          <div className="space-y-2 h-[calc(100vh-260px)] overflow-auto pr-2">
            {(orders || []).map((o) => (
              (() => {
                const isSelected = selectedId === o.id;
                const d = o?.decision || null;
                const needsDecision = !d;
                const border =
                  d === "approved"
                    ? "border-emerald-400"
                    : d === "declined"
                    ? "border-red-400"
                    : needsDecision
                    ? "border-amber-400"
                    : isSelected
                    ? "border-indigo-200"
                    : "border-slate-200";
                // для "требует решения" оставляем общий фон, выделяем только рамкой/меткой
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
                {needsDecision ? (
                  <div className="text-xs font-semibold text-amber-800 mt-1">⏳ Требует решения (подтвердить/отклонить)</div>
                ) : null}
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
                  {canDecide ? (
                    <>
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
                    </>
                  ) : (
                    <div className="text-sm text-slate-500">Решения (подтвердить/отклонить) доступны только логисту и выше.</div>
                  )}

                  {selectedVariantSnapshot && selected?.status !== "confirmed_manual" ? (
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
                    <div className="text-xs text-slate-500">Транспорт доставки</div>
                    <div className="font-semibold">{transportTagLabel(quoteRequest.deliveryTransportTag)}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs text-slate-500">Транспорт разгрузки</div>
                    <div className="font-semibold">{transportTagLabel(quoteRequest.unloadingTransportTag)}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="text-xs text-slate-500">Тип запроса</div>
                    <div className="font-semibold">{quoteRequest.transport_type ?? "auto"}</div>
                  </div>
                </div>

                {Array.isArray(quoteRequest.forbidden_types) && quoteRequest.forbidden_types.length ? (
                  <div className="text-sm text-slate-700">
                    Запрещённые типы:{" "}
                    <span className="font-semibold">{quoteRequest.forbidden_types.join(", ")}</span>
                  </div>
                ) : null}
              </div>

              {(selected?.status === "confirmed_manual" ||
                selected?.manualTransportName ||
                selected?.manualNotes ||
                manualDecision) ? (
                <div className="rounded-xl border-2 border-emerald-200 bg-emerald-50/50 p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold">Ручное решение логиста (сохранено)</div>
                      <div className="text-xs text-slate-600">
                        Это фактически принятый вариант для заказа (в отличие от “выбранного варианта расчёта” ниже).
                      </div>
                    </div>
                    {selected?.manualTransportName ? (
                      <div className="text-right">
                        <div className="text-xs text-slate-500">Машины (доставка)</div>
                        <div className="font-semibold text-emerald-800">{selected.manualTransportName}</div>
                      </div>
                    ) : null}
                  </div>

                  {selected?.manualNotes ? (
                    <div className="text-sm text-slate-700 whitespace-pre-line">
                      <span className="text-xs font-semibold text-slate-600">Комментарий:</span>{" "}
                      {selected.manualNotes}
                    </div>
                  ) : null}

                  {manualDecision ? (
                    <div className="rounded-xl bg-white border border-slate-200 p-3 space-y-3">
                      <div className="grid md:grid-cols-2 gap-3 text-sm">
                        <div>
                          <div className="text-xs text-slate-500">Машины доставки</div>
                          <div className="font-semibold text-slate-800">
                            {Array.isArray(manualDecision.deliveryMachines) && manualDecision.deliveryMachines.length
                              ? manualDecision.deliveryMachines.join(" + ")
                              : (manualDecision.deliveryMachineName || "—")}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-slate-500">Машины разгрузки</div>
                          <div className="font-semibold text-slate-800">
                            {Array.isArray(manualDecision.unloadingMachines) && manualDecision.unloadingMachines.length
                              ? manualDecision.unloadingMachines.join(" + ")
                              : (manualDecision.unloadingMachineName || "—")}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-slate-500">Транспорт доставки</div>
                          <div className="font-semibold">{transportTagLabel(manualDecision.deliveryTransportTag)}</div>
                        </div>
                        <div>
                          <div className="text-xs text-slate-500">Транспорт разгрузки</div>
                          <div className="font-semibold">{transportTagLabel(manualDecision.unloadingTransportTag)}</div>
                        </div>
                      </div>

                      {Array.isArray(manualDecision.items) && manualDecision.items.length ? (
                        <div>
                          <div className="text-sm font-semibold text-slate-800 mb-2">Производства по позициям</div>
                          <div className="overflow-auto rounded-xl border border-slate-200">
                            <table className="w-full text-sm">
                              <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                                <tr>
                                  <th className="p-3 text-left">Товар</th>
                                  <th className="p-3 text-left">Кол-во</th>
                                  <th className="p-3 text-left">Производство</th>
                                </tr>
                              </thead>
                              <tbody>
                                {manualDecision.items.map((it, idx) => (
                                  <tr key={idx} className="border-b border-slate-100">
                                    <td className="p-3">{it?.category} / {it?.subtype}</td>
                                    <td className="p-3">{it?.quantity ?? "—"}</td>
                                    <td className="p-3 font-semibold">{it?.factoryName || "—"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ) : null}

                      <div className="flex items-center justify-between gap-3 pt-2">
                        <div className="text-sm font-semibold text-slate-800">Перерасчёт по ручному выбору</div>
                        {!manualRecalc ? (
                          <button
                            type="button"
                            onClick={handleManualRecalc}
                            className="px-3 py-2 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-500"
                          >
                            Пересчитать
                          </button>
                        ) : null}
                      </div>

                      {manualRecalc ? (
                        <div className="space-y-4">
                          <div className="grid md:grid-cols-4 gap-3 text-sm">
                            <div className="rounded-lg border border-slate-200 p-3">
                              <div className="text-xs text-slate-500">Материал</div>
                              <div className="font-semibold">{Number(manualRecalc.materialCost || 0).toLocaleString()} ₽</div>
                            </div>
                            <div className="rounded-lg border border-slate-200 p-3">
                              <div className="text-xs text-slate-500">Доставка</div>
                              <div className="font-semibold">{Number(manualRecalc.deliveryCost || 0).toLocaleString()} ₽</div>
                            </div>
                            <div className="rounded-lg border border-slate-200 p-3">
                              <div className="text-xs text-slate-500">Разгрузка</div>
                              <div className="font-semibold">{Number(manualRecalc.unloadingCost || 0).toLocaleString()} ₽</div>
                            </div>
                            <div className="rounded-lg border border-slate-200 p-3">
                              <div className="text-xs text-slate-500">Итого</div>
                              <div className="font-semibold text-emerald-700">{Number(manualRecalc.totalCost || 0).toLocaleString()} ₽</div>
                            </div>
                          </div>

                          {manualRecalcTripItems.length ? (
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
                                  {manualRecalcTripItems.map((trip, i) => (
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

                          {manualRecalcDetails.length ? (
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
                                  {manualRecalcDetails.map((d, idx) => (
                                    <tr key={idx} className="border-b border-slate-100 align-top">
                                      <td className="p-3 whitespace-nowrap">{d["завод"]}</td>
                                      <td className="p-3 whitespace-pre-line text-slate-600">{d["контакт"] || "—"}</td>
                                      <td className="p-3">{d["товар"]}</td>
                                      <td className="p-3">{d["машина"]}</td>
                                      <td className="p-3">{d["расстояние_км"]}</td>
                                      <td className="p-3">{d["стоимость_материала"]?.toLocaleString?.() ?? d["стоимость_материала"]}</td>
                                      <td className="p-3">{d["стоимость_доставки"]?.toLocaleString?.() ?? d["стоимость_доставки"]}</td>
                                      <td className="p-3 font-semibold text-emerald-700">{d["итого"]?.toLocaleString?.() ?? d["итого"]}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    // fallback: если payload не в нашем формате, всё равно покажем raw
                    (Object.keys(manualDecisionPayload || {}).length ? (
                      <details className="rounded-xl border border-slate-200 bg-white p-3">
                        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                          Показать raw JSON ручного решения (manualPayload)
                        </summary>
                        <pre className="mt-2 text-xs overflow-auto">{JSON.stringify(manualDecisionPayload, null, 2)}</pre>
                      </details>
                    ) : null)
                  )}
                </div>
              ) : null}

              {selected?.status === "confirmed_auto" && selectedVariantSnapshot ? (
                <div className="rounded-xl border-2 border-emerald-200 bg-emerald-50/50 p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold">Автоматическое решение системы (сохранено)</div>
                      <div className="text-xs text-slate-600">
                        Это принятый системой вариант расчёта, сохранённый в момент подтверждения сценария.
                      </div>
                    </div>
                    {autoMachinesText ? (
                      <div className="text-right">
                        <div className="text-xs text-slate-500">Машины (доставка)</div>
                        <div className="font-semibold text-emerald-800">{autoMachinesText}</div>
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-xl bg-white border border-slate-200 p-3 space-y-3">
                    <div className="grid md:grid-cols-2 gap-3 text-sm">
                      <div>
                        <div className="text-xs text-slate-500">Машины доставки</div>
                        <div className="font-semibold text-slate-800">{autoMachinesText || "—"}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-500">Машины разгрузки</div>
                        <div className="font-semibold text-slate-800">{autoMachinesText || "—"}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-500">Транспорт доставки</div>
                        <div className="font-semibold">{transportTagLabel(quoteRequest.deliveryTransportTag)}</div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-500">Транспорт разгрузки</div>
                        <div className="font-semibold">{transportTagLabel(quoteRequest.unloadingTransportTag)}</div>
                      </div>
                    </div>

                    {Array.isArray(requestedItems) && requestedItems.length ? (
                      <div>
                        <div className="text-sm font-semibold text-slate-800 mb-2">Производства по позициям</div>
                        <div className="overflow-auto rounded-xl border border-slate-200">
                          <table className="w-full text-sm">
                            <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                              <tr>
                                <th className="p-3 text-left">Товар</th>
                                <th className="p-3 text-left">Кол-во</th>
                                <th className="p-3 text-left">Производство</th>
                              </tr>
                            </thead>
                            <tbody>
                              {requestedItems.map((it, idx) => (
                                <tr key={idx} className="border-b border-slate-100">
                                  <td className="p-3">
                                    {it?.category} / {it?.subtype}
                                  </td>
                                  <td className="p-3">{it?.quantity ?? "—"}</td>
                                  <td className="p-3 font-semibold">{autoFactoriesByItem[idx] || "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    ) : null}

                    <div className="text-sm font-semibold text-slate-800 pt-2">Сервисный расчёт</div>
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
                        <div className="text-xs text-slate-500">Разгрузка</div>
                        <div className="font-semibold">
                          {selectedVariantSnapshot.unloadingCost != null
                            ? `${Number(selectedVariantSnapshot.unloadingCost).toLocaleString()} ₽`
                            : "—"}
                        </div>
                      </div>
                      <div className="rounded-lg border border-slate-200 p-3">
                        <div className="text-xs text-slate-500">Итого</div>
                        <div className="font-semibold text-emerald-700">
                          {selectedVariantSnapshot.totalCost != null
                            ? `${Number(selectedVariantSnapshot.totalCost).toLocaleString()} ₽`
                            : "—"}
                        </div>
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
                              <tr key={idx} className="border-b border-slate-100">
                                <td className="p-3 whitespace-nowrap">{d["завод"]}</td>
                                <td className="p-3 whitespace-pre-line text-slate-600">{d["контакт"] || "—"}</td>
                                <td className="p-3">{d["товар"]}</td>
                                <td className="p-3">{d["машина"]}</td>
                                <td className="p-3">{d["расстояние_км"]}</td>
                                <td className="p-3">
                                  {d["стоимость_материала"]?.toLocaleString?.() ?? d["стоимость_материала"]}
                                </td>
                                <td className="p-3">
                                  {d["стоимость_доставки"]?.toLocaleString?.() ?? d["стоимость_доставки"]}
                                </td>
                                <td className="p-3 font-semibold text-emerald-700">
                                  {d["итого"]?.toLocaleString?.() ?? d["итого"]}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}

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
                        </tr>
                      </thead>
                      <tbody>
                        {variantsSummary.map((v) => {
                          const isSel = v.idx === selected?.selectedVariant;
                          return (
                            <tr key={v.idx} className={`border-b border-slate-100 ${isSel ? "bg-indigo-50" : ""}`}>
                              <td className="p-3 font-semibold">{v.idx + 1}</td>
                              <td className="p-3">
                                <div className="font-semibold text-slate-900">{v.transportName}</div>
                                {v.factoriesText ? (
                                  <div className="text-xs text-slate-500 mt-1">🏭 {v.factoriesText}</div>
                                ) : null}
                              </td>
                              <td className="p-3 font-semibold text-indigo-700">
                                {v.totalCost != null ? Number(v.totalCost).toLocaleString() : "—"}
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

              {selectedVariantSnapshot && selected?.status !== "confirmed_auto" ? (
                <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold">
                        {selected?.status === "confirmed_manual" ? "Выбранный вариант расчёта (ориентир)" : "Принятый вариант"}
                      </div>
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
                <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold">Ручное решение логиста (редактирование)</div>
                      <div className="text-xs text-slate-500">
                        Интерфейс совпадает с “Ручное заполнение (логист)” в калькуляторе.
                      </div>
                    </div>
                  </div>

                  <div className="grid md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-semibold text-slate-600 mb-1">Транспорт доставки</label>
                      <select
                        value={manualDeliveryTransportTag}
                        onChange={(e) => setManualDeliveryTransportTag(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
                      >
                        {TRANSPORT_TAGS.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-slate-600 mb-1">Транспорт разгрузки</label>
                      <select
                        value={manualUnloadingTransportTag}
                        onChange={(e) => setManualUnloadingTransportTag(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
                      >
                        {TRANSPORT_TAGS.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <div className="text-sm font-semibold text-slate-800 mb-2">Позиции и производства</div>
                    {Array.isArray(requestedItems) && requestedItems.length ? (
                      <div className="space-y-3">
                        {requestedItems.map((it, idx) => {
                          const options = manualFactoryOptionsByIndex[idx] || [];
                          const selectedFactory = manualFactoryByItem?.[idx] || "";
                          const selectedRow = options.find((r) => normStr(r?.name || r?.["название"]) === selectedFactory);
                          const label = `${it?.category || "—"} / ${it?.subtype || "—"} × ${it?.quantity ?? "—"}`;

                          return (
                            <div key={idx} className="rounded-lg bg-white border border-slate-200 p-3">
                              <div className="text-sm font-semibold text-slate-800 mb-2">{label}</div>
                              <div className="grid md:grid-cols-2 gap-3">
                                <div>
                                  <label className="block text-xs font-semibold text-slate-600 mb-1">Производство</label>
                                  <select
                                    value={selectedFactory}
                                    onChange={(e) => {
                                      const v = e.target.value;
                                      setManualFactoryByItem((prev) => {
                                        const next = Array.isArray(prev) ? [...prev] : [];
                                        next[idx] = v;
                                        return next;
                                      });
                                    }}
                                    className="w-full px-3 py-3 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
                                    disabled={options.length === 0}
                                  >
                                    <option value="">
                                      {options.length ? "Выберите производство…" : "Нет производств с этим товаром"}
                                    </option>
                                    {options.map((r) => {
                                      const nm = normStr(r?.name || r?.["название"]);
                                      return (
                                        <option key={nm} value={nm}>
                                          {nm}
                                        </option>
                                      );
                                    })}
                                  </select>
                                </div>
                                <div>
                                  <div className="text-xs font-semibold text-slate-600 mb-1">Контакт</div>
                                  <div className="text-sm text-slate-700 whitespace-pre-line">
                                    {normStr(selectedRow?.contact) || "—"}
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-sm text-slate-600">Нет позиций заказа.</div>
                    )}
                  </div>

                  <div className="grid md:grid-cols-2 gap-4">
                    <div>
                      <div className="flex items-center justify-between gap-3 mb-2">
                        <label className="block text-sm font-semibold text-slate-700">Машины доставки</label>
                        <button
                          type="button"
                          onClick={() => setManualDeliveryMachines((prev) => [...(prev || [""]), ""])}
                          className="px-3 py-2 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-100 font-semibold hover:bg-indigo-100"
                        >
                          ➕ Добавить
                        </button>
                      </div>
                      <div className="space-y-2">
                        {(manualDeliveryMachines || [""]).map((val, idx) => (
                          <div key={idx} className="flex gap-2">
                            <select
                              value={val}
                              onChange={(e) => {
                                const v = e.target.value;
                                setManualDeliveryMachines((prev) => {
                                  const next = Array.isArray(prev) ? [...prev] : [];
                                  next[idx] = v;
                                  return next;
                                });
                              }}
                              className="flex-1 px-3 py-3 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
                            >
                              <option value="">Выберите машину доставки…</option>
                              {(deliveryMachineOptions.length
                                ? deliveryMachineOptions
                                : uniqueTransportNames.map((n) => ({ name: n }))).map((x) => (
                                <option key={x.key || x.name} value={x.name}>
                                  {x.name}
                                  {x.tag ? ` (${x.tag})` : ""}
                                  {x.capacity != null ? ` • ${x.capacity}т` : ""}
                                </option>
                              ))}
                            </select>
                            {(manualDeliveryMachines || []).length > 1 ? (
                              <button
                                type="button"
                                onClick={() => setManualDeliveryMachines((prev) => (prev || []).filter((_, i) => i !== idx))}
                                className="px-3 py-3 rounded-lg bg-red-50 text-red-700 border border-red-100 font-semibold hover:bg-red-100"
                                title="Удалить"
                              >
                                ✕
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                      <div className="text-xs text-slate-500 mt-2">
                        Список берётся из тарифов и фильтруется по выбранному “транспорту доставки”.
                      </div>
                    </div>

                    <div>
                      <div className="flex items-center justify-between gap-3 mb-2">
                        <label className="block text-sm font-semibold text-slate-700">Машины разгрузки</label>
                        <button
                          type="button"
                          onClick={() => setManualUnloadingMachines((prev) => [...(prev || [""]), ""])}
                          className="px-3 py-2 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-100 font-semibold hover:bg-indigo-100"
                        >
                          ➕ Добавить
                        </button>
                      </div>
                      <div className="space-y-2">
                        {(manualUnloadingMachines || [""]).map((val, idx) => (
                          <div key={idx} className="flex gap-2">
                            <select
                              value={val}
                              onChange={(e) => {
                                const v = e.target.value;
                                setManualUnloadingMachines((prev) => {
                                  const next = Array.isArray(prev) ? [...prev] : [];
                                  next[idx] = v;
                                  return next;
                                });
                              }}
                              className="flex-1 px-3 py-3 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
                            >
                              <option value="">Выберите машину разгрузки…</option>
                              {(unloadingMachineOptions.length
                                ? unloadingMachineOptions
                                : uniqueTransportNames.map((n) => ({ name: n }))).map((x) => (
                                <option key={x.key || x.name} value={x.name}>
                                  {x.name}
                                  {x.tag ? ` (${x.tag})` : ""}
                                  {x.capacity != null ? ` • ${x.capacity}т` : ""}
                                </option>
                              ))}
                            </select>
                            {(manualUnloadingMachines || []).length > 1 ? (
                              <button
                                type="button"
                                onClick={() => setManualUnloadingMachines((prev) => (prev || []).filter((_, i) => i !== idx))}
                                className="px-3 py-3 rounded-lg bg-red-50 text-red-700 border border-red-100 font-semibold hover:bg-red-100"
                                title="Удалить"
                              >
                                ✕
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                      <div className="text-xs text-slate-500 mt-2">
                        Список берётся из тарифов и фильтруется по выбранному “транспорту разгрузки”.
                      </div>
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-semibold text-slate-700 mb-1">Комментарий</label>
                    <textarea
                      value={manualNotes}
                      onChange={(e) => setManualNotes(e.target.value)}
                      rows={3}
                      className="w-full px-3 py-2 rounded-lg bg-white border border-slate-200 text-slate-800"
                      placeholder="Например: согласовано с клиентом, требуется 2 рейса, и т.д."
                    />
                  </div>

                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={handleManualConfirm}
                      className="px-4 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500"
                    >
                      Подтвердить вручную
                    </button>
                  </div>
                </div>
              ) : null}

              {canViewAdminOnly ? (
                <>
                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    <div className="font-semibold mb-2">События</div>
                    {Array.isArray(selected.events) && selected.events.length ? (
                      <ul className="text-sm text-slate-700 space-y-2">
                        {selected.events.map((e) => (
                          <li key={e.id} className="border border-slate-100 rounded-lg p-2">
                            <div className="flex items-center justify-between">
                              <span className="font-semibold">{eventHumanLabel(e.type)}</span>
                              <span className="text-xs text-slate-500">
                                {e.createdAt ? new Date(e.createdAt).toLocaleString() : ""}
                              </span>
                            </div>
                            <div className="text-xs text-slate-500">user: {e.user || "—"}</div>
                            {eventSummary(e.type, e.payload) ? (
                              <div className="mt-1 text-xs text-slate-600">{eventSummary(e.type, e.payload)}</div>
                            ) : null}
                            {e.payload ? (
                              <details className="mt-2 rounded-lg bg-slate-50 border border-slate-200 p-2">
                                <summary className="cursor-pointer text-xs font-semibold text-slate-700">
                                  Показать payload
                                </summary>
                                <pre className="mt-2 text-xs overflow-auto">{JSON.stringify(e.payload, null, 2)}</pre>
                              </details>
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
                </>
              ) : (
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="font-semibold mb-1">События</div>
                  <div className="text-sm text-slate-500">Доступ: только админ и выше.</div>
                </div>
              )}

              {canDeleteOrder ? (
                <div className="rounded-xl border border-red-200 bg-red-50/50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-red-900">Опасная зона</div>
                      <div className="text-xs text-red-800/80 mt-1">
                        Удаление заказа необратимо. Требуется пароль администратора.
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setDeleteOpen(true)}
                      className="px-3 py-2 rounded-lg bg-red-600 text-white font-semibold hover:bg-red-500"
                    >
                      🗑️ Удалить заказ
                    </button>
                  </div>
                </div>
              ) : null}
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
