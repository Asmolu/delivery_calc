import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  getCategories,
  getQuote,
  getCurrentUser,
  isAuthenticated,
  confirmOrderFromQuote,
  rejectOrderForManual,
  manualConfirmOrder,
  fetchFactories,
} from "../api";
import { API_BASE } from "../api";

function MultiSelectDropdown({ options, value, onChange, placeholder = "Нет" }) {
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef(null);

  const selected = Array.isArray(value) ? value : [];
  const selectedSet = React.useMemo(() => new Set(selected), [selected]);
  const available = React.useMemo(
    () => (options || []).filter((o) => !selectedSet.has(o.value)),
    [options, selectedSet]
  );

  React.useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (!rootRef.current) return;
      if (rootRef.current.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const addValue = (v) => {
    if (!v) return;
    if (selectedSet.has(v)) return;
    onChange([...(selected || []), v]);
    setOpen(false);
  };

  const removeValue = (v) => {
    onChange((selected || []).filter((x) => x !== v));
  };

  return (
    <div ref={rootRef} className={`relative ${open ? "z-[9999]" : ""}`}>
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        className="w-full px-3 py-2 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm text-left flex items-center justify-between gap-2"
      >
        <span className="text-sm text-slate-700">
          {open ? "Выберите…" : selected.length ? (available.length ? "Добавить…" : "Нет доступных") : placeholder}
        </span>
        <span className="text-slate-400">▾</span>
      </button>

      {selected.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {selected.map((v) => {
            const opt = (options || []).find((o) => o.value === v);
            const label = opt?.label || v;
            return (
              <span
                key={v}
                className="inline-flex items-center gap-2 px-2 py-1 rounded-full bg-slate-100 border border-slate-200 text-slate-700 text-xs"
              >
                {label}
                <button
                  type="button"
                  onClick={() => removeValue(v)}
                  className="text-slate-500 hover:text-slate-800"
                  title="Убрать"
                >
                  ✕
                </button>
              </span>
            );
          })}
        </div>
      ) : (
        <div className="mt-2 text-xs text-slate-500">{placeholder}</div>
      )}

      {open ? (
        <div className="absolute z-[9999] mt-2 w-full rounded-xl border border-slate-200 bg-white shadow-lg overflow-hidden">
          <div className="max-h-56 overflow-auto">
            {available.length ? (
              available.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => addValue(o.value)}
                  className="w-full text-left px-3 py-2 text-sm text-slate-800 hover:bg-slate-50"
                >
                  {o.label}
                </button>
              ))
            ) : (
              <div className="px-3 py-3 text-sm text-slate-500">Нечего добавлять</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function Calculator() {
  const MotionDiv = motion.div;
  const [categories, setCategories] = useState({});
  const [items, setItems] = useState([{ category: "", subtype: "", quantity: 1 }]);
  const [coords, setCoords] = useState("");
  const [allowedDeliveryTags, setAllowedDeliveryTags] = useState([]);
  const [allowedUnloadingTags, setAllowedUnloadingTags] = useState([]);
  const [forbiddenDeliveryTags, setForbiddenDeliveryTags] = useState([]);
  const [forbiddenUnloadingTags, setForbiddenUnloadingTags] = useState([]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tariffs, setTariffs] = useState([]);

  const [currentUser, setCurrentUser] = useState(null);
  const ORG_RANK = { viewer: 10, manager: 20, logist: 30, admin: 40, owner: 50 };
  const orgRank = (r) => ORG_RANK[String(r || "").toLowerCase()] || 0;
  const canLogist = orgRank(currentUser?.orgRole) >= ORG_RANK.logist;
  const canAdmin = orgRank(currentUser?.orgRole) >= ORG_RANK.admin;
  const isAuthed = isAuthenticated();

  const [actionsOpen, setActionsOpen] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [logisticsModalOpen, setLogisticsModalOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualOrderId, setManualOrderId] = useState(null);
  const [manualDeliveryMachines, setManualDeliveryMachines] = useState([""]);
  const [manualUnloadingMachines, setManualUnloadingMachines] = useState([""]);
  const [manualNotes, setManualNotes] = useState("");
  const [manualItemsSnapshot, setManualItemsSnapshot] = useState([]);
  const [manualFactoryByItem, setManualFactoryByItem] = useState([]);
  const [factoriesFlat, setFactoriesFlat] = useState([]);

  const TRANSPORT_TAGS = React.useMemo(
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

  const UNLOADING_SPECIAL_OPTIONS = React.useMemo(
    () => [{ value: "none", label: "Нет разгрузки (на объекте есть техника)" }],
    []
  );

  const normStr = (x) => String(x ?? "").trim();
  const normKey = (x) => normStr(x).toLowerCase();

  const forbiddenTransportOptions = React.useMemo(() => {
    return (TRANSPORT_TAGS || [])
      .filter((t) => t.value !== "auto")
      .map((t) => ({ value: t.value, label: t.label }));
  }, [TRANSPORT_TAGS]);

  const unloadingAllowedOptions = React.useMemo(() => {
    return [...UNLOADING_SPECIAL_OPTIONS, ...(forbiddenTransportOptions || [])];
  }, [UNLOADING_SPECIAL_OPTIONS, forbiddenTransportOptions]);

  const deliveryTransportTag = React.useMemo(() => {
    // legacy single-tag field: если выбран ровно 1 тег — отправим его, иначе "auto"
    const v = (allowedDeliveryTags || []).map((x) => normStr(x).toLowerCase()).filter(Boolean);
    if (v.length === 1) return v[0];
    return "auto";
  }, [allowedDeliveryTags]);

  const unloadingTransportTag = React.useMemo(() => {
    const v = (allowedUnloadingTags || []).map((x) => normStr(x).toLowerCase()).filter(Boolean);
    if (v.length === 1) return v[0];
    return "auto";
  }, [allowedUnloadingTags]);

  const factoryUpdateDateByName = React.useMemo(() => {
    const map = new Map();
    for (const row of factoriesFlat || []) {
      const name = normKey(row?.name || row?.["название"]);
      if (!name) continue;
      const date = normStr(row?.update_date || row?.updateDate || row?.["дата актуализации"] || row?.["дата"]);
      if (!date) continue;
      if (!map.has(name)) map.set(name, date);
    }
    return map;
  }, [factoriesFlat]);

  const allowedDeliverySet = React.useMemo(() => {
    return new Set((allowedDeliveryTags || []).map((x) => normStr(x).toLowerCase()).filter(Boolean));
  }, [allowedDeliveryTags]);

  const allowedUnloadingSet = React.useMemo(() => {
    return new Set((allowedUnloadingTags || []).map((x) => normStr(x).toLowerCase()).filter(Boolean));
  }, [allowedUnloadingTags]);

  const unloadingDisabled = React.useMemo(() => {
    return unloadingTransportTag === "none" || allowedUnloadingSet.has("none");
  }, [unloadingTransportTag, allowedUnloadingSet]);

  const manualUnloadingDisabled = React.useMemo(() => {
    const hasManualNone = (manualUnloadingMachines || []).some((x) => normStr(x).toLowerCase() === "none");
    return unloadingDisabled || hasManualNone;
  }, [manualUnloadingMachines, unloadingDisabled]);

  const getTariffName = (t) => t?.name || t?.["название"] || "";
  const getTariffTag = (t) => t?.tag || t?.["тег"] || "";
  const getTariffServiceType = (t) => t?.service_type || t?.serviceType || "delivery";

  const transportCards = React.useMemo(() => {
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
          unloadTags: Array.isArray(t?.unload_tags) ? t.unload_tags : null,
          selfLoading: !!t?.self_loading,
        });
      }
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [tariffs]);

  const deliveryMachineOptions = React.useMemo(() => {
    return transportCards.filter(
      (c) =>
        c.serviceType === "delivery" &&
        (allowedDeliverySet.size ? allowedDeliverySet.has(c.tag) : true)
    );
  }, [transportCards, allowedDeliverySet]);

  const unloadingMachineOptions = React.useMemo(() => {
    return transportCards.filter(
      (c) =>
        c.serviceType === "unloading" &&
        (allowedUnloadingSet.size ? allowedUnloadingSet.has(c.tag) : true)
    );
  }, [transportCards, allowedUnloadingSet]);

  useEffect(() => {
    async function load() {
      const data = await getCategories();
      setCategories(data || {});

      try {
        const res = await fetch(`${API_BASE}/api/tariffs`);
        const t = await res.json();
        setTariffs(Array.isArray(t) ? t : []);
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

  useEffect(() => {
    if (!isAuthenticated()) return;
    getCurrentUser().then(setCurrentUser).catch(() => setCurrentUser(null));
  }, []);

  useEffect(() => {
    if (Array.isArray(factoriesFlat) && factoriesFlat.length > 0) return;

    fetchFactories()
      .then((rows) => setFactoriesFlat(Array.isArray(rows) ? rows : []))
      .catch((e) => {
        console.error("Ошибка загрузки /api/factories:", e);
        setFactoriesFlat([]);
      });
    }, [factoriesFlat]);

  const uniqueTransportNames = React.useMemo(() => {
    const names = new Set();
    for (const t of tariffs || []) {
      const name = t?.name || t?.["название"];
      if (name) names.add(name);
    }
    return Array.from(names).sort((a, b) => String(a).localeCompare(String(b)));
  }, [tariffs]);

  const buildOrderSnapshot = (quoteRequestPayload) => {
    return {
      request: quoteRequestPayload,
      variants: result?.variants || [],
      selectedVariant: result?.selectedVariant ?? 0,
      warningText: result?.warningText || null,
      needsLogisticsCheck: !!result?.needsLogisticsCheck,
    };
  };

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
      const forbidDelivery = Array.from(
        new Set((forbiddenDeliveryTags || []).map((x) => normStr(x).toLowerCase()).filter(Boolean))
      );
      const forbidUnloading = Array.from(
        new Set((forbiddenUnloadingTags || []).map((x) => normStr(x).toLowerCase()).filter(Boolean))
      );
      // whitelist не должен одновременно попадать в запреты
      for (const t of allowedDeliverySet) {
        const idx = forbidDelivery.indexOf(t);
        if (idx >= 0) forbidDelivery.splice(idx, 1);
      }
      for (const t of allowedUnloadingSet) {
        const idx = forbidUnloading.indexOf(t);
        if (idx >= 0) forbidUnloading.splice(idx, 1);
      }

      const allowDelivery = Array.from(allowedDeliverySet);
      const allowUnloading = Array.from(allowedUnloadingSet);
      const payload = {
        upload_lat: lat,
        upload_lon: lon,
        transport_type: "auto",
        deliveryTransportTag: deliveryTransportTag,
        unloadingTransportTag: unloadingTransportTag,
        allowedDeliveryTags: allowDelivery,
        allowedUnloadingTags: allowUnloading,
        forbiddenDeliveryTags: forbidDelivery,
        forbiddenUnloadingTags: forbidUnloading,
        items: items.map((it) => ({
          category: it.category,
          subtype: it.subtype,
          quantity: parseInt(it.quantity, 10),
        })),
      };

      const data = await getQuote(payload);
      if (data?.variants) {
        if (data?.needsLogisticsCheck) setLogisticsModalOpen(true);
        setResult({ ...data, selectedVariant: 0, _lastQuoteRequest: payload });
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
          _lastQuoteRequest: payload,
        };
        if (localized?.needsLogisticsCheck) setLogisticsModalOpen(true);
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

  const handleConfirmScenario = async () => {
    if (!canLogist || !result?.variants?.length) return;
    const reqPayload = result?._lastQuoteRequest;
    if (!reqPayload) {
      alert("Не найден снимок запроса для сохранения заказа");
      return;
    }
    try {
      setActionBusy(true);
      const snapshot = buildOrderSnapshot(reqPayload);
      const resp = await confirmOrderFromQuote(snapshot);
      if (resp?.id != null) {
        sessionStorage.setItem("selected_order_id", String(resp.id));
      }
      setActionsOpen(false);
      alert(`✅ Сценарий подтверждён. Заказ #${resp?.id}`);
    } catch (e) {
      alert(e?.message || "Ошибка сохранения заказа");
    } finally {
      setActionBusy(false);
    }
  };

  const handleRejectAndOpenManual = async () => {
    if (!canLogist || !result?.variants?.length) return;
    const reqPayload = result?._lastQuoteRequest;
    if (!reqPayload) {
      alert("Не найден снимок запроса для сохранения заказа");
      return;
    }
    try {
      setActionBusy(true);
      const snapshot = buildOrderSnapshot(reqPayload);
      const resp = await rejectOrderForManual(snapshot);
      if (resp?.id != null) {
        sessionStorage.setItem("selected_order_id", String(resp.id));
      }
      setManualOrderId(resp?.id || null);
      setManualDeliveryMachines([""]);
      setManualUnloadingMachines([""]);
      setManualNotes("");
      const itemsSnap = Array.isArray(reqPayload?.items) ? reqPayload.items : [];
      setManualItemsSnapshot(itemsSnap);
      setManualFactoryByItem(itemsSnap.map(() => ""));
      setManualOpen(true);
      setActionsOpen(false);
    } catch (e) {
      alert(e?.message || "Ошибка отклонения сценария");
    } finally {
      setActionBusy(false);
    }
  };

  const manualFactoryOptionsByIndex = React.useMemo(() => {
    const itemsSnap = Array.isArray(manualItemsSnapshot) ? manualItemsSnapshot : [];
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
      // уникализируем по имени завода
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
  }, [manualItemsSnapshot, factoriesFlat]);

  const handleManualConfirm = async () => {
    if (!manualOrderId) {
      alert("Не найден orderId для ручного подтверждения");
      return;
    }
    const canPickDeliveryMachine = deliveryMachineOptions.length > 0 || uniqueTransportNames.length > 0;
    const canPickUnloadingMachine =
    !manualUnloadingDisabled && (unloadingMachineOptions.length > 0 || uniqueTransportNames.length > 0);
    const deliveryNames = (manualDeliveryMachines || []).map((x) => normStr(x)).filter(Boolean);
    const unloadingNames = manualUnloadingDisabled
      ? []
      : (manualUnloadingMachines || []).map((x) => normStr(x)).filter(Boolean);
    if (canPickDeliveryMachine && deliveryNames.length === 0) {
      alert("Добавьте хотя бы одну машину доставки");
      return;
    }
    if (canPickUnloadingMachine && unloadingNames.length === 0) {
      alert("Добавьте хотя бы одну машину разгрузки");
      return;
    }
    const itemsSnap = Array.isArray(manualItemsSnapshot) ? manualItemsSnapshot : [];
    if (itemsSnap.length) {
      for (let i = 0; i < itemsSnap.length; i++) {
        const hasOptions = Array.isArray(manualFactoryOptionsByIndex?.[i]) && manualFactoryOptionsByIndex[i].length > 0;
        if (hasOptions && !normStr(manualFactoryByItem?.[i])) {
          alert("Выберите производство для всех позиций");
          return;
        }
      }
    }
    try {
      setActionBusy(true);
      const deliveryNameFinal = (deliveryNames.join(" + ") || "manual").trim();
      const unloadingNameFinal = manualUnloadingDisabled ? "none" : (unloadingNames.join(" + ") || "manual").trim();
      const manualPayload = {
        deliveryMachineName: deliveryNameFinal, // legacy single string
        unloadingMachineName: unloadingNameFinal, // legacy single string
        deliveryMachines: deliveryNames,
        unloadingMachines: unloadingNames,
        deliveryTransportTag,
        unloadingTransportTag: manualUnloadingDisabled ? "none" : unloadingTransportTag,
        allowedDeliveryTags: Array.from(allowedDeliverySet),
        allowedUnloadingTags: manualUnloadingDisabled ? ["none"] : Array.from(allowedUnloadingSet),
        items: itemsSnap.map((it, idx) => ({
          category: it?.category,
          subtype: it?.subtype,
          quantity: it?.quantity,
          factoryName: manualFactoryByItem?.[idx] || null,
        })),
      };
      await manualConfirmOrder(manualOrderId, {
        transportName: deliveryNameFinal,
        notes: manualNotes || null,
        payload: {
          selectedVariant: result?.selectedVariant ?? 0,
          manual: manualPayload,
        },
      });
      sessionStorage.setItem("selected_order_id", String(manualOrderId));
      setManualOpen(false);
      alert(`✅ Заказ #${manualOrderId} подтверждён вручную`);
    } catch (e) {
      alert(e?.message || "Ошибка ручного подтверждения");
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <MotionDiv
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
        {/* card-glass has backdrop-filter -> creates stacking context.
            Ensure dropdowns can overlay next sections by raising this card's z-index. */}
        <div className="card-glass relative z-50 p-5 md:p-6 md:col-span-2 space-y-4">
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
              <label className="block mb-2 text-sm font-semibold text-slate-700">Выберете транспорт доставки</label>
              <MultiSelectDropdown
                options={forbiddenTransportOptions}
                value={allowedDeliveryTags}
                onChange={(next) => {
                  const normNext = Array.from(new Set((next || []).map((x) => normStr(x).toLowerCase()).filter(Boolean)));
                  setAllowedDeliveryTags(normNext);
                  const nextSet = new Set(normNext);
                  setForbiddenDeliveryTags((prev) => (prev || []).filter((x) => !nextSet.has(normStr(x).toLowerCase())));
                }}
                placeholder="Авто"
              />
              <div className="text-xs text-slate-500 mt-1">
                {allowedDeliveryTags?.length ? "Расчёт будет только по выбранным тегам." : "Если ничего не выбрано — ограничений нет."}
              </div>

              <div className="mt-3">
                <label className="block mb-2 text-sm font-semibold text-slate-700">
                  Запрещённый транспорт доставки (можно несколько)
                </label>
                <MultiSelectDropdown
                  options={forbiddenTransportOptions}
                  value={forbiddenDeliveryTags}
                  onChange={setForbiddenDeliveryTags}
                  placeholder="Нет"
                />
              </div>
            </div>
            <div>
              <label className="block mb-2 text-sm font-semibold text-slate-700">Выберете транспорт разгрузки</label>
              <MultiSelectDropdown
                options={unloadingAllowedOptions}
                value={allowedUnloadingTags}
                onChange={(next) => {
                  const normNext = Array.from(
                    new Set((next || []).map((x) => normStr(x).toLowerCase()).filter(Boolean))
                  );
                  // "none" эксклюзивен: если выбран — оставляем только его и убираем запреты
                  if (normNext.includes("none")) {
                    setAllowedUnloadingTags(["none"]);
                    setForbiddenUnloadingTags([]);
                    return;
                  }
                  const cleaned = normNext.filter((x) => x !== "none");
                  setAllowedUnloadingTags(cleaned);
                  const nextSet = new Set(cleaned);
                  setForbiddenUnloadingTags((prev) =>
                    (prev || []).filter((x) => !nextSet.has(normStr(x).toLowerCase()))
                  );
                }}
                placeholder="Авто"
              />
              <div className="text-xs text-slate-500 mt-1">
                {unloadingDisabled
                  ? "Разгрузка не будет посчитана (на объекте есть своя техника)."
                  : allowedUnloadingTags?.length
                    ? "Разгрузка будет только по выбранным тегам."
                    : "Если ничего не выбрано — ограничений нет."}
              </div>

              <div className="mt-3">
                <label className="block mb-2 text-sm font-semibold text-slate-700">
                  Запрещённый транспорт разгрузки (можно несколько)
                </label>
                <MultiSelectDropdown
                  options={forbiddenTransportOptions}
                  value={forbiddenUnloadingTags}
                  onChange={setForbiddenUnloadingTags}
                  placeholder="Нет"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="card-glass p-5 md:p-6">
          <h3 className="text-lg font-semibold mb-3">Товары</h3>
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

      {/* Keep below filter card so dropdowns overlay it */}
      <div className="card-glass relative z-0 p-6 md:p-8 flex flex-col gap-4">
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
        <MotionDiv initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="card-glass p-6 md:p-8">
          {result.warningText ? (
            <div className="mb-6 rounded-2xl border-2 border-amber-300 bg-gradient-to-r from-amber-50 to-white text-amber-950 px-5 py-4 shadow-lg">
              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-amber-700">Требует внимания</div>
                  <div className="text-xl font-extrabold mt-1">⚠️ {result.warningText}</div>
                  {Array.isArray(result.warningReasons) && result.warningReasons.length ? (
                    <ul className="mt-2 text-sm text-amber-900 list-disc pl-5 space-y-1">
                      {result.warningReasons.slice(0, 5).map((r, idx) => (
                        <li key={idx}>{r}</li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-sm text-amber-900 mt-2">
                      Заказ содержит товары из разных категорий — перевозки будут рассчитаны раздельно.
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setLogisticsModalOpen(true)}
                    className="px-4 py-2 rounded-xl bg-amber-600 text-white font-semibold hover:bg-amber-500"
                  >
                    Что делать?
                  </button>
                  {canLogist ? (
                    <button
                      type="button"
                      disabled={actionBusy}
                      onClick={async () => {
                        setLogisticsModalOpen(false);
                        await handleRejectAndOpenManual();
                      }}
                      className="px-4 py-2 rounded-xl bg-white border-2 border-amber-300 text-amber-900 font-semibold hover:border-amber-400 disabled:opacity-60"
                    >
                      Отклонить и заполнить вручную
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
          <div className="flex flex-col gap-3 mb-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="pill mb-2">Найдено {result.variants.length} вариантов</p>
              <h3 className="text-2xl font-semibold">Сравнение предложений</h3>
              <p className="text-slate-600">Кликните на карточку, чтобы увидеть детали рейсов и тарифов.</p>
            </div>
            <div className="flex items-center gap-2">
              <div
                className={`text-xs font-semibold px-3 py-2 rounded-xl border ${
                  canLogist ? "bg-emerald-50 border-emerald-200 text-emerald-900" : "bg-slate-50 border-slate-200 text-slate-700"
                }`}
              >
                Детализация: {canLogist ? "доступна" : "недоступна"} · детали доступны логисту и выше
                {!canLogist ? (isAuthed ? ` (ваша роль: ${currentUser?.orgRole || "—"})` : " (войдите)") : ""}
              </div>
              {!isAuthed ? (
                <a
                  href="/login"
                  className="px-3 py-2 rounded-xl bg-white border border-slate-200 text-slate-700 font-semibold hover:border-indigo-200"
                >
                  Войти
                </a>
              ) : null}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-6">
            {result.variants.map((variant, idx) => {
              const layoutClass = idx < 3 ? "md:col-span-2" : "md:col-span-3";
              return (
                <button
                  type="button"
                  key={idx}
                  onClick={() => setResult({ ...result, selectedVariant: idx })}
                  className={`text-left rounded-xl p-4 transition shadow-sm border ${layoutClass} ${
                    result.selectedVariant === idx
                      ? "bg-indigo-50 border-indigo-200 shadow-md"
                      : "bg-white border-slate-200 hover:border-indigo-200"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="text-sm text-slate-500">Вариант #{idx + 1}</div>
                    {variant?.isSingleFactory ? (
                      <div className="text-[11px] font-semibold px-2 py-1 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200">
                        1 завод{variant?.singleFactoryName ? `: ${variant.singleFactoryName}` : ""}
                      </div>
                    ) : null}
                    </div>
                    {(() => {
                      const plans = Array.isArray(variant?.transportDetails) ? variant.transportDetails : [];
                      const factories = Array.from(new Set(plans.map((p) => p?.factory_name).filter(Boolean)));
                      const productionLabel =
                        variant?.singleFactoryName ||
                        (factories.length === 1 ? factories[0] : (factories.length ? factories.join(", ") : "—"));
                      const unloadingMachine =
                        Number(variant?.unloadingCost || 0) > 0 ? (variant?.unloading?.tariff_name || "—") : "—";
                      const deliveryMachine = variant?.transportName || "—";
  
                      return (
                        <>
                          <div className="text-lg font-semibold mb-1">🚚 {deliveryMachine}</div>
                          <p className="text-indigo-700 font-bold text-xl mb-1">
                            {variant.totalCost != null ? `${variant.totalCost.toLocaleString()} ₽` : "—"}
                          </p>
                          <div className="mt-2 text-sm text-slate-600 space-y-1">
                            <div>
                              <span className="text-slate-400">Производство:</span> {productionLabel}
                            </div>
                            <div>
                              <span className="text-slate-400">Количество рейсов:</span> {variant.tripCount ?? 0}
                            </div>
                            <div>
                              <span className="text-slate-400">Машина разгрузки:</span> {unloadingMachine}
                            </div>
                            <div>
                              <span className="text-slate-400">Машина доставки:</span> {deliveryMachine}
                            </div>
                          </div>
                        </>
                      );
                    })()}
                  </button>
                );
              })}
          </div>

          {result.selectedVariant !== undefined && (() => {
            const activeVariant = result.variants[result.selectedVariant] || {};
            const tripItems = Array.isArray(activeVariant.tripItems) ? activeVariant.tripItems : [];
            const detailRows = Array.isArray(activeVariant.details) ? activeVariant.details : [];
            const unloading = activeVariant.unloading || null;
            const unloadingCost = Number(activeVariant.unloadingCost || 0);
            const summaryMaterial = Number(activeVariant.materialCost || 0);
            const summaryDelivery = Number(activeVariant.deliveryCost || 0);
            const summaryTotal =
              activeVariant.totalCost != null
                ? Number(activeVariant.totalCost || 0)
                : summaryMaterial + summaryDelivery + unloadingCost;

            const sumMaterial = (detailRows || []).reduce((acc, r) => acc + Number(r?.["стоимость_материала"] || 0), 0);
            const sumDelivery = (detailRows || []).reduce((acc, r) => acc + Number(r?.["стоимость_доставки"] || 0), 0);
            const sumTotalWithUnloading = sumMaterial + sumDelivery + unloadingCost;

            return (
              <div className="mt-10 space-y-6">
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="text-sm font-semibold text-slate-800 mb-2">Итоги варианта</div>
                  <div className="grid gap-2 sm:grid-cols-4">
                    <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
                      <div className="text-xs text-slate-500">Материал</div>
                      <div className="text-lg font-semibold text-slate-900">{summaryMaterial.toLocaleString()} ₽</div>
                    </div>
                    <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
                      <div className="text-xs text-slate-500">Доставка</div>
                      <div className="text-lg font-semibold text-slate-900">{summaryDelivery.toLocaleString()} ₽</div>
                    </div>
                    <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
                      <div className="text-xs text-slate-500">Разгрузка</div>
                      <div className="text-lg font-semibold text-slate-900">{unloadingCost.toLocaleString()} ₽</div>
                    </div>
                    <div className="rounded-lg bg-emerald-900/20 border border-emerald-400/30 p-3">
                      <div className="text-xs text-emerald-200">Итого</div>
                      <div className="text-lg font-bold text-emerald-100">{summaryTotal.toLocaleString()} ₽</div>
                    </div>
                  </div>
                </div>

                {canLogist ? (
                  <>
                    <div className="overflow-auto rounded-xl border border-slate-200 bg-slate-900/70 shadow-sm">
                      <table className="w-full text-sm text-slate-200">
                        <thead className="bg-slate-900/50 text-slate-300 border-b border-slate-800">
                          <tr>
                            <th className="p-3 text-left">Производство</th>
                            <th className="p-3 text-left">Дата актуализации</th>
                            <th className="p-3 text-left">Контакт</th>
                            <th className="p-3 text-left">Товар</th>
                            <th className="p-3 text-left">Материал (₽)</th>
                            <th className="p-3 text-left">Машина</th>
                            <th className="p-3 text-left">Доставка (₽)</th>
                            <th className="p-3 text-left">Разгрузка</th>
                            <th className="p-3 text-left">Разгрузка (₽)</th>
                            <th className="p-3 text-left">Итого (₽)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detailRows.map((d, idx) => (
                            <tr key={idx} className="border-b border-slate-800">
                              <td className="p-3 whitespace-nowrap">{d["завод"]}</td>
                              <td className="p-3 whitespace-nowrap">
                                {factoryUpdateDateByName.get(normKey(d["завод"])) || "—"}
                              </td>
                              <td className="p-3 whitespace-pre-line text-slate-400">{d["контакт"] || "—"}</td>
                              <td className="p-3">{d["товар"]}</td>
                              <td className="p-3">{d["стоимость_материала"]?.toLocaleString()}</td>
                              <td className="p-3">{d["машина"]}</td>
                              <td className="p-3">{d["стоимость_доставки"]?.toLocaleString()}</td>
                              <td className="p-3 text-slate-300 whitespace-pre-line">{d["разгрузка"] || "—"}</td>
                              <td className="p-3">{detailRows.length === 1 ? `${unloadingCost.toLocaleString()} ₽` : "—"}</td>
                              <td className="p-3 text-indigo-300 font-semibold">
                                {(Number(d["итого"] || 0) + (detailRows.length === 1 ? unloadingCost : 0)).toLocaleString()}
                              </td>
                            </tr>
                          ))}
                          {/* Summary rows (to avoid double-counting unloading when factories > 1) */}
                          {detailRows.length > 1 ? (
                            <>
                              <tr className="border-t border-slate-700 bg-slate-900/30">
                              <td className="p-3 font-semibold" colSpan={8}>Разгрузка</td>
                                <td className="p-3 text-indigo-200 font-semibold">{unloadingCost.toLocaleString()} ₽</td>
                                <td className="p-3">—</td>
                              </tr>
                              <tr className="border-t border-slate-700 bg-slate-900/40">
                              <td className="p-3 font-bold" colSpan={4}>Итого по варианту</td>
                                <td className="p-3 font-bold text-slate-100">{sumMaterial.toLocaleString()} ₽</td>
                                <td className="p-3">—</td>
                                <td className="p-3 font-bold text-slate-100">{sumDelivery.toLocaleString()} ₽</td>
                                <td className="p-3">—</td>
                                <td className="p-3 font-bold text-indigo-200">{unloadingCost.toLocaleString()} ₽</td>
                                <td className="p-3 font-bold text-emerald-200">{sumTotalWithUnloading.toLocaleString()} ₽</td>
                              </tr>
                            </>
                          ) : null}
                        </tbody>
                      </table>
                    </div>

                    {tripItems.length > 0 ? (
                      <div className="overflow-auto rounded-xl border border-slate-200 bg-slate-900/70 shadow-sm">
                        <div className="p-4 border-b border-slate-800 flex items-center gap-2 text-slate-200">
                          🚚 Что везёт каждая машина
                        </div>
                        <table className="w-full text-sm text-slate-200">
                          <thead className="bg-slate-900/50 text-slate-300 border-b border-slate-800">
                            <tr>
                              <th className="p-3 text-left">Производство</th>
                              <th className="p-3 text-left">Дата актуализации</th>
                              <th className="p-3 text-left">Расстояние (км)</th>
                              <th className="p-3 text-left">Машина</th>
                              <th className="p-3 text-left">Тариф</th>
                              <th className="p-3 text-left">Товары</th>
                              <th className="p-3 text-left">Загрузка (т)</th>
                              <th className="p-3 text-left">Разгрузка</th>
                              <th className="p-3 text-left">Доставка (₽)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {tripItems.map((trip, i) => (
                              <tr key={i} className="border-b border-slate-800 align-top">
                                <td className="p-3 whitespace-nowrap">{trip["завод"]}</td>
                                <td className="p-3 whitespace-nowrap">
                                  {factoryUpdateDateByName.get(normKey(trip["завод"])) || "—"}
                                </td>
                                <td className="p-3">{trip["расстояние_км"]}</td>
                                <td className="p-3">{trip["машина"]}</td>
                                <td className="p-3 text-slate-300 whitespace-pre-line">{trip["тариф"] || "—"}</td>
                                <td className="p-3 text-slate-100">{trip["товары"]}</td>
                                <td className="p-3">{trip["загрузка_т"]}</td>
                                <td className="p-3 text-slate-300 whitespace-pre-line">{trip["разгрузка"] || "—"}</td>
                                <td className="p-3">{Number(trip["стоимость_доставки"] || 0).toLocaleString()}</td>
                              </tr>
                            ))}
                            {/* Add explicit unloading row for clarity */}
                            {unloading ? (
                              <tr className="border-t border-slate-700 bg-slate-900/30">
                                <td className="p-3 font-semibold whitespace-nowrap">Разгрузка</td>
                                <td className="p-3">—</td>
                                <td className="p-3">—</td>
                                <td className="p-3">{unloading.tariff_name || unloading.tag || "—"}</td>
                                <td className="p-3 text-slate-300 whitespace-pre-line">{unloading.tariff_label || "—"}</td>
                                <td className="p-3 text-slate-100">—</td>
                                <td className="p-3">—</td>
                                <td className="p-3 text-slate-300 whitespace-pre-line">—</td>
                                <td className="p-3 font-semibold text-indigo-200">{unloadingCost.toLocaleString()} ₽</td>
                              </tr>
                            ) : null}
                            <tr className="border-t border-slate-700 bg-slate-900/40">
                            <td className="p-3 font-bold" colSpan={8}>Итого по варианту</td>
                              <td className="p-3 font-bold text-indigo-200">{(sumDelivery + unloadingCost).toLocaleString()} ₽</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">
                    Подробности по рейсам/производствам доступны только логисту и выше. Сейчас показаны только итоговые суммы.
                  </div>
                )}
              </div>
            );
          })()}
        </MotionDiv>
      ) : null}

      {/* Floating actions (logist+, after quote) */}
      {canLogist && result?.variants?.length ? (
        <div className="fixed bottom-6 right-6 z-50">
          {actionsOpen ? (
            <div className="mb-3 w-72 rounded-2xl border border-slate-200 bg-white shadow-xl p-3">
              <div className="text-sm font-semibold text-slate-800 mb-2">Действия</div>
              <button
                disabled={actionBusy}
                onClick={handleConfirmScenario}
                className="w-full mb-2 px-4 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500 disabled:opacity-60"
              >
                Подтвердить сценарий (в БД)
              </button>
              <button
                disabled={actionBusy}
                onClick={handleRejectAndOpenManual}
                className="w-full px-4 py-3 rounded-xl bg-amber-600 text-white font-semibold hover:bg-amber-500 disabled:opacity-60"
              >
                Отклонить и заполнить вручную
              </button>
              <button
                type="button"
                onClick={() => setActionsOpen(false)}
                className="w-full mt-2 px-4 py-2 rounded-xl bg-white border border-slate-200 text-slate-700 font-semibold hover:border-indigo-200"
              >
                Закрыть
              </button>
            </div>
          ) : null}

          <button
            type="button"
            onClick={() => setActionsOpen((v) => !v)}
            className="px-5 py-4 rounded-full bg-indigo-600 text-white font-bold shadow-lg shadow-indigo-200 hover:bg-indigo-500"
            title="Действия"
          >
            Действия
          </button>
        </div>
      ) : null}

      {/* Manual modal */}
      {manualOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-3xl rounded-2xl bg-white border border-slate-200 shadow-2xl p-5">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-lg font-bold">Ручное заполнение (логист)</div>
                <div className="text-xs text-slate-500">
                  Заказ #{manualOrderId || "—"} • выберите транспорт и подтвердите
                </div>
              </div>
              <button
                type="button"
                onClick={() => setManualOpen(false)}
                className="px-3 py-2 rounded-lg bg-white border border-slate-200 hover:border-indigo-200"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="text-sm font-semibold text-slate-800 mb-2">Позиции и производства</div>
                {Array.isArray(manualItemsSnapshot) && manualItemsSnapshot.length ? (
                  <div className="space-y-3">
                    {manualItemsSnapshot.map((it, idx) => {
                      const options = manualFactoryOptionsByIndex[idx] || [];
                      const label = `${it?.category || "—"} / ${it?.subtype || "—"} × ${it?.quantity ?? "—"}`;
                      const selectedFactory = manualFactoryByItem?.[idx] || "";
                      const selectedRow = options.find((r) => normStr(r?.name || r?.["название"]) === selectedFactory);

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
                  <div className="text-sm text-slate-600">Не найден снимок позиций заказа.</div>
                )}
              </div>

              <div>
                <div className="flex items-center justify-between gap-3 mb-2">
                  <label className="block text-sm font-semibold text-slate-700">Машины доставки</label>
                  <button
                    type="button"
                    onClick={() => setManualDeliveryMachines((prev) => [...(prev || [""]), ""])}
                    className="px-3 py-2 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-100 font-semibold hover:bg-indigo-100"
                  >
                    ➕ Добавить машину
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
                          onClick={() =>
                            setManualDeliveryMachines((prev) => (prev || []).filter((_, i) => i !== idx))
                          }
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
                  Список берётся из тарифов (`/api/tariffs`) и фильтруется по выбранному “транспорту доставки”.
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between gap-3 mb-2">
                  <label className="block text-sm font-semibold text-slate-700">Машины разгрузки</label>
                  <button
                    type="button"
                    onClick={() => setManualUnloadingMachines((prev) => [...(prev || [""]), ""])}
                    className="px-3 py-2 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-100 font-semibold hover:bg-indigo-100 disabled:opacity-60"
                    disabled={manualUnloadingDisabled}
                  >
                    ➕ Добавить машину
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
                            if (v === "none") return ["none"];
                            next[idx] = v;
                            return next.filter((x) => normStr(x).toLowerCase() !== "none");
                          });
                        }}
                        className="flex-1 px-3 py-3 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm"
                        disabled={manualUnloadingDisabled && normStr(val).toLowerCase() !== "none"}
                      >
                        <option value="">Выберите машину разгрузки…</option>
                        <option value="none">Нет разгрузки (на объекте есть техника)</option>
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
                          onClick={() =>
                            setManualUnloadingMachines((prev) => (prev || []).filter((_, i) => i !== idx))
                          }
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
                  {manualUnloadingDisabled ? " Разгрузка отключена (на объекте есть своя техника)." : ""}
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
            </div>

            <div className="mt-4 flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setManualOpen(false)}
                className="px-4 py-3 rounded-xl bg-white border border-slate-200 text-slate-700 font-semibold hover:border-indigo-200"
              >
                Отмена
              </button>
              <button
                disabled={actionBusy}
                type="button"
                onClick={handleManualConfirm}
                className="px-4 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500 disabled:opacity-60"
              >
                Подтвердить (в БД)
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Logistics warning modal */}
      {logisticsModalOpen && result?.warningText ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-2xl rounded-2xl bg-white border border-slate-200 shadow-2xl p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Проверка логистом</div>
                <div className="text-2xl font-extrabold text-slate-900 mt-1">⚠️ {result.warningText}</div>
              </div>
              <button
                type="button"
                onClick={() => setLogisticsModalOpen(false)}
                className="px-3 py-2 rounded-lg bg-white border border-slate-200 hover:border-indigo-200"
                title="Закрыть"
              >
                ✕
              </button>
            </div>

            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
              <div className="text-sm font-semibold text-amber-900 mb-2">Причины</div>
              {Array.isArray(result.warningReasons) && result.warningReasons.length ? (
                <ul className="text-sm text-amber-900 list-disc pl-5 space-y-1">
                  {result.warningReasons.map((r, idx) => (
                    <li key={idx}>{r}</li>
                  ))}
                </ul>
              ) : (
                <div className="text-sm text-amber-900">
                  Есть признаки, что автоматический расчёт может требовать ручной проверки.
                </div>
              )}
            </div>

            <div className="mt-4 flex flex-wrap gap-2 justify-end">
              <button
                type="button"
                onClick={() => setLogisticsModalOpen(false)}
                className="px-4 py-2 rounded-xl bg-white border border-slate-200 text-slate-800 font-semibold hover:border-indigo-200"
              >
                Понятно
              </button>
              {canLogist ? (
                <button
                  type="button"
                  disabled={actionBusy}
                  onClick={async () => {
                    setLogisticsModalOpen(false);
                    await handleRejectAndOpenManual();
                  }}
                  className="px-4 py-2 rounded-xl bg-amber-600 text-white font-semibold hover:bg-amber-500 disabled:opacity-60"
                >
                  Отклонить и заполнить вручную
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </MotionDiv>
  );
}
