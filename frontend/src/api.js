// === API base URL ===
const envBase = import.meta?.env?.VITE_API_BASE;
const isDev = window.location.port === "5173" || window.location.port === "4173";
export const API_BASE = envBase || (isDev ? "http://127.0.0.1:8000" : window.location.origin);
console.log("🌍 API_BASE =", API_BASE);

// === Универсальная обёртка для fetch ===
async function request(method, path, body) {
  const url = `${API_BASE}${path}`;
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) {
    options.body = JSON.stringify(body);
  }

  const resp = await fetch(url, options);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`Ошибка запроса ${method} ${path}: ${resp.status} ${resp.statusText} ${text}`);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

// === Основные функции API ===
export async function getCategories() {
  return request("GET", "/api/categories");
}

export async function getTariffs() {
  return request("GET", "/api/tariffs");
}

export async function reloadAll() {
  return request("POST", "/admin/reload", {});
}

export async function getQuote(payload) {
  const data = await request("POST", "/api/quote", payload);
  // если сервер возвращает объект с полем result, разворачиваем
  return data.result || data;
}


// === Совместимость со старым фронтом ===
// (чтобы Admin.jsx и прочие старые страницы не падали)
export const reloadFactories = reloadAll;
export const fetchFactories = async () => request("GET", "/api/factories");
export const fetchTariffs = getTariffs;
export const loadCategories = getCategories;
export const loadTariffs = getTariffs;
export const calculateQuote = getQuote;
export const reloadData = reloadAll;
