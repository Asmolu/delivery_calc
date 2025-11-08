const API_BASE = "";

export async function fetchFactories() {
  const res = await fetch(`${API_BASE}/api/factories`);
  if (!res.ok) throw new Error("Ошибка при загрузке factories");
  return await res.json();
}

export async function fetchTariffs() {
  const res = await fetch("http://localhost:8000/api/tariffs");
  if (!res.ok) throw new Error("Не удалось загрузить тарифы");
  return await res.json();
}



export async function reloadFactories() {
  const res = await fetch(`${API_BASE}/admin/reload`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Ошибка при обновлении");
  return data;
}

export async function fetchCategories() {
  const res = await fetch(`${API_BASE}/api/categories`);
  if (!res.ok) throw new Error("Ошибка при загрузке категорий");
  return await res.json();
}

export async function calculateQuote(payload) {
  const res = await fetch(`${API_BASE}/quote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Ошибка при расчёте");
  return data;
}

export async function getCategories() {
  try {
    const res = await fetch(`${API_BASE}/api/categories`);
    if (!res.ok) throw new Error("Ошибка при получении категорий");
    return await res.json();
  } catch (err) {
    console.error("Ошибка в getCategories:", err);
    return {};
  }
}

export async function getQuote(payload) {
  try {
    const res = await fetch(`${API_BASE}/quote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Ошибка при расчёте стоимости");
    return await res.json();
  } catch (err) {
    console.error("Ошибка в getQuote:", err);
    return null;
  }
}