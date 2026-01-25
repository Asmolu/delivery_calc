import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { adminDeleteTransportCard, adminListTariffAudit, adminListTariffs, adminUpsertTransportCard, getCurrentUser } from "../api";

const TRANSPORT_TAGS = [
  { value: "container_carrier", label: "Контейнеровоз" },
  { value: "long_haul", label: "Длинномер (шаланда)" },
  { value: "flatbed", label: "Бортовой транспорт" },
  { value: "manipulator", label: "Манипулятор" },
  { value: "crane", label: "Кран" },
];

const GEO_ZONES = [
  { value: "", label: "Нет" },
  { value: "MKAD", label: "MKAD" },
  { value: "MOSCOW_MO", label: "MOSCOW_MO" },
];

const emptyRange = { min_distance: 0, max_distance: 0, base: 0 };
const emptyBlock = {
  weight_condition: "any",
  weight_threshold: "",
  per_km: 0,
  delivery_ranges: [{ ...emptyRange }],
  unloading_price: "",
};

const emptyDraft = {
  name: "",
  capacity: 0,
  tag: "manipulator",
  is_active: true,

  load_zone: "",
  unload_zone: "",

  unload_tags: [],

  enable_delivery: true,
  enable_unloading: false,

  description: "",
  notes: "",

  // container_carrier: связь с базовой шаландой
  base_transport_key: "",

  blocks: [{ ...emptyBlock }],
};

const ORG_RANK = { viewer: 10, manager: 20, logist: 30, admin: 40, owner: 50 };
function orgRank(role) {
  return ORG_RANK[String(role || "").toLowerCase()] || 0;
}

