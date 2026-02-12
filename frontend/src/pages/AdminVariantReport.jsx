import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { adminGetVariantsSummary, getCurrentUser } from "../api";

function toInputDateTimeValue(d) {
  const dt = d instanceof Date ? d : new Date(d);
  if (Number.isNaN(dt.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  const yyyy = dt.getFullYear();
  const mm = pad(dt.getMonth() + 1);
  const dd = pad(dt.getDate());
  const hh = pad(dt.getHours());
  const mi = pad(dt.getMinutes());
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
}

function fmtPct(v) {
  return `${Number(v || 0).toFixed(2)}%`;
}

function KpiCard({ title, percent, count, total, wide = false }) {
  return (
    <div className={`card-glass p-4 border border-slate-200 bg-white ${wide ? "md:col-span-2" : ""}`}>
      <div className="text-sm text-slate-500">{title}</div>
      <div className="mt-1 text-2xl font-bold text-slate-900">{fmtPct(percent)}</div>
      <div className="text-sm text-slate-600 mt-1">
        {Number(count || 0).toLocaleString()} / {Number(total || 0).toLocaleString()}
      </div>
    </div>
  );
}

const ORG_RANK = { viewer: 10, manager: 20, logist: 30, admin: 40, owner: 50 };
const rankOf = (r) => ORG_RANK[String(r || "").toLowerCase()] || 0;

export default function AdminVariantReport() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [data, setData] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const [fromValue, setFromValue] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return toInputDateTimeValue(d);
  });
  const [toValue, setToValue] = useState(() => toInputDateTimeValue(new Date()));

  const load = async () => {
    try {
      setLoading(true);
      setErr("");
      const fromIso = fromValue ? new Date(fromValue).toISOString() : undefined;
      const toIso = toValue ? new Date(toValue).toISOString() : undefined;
      const resp = await adminGetVariantsSummary({ from: fromIso, to: toIso });
      setData(resp || null);
    } catch (e) {
      setErr(e?.message || "Ошибка загрузки отчёта");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    getCurrentUser()
      .then((u) => {
        if (!mounted) return;
        if (rankOf(u?.orgRole) < ORG_RANK.admin) {
          navigate("/admin", { replace: true });
          return;
        }
        load();
      })
      .catch(() => navigate("/login", { replace: true }));
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => {
      load();
    }, 15000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, fromValue, toValue]);

  const ordersTotal = Number(data?.totals?.orders || 0);
  const quotesTotal = Number(data?.totals?.quoteSessions || 0);

  const kpi = useMemo(() => {
    const p = data?.fromOrdersPercent || {};
    const c = data?.fromOrdersCount || {};
    return {
      autoAccepted: { title: "% Авторасчёт подтверждён", percent: p.autoAccepted, count: c.autoAccepted },
      manualAccepted: { title: "% Ручной пересчёт + принято", percent: p.manualRecalcAccepted, count: c.manualRecalcAccepted },
      fullyDeclined: { title: "% Авторасчёт отклонён", percent: p.fullyDeclined, count: c.fullyDeclined },
      manualDeclined: { title: "% Ручной пересчёт + не принято", percent: p.manualRecalcDeclined, count: c.manualRecalcDeclined },
      stuck: { title: "% Застряли на грани", percent: p.stuckNoDecision, count: c.stuckNoDecision },
    };
  }, [data]);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <h1 className="text-3xl font-extrabold text-slate-900">📊 Дашборд/отчёт</h1>
        <div className="flex gap-2">
          <button type="button" onClick={() => navigate("/admin")} className="px-4 py-2 rounded-lg border border-slate-300 bg-white text-slate-700">← В админку</button>
          <button type="button" onClick={load} disabled={loading} className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-500 disabled:opacity-60">Обновить отчёт</button>
        </div>
      </div>

      <div className="card-glass p-4 border border-slate-200 bg-white grid grid-cols-1 md:grid-cols-4 gap-3">
        <label className="text-sm text-slate-700">
          Период: с
          <input type="datetime-local" value={fromValue} onChange={(e) => setFromValue(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
        </label>
        <label className="text-sm text-slate-700">
          по
          <input type="datetime-local" value={toValue} onChange={(e) => setToValue(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
        </label>
        <label className="text-sm text-slate-700 flex items-end gap-2">
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          Автообновление каждые 15 сек
        </label>
        <div className="text-xs text-slate-500 flex items-end">Обновлено: {data?.updatedAt ? new Date(data.updatedAt).toLocaleString() : "—"}</div>
      </div>

      {err ? <div className="p-3 rounded-lg bg-red-50 text-red-700 border border-red-200">{err}</div> : null}

      <section className="space-y-3">
        <h2 className="text-xl font-bold text-slate-900">От сохранённых заказов (orders)</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <KpiCard title={kpi.autoAccepted.title} percent={kpi.autoAccepted.percent} count={kpi.autoAccepted.count} total={ordersTotal} />
          <KpiCard title={kpi.manualAccepted.title} percent={kpi.manualAccepted.percent} count={kpi.manualAccepted.count} total={ordersTotal} />
          <KpiCard title={kpi.fullyDeclined.title} percent={kpi.fullyDeclined.percent} count={kpi.fullyDeclined.count} total={ordersTotal} />
          <KpiCard title={kpi.manualDeclined.title} percent={kpi.manualDeclined.percent} count={kpi.manualDeclined.count} total={ordersTotal} />
          <KpiCard title={kpi.stuck.title} percent={kpi.stuck.percent} count={kpi.stuck.count} total={ordersTotal} wide />
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-bold text-slate-900">От всех расчётов (quote_sessions)</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <KpiCard
            title="% Сохранено в заказы"
            percent={data?.fromQuoteSessionsPercent?.savedToOrder}
            count={data?.fromQuoteSessionsCount?.savedToOrder}
            total={quotesTotal}
          />
          <KpiCard
            title="% Не сохранили в БД"
            percent={data?.fromQuoteSessionsPercent?.notSavedToOrder}
            count={data?.fromQuoteSessionsCount?.notSavedToOrder}
            total={quotesTotal}
          />
        </div>
      </section>
    </div>
  );
}