function toNum(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function weightKey(cond, thr) {
  const c = String(cond || "any");
  const t = thr == null ? "" : String(thr);
  return `${c}::${t}`;
}

function MultiSelectDropdown({ options, value, onChange, placeholder = "Нет", disabled = false }) {
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
    if (disabled) return;
    if (selectedSet.has(v)) return;
    onChange([...(selected || []), v]);
    setOpen(false);
  };

  const removeValue = (v) => {
    if (disabled) return;
    onChange((selected || []).filter((x) => x !== v));
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((s) => !s)}
        className={`w-full px-3 py-2 rounded-lg bg-white border border-slate-200 text-slate-800 shadow-sm text-left flex items-center justify-between gap-2 ${
          disabled ? "opacity-60 cursor-not-allowed" : ""
        }`}
      >
        <span className="text-sm text-slate-700">
          {open ? "Выберите…" : available.length ? "Добавить…" : "Нет доступных"}
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
                  disabled={disabled}
                  onClick={() => removeValue(v)}
                  className="text-slate-500 hover:text-slate-800 disabled:cursor-not-allowed"
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
        <div className="absolute z-20 mt-2 w-full rounded-xl border border-slate-200 bg-white shadow-lg overflow-hidden">
          <div className="max-h-56 overflow-auto">
            {available.length ? (
              available.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  disabled={disabled}
                  onClick={() => addValue(o.value)}
                  className="w-full text-left px-3 py-2 text-sm text-slate-800 hover:bg-slate-900/30 disabled:cursor-not-allowed"
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

export default function AdminTariffs() {
  const MotionDiv = motion.div;
  const navigate = useNavigate();

  const [user, setUser] = useState(null);

  const [tariffsRaw, setTariffsRaw] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const [selectedKey, setSelectedKey] = useState("new");
  const [draft, setDraft] = useState(emptyDraft);
  const isContainer = String(draft?.tag || "").toLowerCase() === "container_carrier";

  const [auditOpen, setAuditOpen] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditRows, setAuditRows] = useState([]);

  const canEdit = orgRank(user?.orgRole) >= ORG_RANK.logist;
  const canViewAudit = orgRank(user?.orgRole) >= ORG_RANK.admin;
  const canDelete = orgRank(user?.orgRole) >= ORG_RANK.admin;

  const fmtTs = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  };

  const reload = async () => {
    if (user && !canEdit) {
      setMessage("Доступ: только логист и выше.");
      return;
    }
    setLoading(true);
    try {
      const t = await adminListTariffs();
      setTariffsRaw(Array.isArray(t) ? t : []);
    } catch (e) {
      const hint =
        e?.status === 401
          ? " (нужно войти через /login)"
          : e?.status === 403
            ? " (доступ только логист и выше)"
            : "";
      setMessage((e?.message || "Ошибка загрузки тарифов") + hint);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    getCurrentUser().then(setUser).catch(() => navigate("/login", { replace: true }));
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Переход из /admin по кнопке "Открыть в редакторе"
  useEffect(() => {
    const key = sessionStorage.getItem("selected_transport_key");
    if (key) {
      sessionStorage.removeItem("selected_transport_key");
      setSelectedKey(key);
    }
  }, []);

  const loadAudit = async () => {
    if (user && !canViewAudit) {
      setMessage("Историю изменений могут смотреть только админ и выше.");
      return;
    }
    setAuditLoading(true);
    try {
      const rows = await adminListTariffAudit(200);
      setAuditRows(Array.isArray(rows) ? rows : []);
    } catch (e) {
      const hint = e?.status === 403 ? " (доступ только админ и выше)" : "";
      setMessage((e?.message || "Ошибка загрузки истории изменений") + hint);
    } finally {
      setAuditLoading(false);
    }
  };

  const transports = useMemo(() => {
    const normalized = (tariffsRaw || []).map((v) => ({
      id: v.id,
      name: v.name || v.название || "Без названия",
      capacity: Number(v.capacity ?? v["грузоподъёмность"] ?? 0),
      tag: v.tag || v["тэг"] || v["тег"] || "",
      base_transport_name: v.base_transport_name ?? null,
      base_transport_tag: v.base_transport_tag ?? null,
      weight_condition: v.weight_condition || "any",
      weight_threshold: v.weight_threshold ?? null,
      min_distance: Number(v.min_distance ?? 0),
      max_distance: Number(v.max_distance ?? 0),
      base: Number(v.base ?? 0),
      per_km: Number(v.per_km ?? 0),
      load_zone: v.load_zone ?? "",
      unload_zone: v.unload_zone ?? "",
      service_type: v.service_type || "delivery",
      unload_tags: Array.isArray(v.unload_tags) ? v.unload_tags : null,
      unload_capability: v.unload_capability || "none",
      is_active: v.is_active !== false,
      description: v.description || v["описание"] || "",
      notes: v.notes || v["заметки"] || "",
    }));

    const byKey = new Map();
    for (const r of normalized) {
      const k = `${r.name}||${r.tag}`;
      const arr = byKey.get(k) || [];
      arr.push(r);
      byKey.set(k, arr);
    }

    const out = [];
    for (const [key, rows] of byKey.entries()) {
      const header = rows[0] || {};
      // blocks by weight
      const blocksMap = new Map();
      for (const r of rows) {
        const wk = weightKey(r.weight_condition, r.weight_threshold);
        const b = blocksMap.get(wk) || {
          weight_condition: r.weight_condition || "any",
          weight_threshold: r.weight_threshold ?? null,
          per_km: 0,
          delivery_ranges: [],
          unloading_price: null,
        };
        if (r.service_type === "unloading") {
          b.unloading_price = r.base;
        } else {
          b.delivery_ranges.push({ min_distance: r.min_distance, max_distance: r.max_distance, base: r.base });
          b.per_km = Math.max(b.per_km || 0, r.per_km || 0);
        }
        blocksMap.set(wk, b);
      }

      const blocks = Array.from(blocksMap.values()).map((b) => ({
        weight_condition: b.weight_condition,
        weight_threshold: b.weight_threshold,
        per_km: b.per_km || 0,
        delivery_ranges: (b.delivery_ranges || []).sort((a, c) => (a.min_distance || 0) - (c.min_distance || 0)),
        unloading_price: b.unloading_price,
      }));

      const unloadTags = header.unload_tags || (header.unload_capability && header.unload_capability !== "none" ? [header.unload_capability] : []);

      const baseKey =
        header.base_transport_name && header.base_transport_tag
          ? `${header.base_transport_name}||${header.base_transport_tag}`
          : "";

      out.push({
        key,
        name: header.name,
        capacity: header.capacity,
        tag: header.tag,
        is_active: header.is_active !== false,
        load_zone: header.load_zone ?? "",
        unload_zone: header.unload_zone ?? "",
        unload_tags: unloadTags,
        description: header.description || "",
        notes: header.notes || "",
        base_transport_key: baseKey,
        blocks,
        enable_delivery: blocks.some((b) => (b.delivery_ranges || []).length > 0),
        enable_unloading: blocks.some((b) => (b.unloading_price || 0) > 0),
      });
    }

    out.sort((a, b) => String(a.name).localeCompare(String(b.name)));
    return out;
  }, [tariffsRaw]);

  const selectedTransport = useMemo(() => {
    if (selectedKey === "new") return null;
    return transports.find((t) => t.key === selectedKey) || null;
  }, [selectedKey, transports]);

  useEffect(() => {
    if (selectedKey === "new") {
      setDraft(emptyDraft);
      return;
    }
    if (!selectedTransport) return;

    const blocks = (selectedTransport.blocks || []).slice(0, 2);
    const mapped = blocks.length
      ? blocks.map((b) => ({
          weight_condition: b.weight_condition || "any",
          weight_threshold: b.weight_threshold ?? "",
          per_km: b.per_km || 0,
          delivery_ranges: (b.delivery_ranges?.length ? b.delivery_ranges : [{ ...emptyRange }]).map((r) => ({
            min_distance: r.min_distance ?? 0,
            max_distance: r.max_distance ?? 0,
            base: r.base ?? 0,
          })),
          unloading_price: b.unloading_price ?? "",
        }))
      : [{ ...emptyBlock }];

    setDraft({
      name: selectedTransport.name || "",
      capacity: selectedTransport.capacity || 0,
      tag: selectedTransport.tag || "",
      is_active: selectedTransport.is_active !== false,
      load_zone: selectedTransport.load_zone || "",
      unload_zone: selectedTransport.unload_zone || "",
      unload_tags: Array.isArray(selectedTransport.unload_tags) ? selectedTransport.unload_tags : [],
      enable_delivery: !!selectedTransport.enable_delivery,
      enable_unloading: !!selectedTransport.enable_unloading,
      description: selectedTransport.description || "",
      notes: selectedTransport.notes || "",
      base_transport_key: selectedTransport.base_transport_key || "",
      blocks: mapped,
    });
  }, [selectedKey, selectedTransport]);

  const baseShalandaOptions = useMemo(() => {
    // базу выбираем из доставочных long_haul карточек
    return (transports || [])
      .filter((t) => String(t.tag || "").toLowerCase() === "long_haul")
      .map((t) => ({ key: `${t.name}||${t.tag}`, label: `${t.name} (${t.tag})` }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [transports]);

  const addDeliveryRow = (blockIdx) => {
    setDraft((s) => {
      const blocks = (s.blocks || []).slice();
      const b = { ...(blocks[blockIdx] || { ...emptyBlock }) };
      b.delivery_ranges = (b.delivery_ranges || []).concat([{ ...emptyRange }]);
      blocks[blockIdx] = b;
      return { ...s, blocks };
    });
  };

  const removeDeliveryRow = (blockIdx, rowIdx) => {
    setDraft((s) => {
      const blocks = (s.blocks || []).slice();
      const b = { ...(blocks[blockIdx] || { ...emptyBlock }) };
      const ranges = (b.delivery_ranges || []).slice();
      ranges.splice(rowIdx, 1);
      b.delivery_ranges = ranges.length ? ranges : [{ ...emptyRange }];
      blocks[blockIdx] = b;
      return { ...s, blocks };
    });
  };

  const addSecondWeightBlock = () => {
    setDraft((s) => {
      const blocks = (s.blocks || []).slice();
      if (blocks.length >= 2) return s;
      blocks.push({ ...emptyBlock });
      return { ...s, blocks };
    });
  };

  const removeSecondWeightBlock = () => {
    setDraft((s) => {
      const blocks = (s.blocks || []).slice(0, 1);
      return { ...s, blocks };
    });
  };

  const saveCard = async () => {
    setLoading(true);
    setMessage("");
    try {
      const name = String(draft.name || "").trim();
      const tag = String(draft.tag || "").trim().toLowerCase();
      const isContainer = tag === "container_carrier";
      if (!name) throw new Error("Укажите название");
      if (!tag) throw new Error("Укажите тег");

      const unload = Array.isArray(draft.unload_tags) ? draft.unload_tags : [];
      const baseKey = String(draft.base_transport_key || "").trim();
      const [baseNameRaw, baseTagRaw] = baseKey ? baseKey.split("||") : ["", ""];
      const baseName = String(baseNameRaw || "").trim();
      const baseTag = String(baseTagRaw || "").trim().toLowerCase();

      const blocks = isContainer
        ? []
        : (draft.blocks || []).slice(0, 2).map((b) => {
            const cond = b.weight_condition || "any";
            const thr = cond === "any" ? null : toNum(b.weight_threshold || 0, 0);
            if (cond !== "any" && !thr) throw new Error("Весовой порог обязателен для le/gt");

            const deliveryRanges = (b.delivery_ranges || []).map((r) => ({
              min_distance: toNum(r.min_distance || 0, 0),
              max_distance: toNum(r.max_distance || 0, 0),
              base: toNum(r.base || 0, 0),
            }));

            if (draft.enable_delivery) {
              const ok = deliveryRanges.some((r) => (r.base || 0) > 0);
              if (!ok) throw new Error("Добавьте хотя бы один диапазон доставки с ценой");
            }

            return {
              weight_condition: cond,
              weight_threshold: thr,
              per_km: toNum(b.per_km || 0, 0),
              delivery_ranges: deliveryRanges.filter((r) => (r.base || 0) > 0),
              unloading_price: draft.enable_unloading ? toNum(b.unloading_price || 0, 0) : null,
            };
          });

      const payload = {
        name,
        capacity: toNum(draft.capacity || 0, 0),
        tag,
        base_transport_name: isContainer ? baseName : null,
        base_transport_tag: isContainer ? (baseTag || "long_haul") : null,
        load_zone: draft.load_zone || null,
        unload_zone: draft.unload_zone || null,
        unload_tags: isContainer ? ["crane"] : unload,
        is_active: !!draft.is_active,
        description: draft.description || null,
        notes: draft.notes || null,
        enable_delivery: isContainer ? true : !!draft.enable_delivery,
        enable_unloading: isContainer ? false : !!draft.enable_unloading,
        weight_blocks: blocks,
      };

      await adminUpsertTransportCard(payload);
      await reload();
      setSelectedKey(`${name}||${tag}`);
      setMessage("✅ Сохранено");
    } catch (e) {
      setMessage(e?.message || "Ошибка сохранения");
    } finally {
      setLoading(false);
    }
  };

  const deleteCard = async () => {
    if (selectedKey === "new") return;
    if (!selectedTransport) return;
    if (user && !canDelete) {
      setMessage("Удалять транспорт могут только админ и выше.");
      return;
    }
    if (!window.confirm(`Удалить транспорт "${selectedTransport.name}" (${selectedTransport.tag}) целиком?`)) return;
    const password = window.prompt("Подтвердите пароль администратора для удаления транспорта:");
    if (!password) return;
    setLoading(true);
    setMessage("");
    try {
      await adminDeleteTransportCard(selectedTransport.name, selectedTransport.tag, password);
      setSelectedKey("new");
      await reload();
    } catch (e) {
      setMessage(e?.message || "Ошибка удаления");
    } finally {
      setLoading(false);
    }
  };

  return (
    <MotionDiv className="space-y-6" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <div className="card-glass p-6 flex items-center justify-between">
        <div>
          <p className="pill mb-2">admin</p>
          <h1 className="text-2xl font-bold">➕ Добавление транспорта</h1>
          <p className="text-slate-600 text-sm">Создание и редактирование транспорта и тарифных сеток.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={reload} disabled={loading} className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-500 disabled:opacity-60">
            {loading ? "Обновляем..." : "Обновить"}
          </button>
          <button onClick={() => navigate("/admin")} className="px-4 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200">
            ← Админка
          </button>
        </div>
      </div>

      {message ? <div className="card-glass p-4 text-sm border border-slate-200 bg-white text-slate-700">{message}</div> : null}

      <div className="card-glass p-6 border border-slate-200 bg-white">
        <div className="flex items-center justify-between mb-3 gap-3">
          <h2 className="text-lg font-bold">Редактор транспорта</h2>
          <div className="flex items-center gap-2">
            <select
              value={selectedKey}
              onChange={(e) => setSelectedKey(e.target.value)}
              className="px-3 py-2 rounded-lg border border-slate-200 bg-white"
            >
              <option value="new">+ Новый транспорт</option>
              {transports.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.name} ({t.tag})
                </option>
              ))}
            </select>
            {selectedKey !== "new" ? (
              <button
                type="button"
                onClick={deleteCard}
                disabled={loading}
                className="px-3 py-2 rounded-lg bg-rose-600 text-white font-semibold hover:bg-rose-500 disabled:opacity-60"
              >
                Удалить транспорт
              </button>
            ) : null}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="text-sm">
            <div className="text-slate-600 mb-1">Название</div>
            <input value={draft.name} onChange={(e) => setDraft((s) => ({ ...s, name: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-slate-200" />
          </label>
          <label className="text-sm">
            <div className="text-slate-600 mb-1">Грузоподъёмность (т)</div>
            <input type="number" step="0.1" value={draft.capacity} onChange={(e) => setDraft((s) => ({ ...s, capacity: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-slate-200" />
          </label>
          <label className="text-sm">
            <div className="text-slate-600 mb-1">Тег</div>
            <select
              value={draft.tag}
              onChange={(e) => {
                const nextTag = e.target.value;
                setDraft((s) => {
                  const tagNorm = String(nextTag || "").toLowerCase();
                  if (tagNorm === "container_carrier") {
                    return {
                      ...s,
                      tag: nextTag,
                      enable_delivery: true,
                      enable_unloading: false,
                      unload_tags: ["crane"],
                      // тарифные блоки не редактируем для контейнеровоза (берём из шаланды)
                      blocks: [{ ...emptyBlock }],
                    };
                  }
                  return { ...s, tag: nextTag };
                });
              }}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white"
            >
              {TRANSPORT_TAGS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>

          {isContainer ? (
            <label className="text-sm md:col-span-3">
              <div className="text-slate-600 mb-1">Базовая шаланда (от неё берётся цена)</div>
              <select
                value={draft.base_transport_key || ""}
                onChange={(e) => setDraft((s) => ({ ...s, base_transport_key: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white"
              >
                <option value="">Выберите шаланду…</option>
                {baseShalandaOptions.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
              <div className="text-xs text-slate-500 mt-1">
                Контейнеровоз использует тарифную сетку шаланды, но считает цену по формуле.
              </div>
            </label>
          ) : null}

          <label className="text-sm md:col-span-1">
            <div className="text-slate-600 mb-1">Тип транспорта</div>
            {isContainer ? (
              <div className="text-sm text-slate-700 pt-2">
                <div className="font-semibold">Доставка</div>
                <div className="text-xs text-slate-500">Для контейнеровоза тарифная сетка берётся из шаланды.</div>
              </div>
            ) : (
              <div className="flex flex-col gap-2 pt-1">
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={!!draft.enable_delivery}
                    onChange={(e) => setDraft((s) => ({ ...s, enable_delivery: e.target.checked }))}
                    className="w-4 h-4 accent-indigo-600"
                  />
                  Доставка
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={!!draft.enable_unloading}
                    onChange={(e) => setDraft((s) => ({ ...s, enable_unloading: e.target.checked }))}
                    className="w-4 h-4 accent-indigo-600"
                  />
                  Разгрузка
                </label>
              </div>
            )}
          </label>

          <label className="text-sm md:col-span-1">
            <div className="text-slate-600 mb-1">Теги разгрузки (можно несколько)</div>
            <MultiSelectDropdown
              options={[
                { value: "self", label: "Сам" },
                { value: "crane", label: "Кран" },
                { value: "manipulator", label: "Манипулятор" },
              ]}
              value={draft.unload_tags}
              onChange={(next) => setDraft((s) => ({ ...s, unload_tags: next }))}
              placeholder="Нет"
              disabled={isContainer}
            />
            <div className="text-xs text-slate-500 mt-1">
              {isContainer ? "Для контейнеровоза фиксировано: только кран." : "Добавляйте теги по одному, выбранные отображаются чипами."}
            </div>
          </label>

          <label className="text-sm md:col-span-1">
            <div className="text-slate-600 mb-1">Активность</div>
            <label className="flex items-center gap-2 text-sm text-slate-700 mt-2">
              <input type="checkbox" checked={!!draft.is_active} onChange={(e) => setDraft((s) => ({ ...s, is_active: e.target.checked }))} className="w-4 h-4 accent-indigo-600" />
              Активен
            </label>
          </label>

          <label className="text-sm">
          <div className="text-slate-600 mb-1">Ограничение загрузки (зона)</div>
            <select
              value={draft.load_zone || ""}
              onChange={(e) => setDraft((s) => ({ ...s, load_zone: e.target.value }))}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white"
            >
              {GEO_ZONES.map((z) => (
                <option key={z.value || "none"} value={z.value}>
                  {z.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm md:col-span-2">
          <div className="text-slate-600 mb-1">Ограничение выгрузки (зона)</div>
            <select
              value={draft.unload_zone || ""}
              onChange={(e) => setDraft((s) => ({ ...s, unload_zone: e.target.value }))}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white"
            >
              {GEO_ZONES.map((z) => (
                <option key={z.value || "none"} value={z.value}>
                  {z.label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm md:col-span-3">
            <div className="text-slate-600 mb-1">Описание</div>
            <textarea value={draft.description} onChange={(e) => setDraft((s) => ({ ...s, description: e.target.value }))} rows={2} className="w-full px-3 py-2 rounded-lg border border-slate-200" />
          </label>
          <label className="text-sm md:col-span-3">
            <div className="text-slate-600 mb-1">Заметки</div>
            <textarea value={draft.notes} onChange={(e) => setDraft((s) => ({ ...s, notes: e.target.value }))} rows={2} className="w-full px-3 py-2 rounded-lg border border-slate-200" />
          </label>
        </div>

        <div className="mt-5 space-y-5">
          {!isContainer ? draft.blocks.slice(0, 2).map((b, bi) => (
            <div key={bi} className="border border-slate-200 rounded-xl p-4 bg-white">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="text-md font-bold">Весовое условие {bi + 1}</div>
                {bi === 1 ? (
                  <button type="button" onClick={removeSecondWeightBlock} className="px-3 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200">
                    Удалить весовое условие 2
                  </button>
                ) : null}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <label className="text-sm">
                  <div className="text-slate-600 mb-1">Весовое условие</div>
                  <select
                    value={b.weight_condition}
                    onChange={(e) =>
                      setDraft((s) => {
                        const blocks = s.blocks.slice();
                        blocks[bi] = { ...blocks[bi], weight_condition: e.target.value };
                        return { ...s, blocks };
                      })
                    }
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white"
                  >
                    <option value="any">any</option>
                    <option value="le">≤ threshold</option>
                    <option value="gt">{">"} threshold</option>
                  </select>
                </label>
                <label className="text-sm">
                  <div className="text-slate-600 mb-1">Весовой порог</div>
                  <input
                    type="number"
                    step="0.1"
                    value={b.weight_threshold}
                    disabled={b.weight_condition === "any"}
                    onChange={(e) =>
                      setDraft((s) => {
                        const blocks = s.blocks.slice();
                        blocks[bi] = { ...blocks[bi], weight_threshold: e.target.value };
                        return { ...s, blocks };
                      })
                    }
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 disabled:bg-slate-900/40"
                  />
                </label>
                <label className="text-sm">
                  <div className="text-slate-600 mb-1">После max (₽/км) — общий</div>
                  <input
                    type="number"
                    step="1"
                    value={b.per_km}
                    onChange={(e) =>
                      setDraft((s) => {
                        const blocks = s.blocks.slice();
                        blocks[bi] = { ...blocks[bi], per_km: e.target.value };
                        return { ...s, blocks };
                      })
                    }
                    className="w-full px-3 py-2 rounded-lg border border-slate-200"
                  />
                </label>
              </div>

              {draft.enable_delivery ? (
                <div className="mt-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-sm font-semibold text-slate-700">Диапазоны доставки</div>
                    <button type="button" onClick={() => addDeliveryRow(bi)} className="px-3 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200">
                      + Добавить строку
                    </button>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left text-slate-700 border border-slate-200 rounded-lg">
                      <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                        <tr>
                          <th className="px-3 py-2">Мин (км)</th>
                          <th className="px-3 py-2">Макс (км)</th>
                          <th className="px-3 py-2">Цена (₽)</th>
                          <th className="px-3 py-2">Действия</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(b.delivery_ranges || []).map((r, ri) => (
                          <tr key={ri} className="border-t border-slate-100 hover:bg-slate-900/30">
                            <td className="px-3 py-2">
                              <input
                                type="number"
                                step="0.1"
                                value={r.min_distance}
                                onChange={(e) =>
                                  setDraft((s) => {
                                    const blocks = s.blocks.slice();
                                    const bb = { ...blocks[bi] };
                                    const ranges = (bb.delivery_ranges || []).slice();
                                    ranges[ri] = { ...ranges[ri], min_distance: e.target.value };
                                    bb.delivery_ranges = ranges;
                                    blocks[bi] = bb;
                                    return { ...s, blocks };
                                  })
                                }
                                className="w-28 px-2 py-1 rounded border border-slate-200 bg-white"
                              />
                            </td>
                            <td className="px-3 py-2">
                              <input
                                type="number"
                                step="0.1"
                                value={r.max_distance}
                                onChange={(e) =>
                                  setDraft((s) => {
                                    const blocks = s.blocks.slice();
                                    const bb = { ...blocks[bi] };
                                    const ranges = (bb.delivery_ranges || []).slice();
                                    ranges[ri] = { ...ranges[ri], max_distance: e.target.value };
                                    bb.delivery_ranges = ranges;
                                    blocks[bi] = bb;
                                    return { ...s, blocks };
                                  })
                                }
                                className="w-28 px-2 py-1 rounded border border-slate-200 bg-white"
                              />
                            </td>
                            <td className="px-3 py-2">
                              <input
                                type="number"
                                step="1"
                                value={r.base}
                                onChange={(e) =>
                                  setDraft((s) => {
                                    const blocks = s.blocks.slice();
                                    const bb = { ...blocks[bi] };
                                    const ranges = (bb.delivery_ranges || []).slice();
                                    ranges[ri] = { ...ranges[ri], base: e.target.value };
                                    bb.delivery_ranges = ranges;
                                    blocks[bi] = bb;
                                    return { ...s, blocks };
                                  })
                                }
                                className="w-32 px-2 py-1 rounded border border-slate-200 bg-white"
                              />
                            </td>
                            <td className="px-3 py-2">
                              <button type="button" onClick={() => removeDeliveryRow(bi, ri)} className="px-3 py-1.5 rounded-lg bg-rose-600 text-white hover:bg-rose-500">
                                Удалить
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}

              {draft.enable_unloading ? (
                <div className="mt-4">
                  <div className="text-sm font-semibold text-slate-700 mb-2">Фикс цена разгрузки</div>
                  <input
                    type="number"
                    step="1"
                    value={b.unloading_price}
                    onChange={(e) =>
                      setDraft((s) => {
                        const blocks = s.blocks.slice();
                        blocks[bi] = { ...blocks[bi], unloading_price: e.target.value };
                        return { ...s, blocks };
                      })
                    }
                    className="w-48 px-3 py-2 rounded-lg border border-slate-200"
                    placeholder="₽"
                  />
                </div>
              ) : null}
            </div>
          )) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
              <div className="font-semibold">Тарифная сетка скрыта</div>
              <div className="text-xs text-slate-600 mt-1">
                Для контейнеровоза стоимость и диапазоны берутся из привязанной шаланды. Здесь настраиваются только общие поля и связь с шаландой.
              </div>
            </div>
          )}

          {!isContainer && draft.blocks.length < 2 ? (
            <button type="button" onClick={addSecondWeightBlock} className="px-4 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200">
              + Добавить второе весовое условие
            </button>
          ) : null}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={saveCard} disabled={loading} className="px-5 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500 disabled:opacity-60">
              Сохранить транспорт
            </button>
          </div>
        </div>
      </div>

      {canViewAudit ? (
        <div className="card-glass p-6 border border-slate-200 bg-white">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">История изменений</h2>
              <p className="text-slate-600 text-sm">Кто и когда создавал/редактировал/удалял тарифы.</p>
            </div>
            <button
              type="button"
              onClick={async () => {
                const next = !auditOpen;
                setAuditOpen(next);
                if (next && auditRows.length === 0) {
                  await loadAudit();
                }
              }}
              className="px-4 py-2 rounded-lg bg-white border border-slate-200 font-semibold hover:border-indigo-200"
            >
              {auditOpen ? "Скрыть" : "Показать"}
            </button>
          </div>

          {auditOpen ? (
            <div className="mt-4">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs text-slate-500">{auditLoading ? "Загрузка..." : `Показано: ${auditRows.length}`}</div>
                <button
                  type="button"
                  onClick={loadAudit}
                  disabled={auditLoading}
                  className="px-3 py-2 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-500 disabled:opacity-60"
                >
                  Обновить историю
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left text-slate-700 border border-slate-200 rounded-lg">
                  <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                    <tr>
                      <th className="px-3 py-2">Когда</th>
                      <th className="px-3 py-2">Кто</th>
                      <th className="px-3 py-2">Действие</th>
                      <th className="px-3 py-2">Транспорт</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(auditRows || []).map((r) => (
                      <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-900/30">
                        <td className="px-3 py-2 whitespace-nowrap">{fmtTs(r.createdAt)}</td>
                        <td className="px-3 py-2">{r.user?.username || "—"}</td>
                        <td className="px-3 py-2">{r.action}</td>
                        <td className="px-3 py-2">{r.tariffName || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="card-glass p-6 border border-slate-200 bg-white">
          <h2 className="text-lg font-bold">История изменений</h2>
          <p className="text-slate-600 text-sm">Доступ: только админ и выше.</p>
        </div>
      )}
    </MotionDiv>
  );
}
