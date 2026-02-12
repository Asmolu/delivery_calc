// === API base URL ===
const envBase = import.meta?.env?.VITE_API_BASE;
const isDev = import.meta.env.DEV;
export const API_BASE = envBase || (isDev ? "http://127.0.0.1:8000" : window.location.origin);
console.log("🌍 API_BASE =", API_BASE);

// === Управление токеном ===
function getToken() {
  return localStorage.getItem("auth_token");
}

function setToken(token) {
  if (token) {
    localStorage.setItem("auth_token", token);
  } else {
    localStorage.removeItem("auth_token");
  }
}

// === Универсальная обёртка для fetch ===
async function request(method, path, body, requireAuth = false) {
  const url = `${API_BASE}${path}`;
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  
  // Добавляем токен, если требуется аутентификация
  if (requireAuth) {
    const token = getToken();
    if (token) {
      options.headers["Authorization"] = `Bearer ${token}`;
    }
  }
  
  if (body !== undefined) {
    options.body = JSON.stringify(body);
  }

  let resp;
  let rawText = "";
  try {
    resp = await fetch(url, options);
    rawText = await resp.text().catch(() => "");
  } catch (error) {
    if (path === "/auth/me") {
      setToken(null);
    }
    const err = new Error(error?.message || "Ошибка сети");
    err.status = 0;
    throw err;
  }

  let parsed = null;
  if (rawText) {
    try {
      parsed = JSON.parse(rawText);
    } catch {
      // оставляем parsed = null
    }
  }

  if (!resp.ok) {
    if (resp.status === 401 || path === "/auth/me") {
      setToken(null);
    }
    const detail = parsed?.detail || parsed?.message || rawText || resp.statusText;
    const error = new Error(detail || "Ошибка запроса");
    error.status = resp.status;
    throw error;
  }

  if (resp.status === 204 || rawText === "") return null;
  return parsed;
}

// === Основные функции API ===
export async function getCategories() {
  return request("GET", "/api/categories");
}

export async function getTariffs() {
  return request("GET", "/api/tariffs");
}

// === Аутентификация ===
export async function login(username, password) {
  const resp = await fetch(`${API_BASE}/auth/login/json`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({}));
    throw new Error(error.detail || "Ошибка входа");
  }
  
  const data = await resp.json();
  if (data.access_token) {
    setToken(data.access_token);
  }
  return data;
}

export async function logout() {
  setToken(null);
}

export async function getCurrentUser() {
  return request("GET", "/auth/me", undefined, true);
}

export function isAuthenticated() {
  return !!getToken();
}

export async function reloadAll() {
  return request("POST", "/admin/reload", {}, true);
}

// === Tariffs (admin) ===
export async function adminListTariffs() {
  return request("GET", "/admin/tariffs", undefined, true);
}

export async function adminCreateTariff(payload) {
  return request("POST", "/admin/tariffs", payload, true);
}

export async function adminUpdateTariff(tariffId, payload) {
  return request("PUT", `/admin/tariffs/${tariffId}`, payload, true);
}

export async function adminDeleteTariff(tariffId, password) {
  const qs = `password=${encodeURIComponent(String(password || ""))}`;
  return request("DELETE", `/admin/tariffs/${tariffId}?${qs}`, undefined, true);
}

export async function adminListTariffAudit(limit = 200) {
  return request("GET", `/admin/tariffs/audit?limit=${encodeURIComponent(String(limit))}`, undefined, true);
}

export async function adminUpsertTransportCard(payload) {
  return request("POST", "/admin/transports/upsert", payload, true);
}

export async function adminDeleteTransportCard(name, tag, password) {
  const qs =
    `name=${encodeURIComponent(String(name || ""))}` +
    `&tag=${encodeURIComponent(String(tag || ""))}` +
    `&password=${encodeURIComponent(String(password || ""))}`;
  return request("DELETE", `/admin/transports?${qs}`, undefined, true);
}

// === Users / Invites (admin, org-scoped via default org) ===
export async function adminGetOrg() {
  return request("GET", "/admin/org", undefined, true);
}

export async function adminListOrgMembers() {
  return request("GET", "/admin/org/members", undefined, true);
}

export async function adminListOrgInvites() {
  return request("GET", "/admin/org/invites", undefined, true);
}

export async function adminCreateOrgInvite(payload) {
  return request("POST", "/admin/org/invites", payload, true);
}

export async function adminRevokeOrgInvite(inviteId) {
  return request("POST", `/admin/org/invites/${encodeURIComponent(String(inviteId))}/revoke`, {}, true);
}

export async function adminUpdateOrgMember(memberId, payload) {
  return request("PUT", `/admin/org/members/${encodeURIComponent(String(memberId))}`, payload, true);
}

// === Invite accept (public) ===
export async function acceptInvite(token, username, password, firstName, lastName) {
  return request(
    "POST",
    "/auth/invite/accept",
    { token, username, password, first_name: firstName, last_name: lastName },
    false
  );
}

// === Factories / Products (admin) ===
export async function adminListFactoriesCatalog() {
  return request("GET", "/admin/factories", undefined, true);
}

export async function adminSetFactoryActive(factoryId, isActive) {
  return request("PUT", `/admin/factories/${encodeURIComponent(String(factoryId))}/active`, { is_active: !!isActive }, true);
}

export async function adminSetProductActive(productId, isActive) {
  return request("PUT", `/admin/products/${encodeURIComponent(String(productId))}/active`, { is_active: !!isActive }, true);
}

export async function getQuote(payload) {
  // /api/quote публичный, но детали выдаём только если есть авторизация.
  const data = await request("POST", "/api/quote", payload, isAuthenticated());
  // если сервер возвращает объект с полем result, разворачиваем
  return data.result || data;
}

// === Orders (admin) ===
export async function listOrders() {
  return request("GET", "/admin/orders", undefined, true);
}

export async function getOrder(orderId) {
  return request("GET", `/admin/orders/${orderId}`, undefined, true);
}

export async function confirmOrderFromQuote(snapshot) {
  return request("POST", "/admin/orders/confirm", snapshot, true);
}

export async function rejectOrderForManual(snapshot) {
  return request("POST", "/admin/orders/reject", snapshot, true);
}

export async function manualConfirmOrder(orderId, decision) {
  return request("POST", `/admin/orders/${orderId}/manual_confirm`, decision, true);
}

export async function recalcManualOrder(orderId) {
  return request("POST", `/admin/orders/${orderId}/manual_recalc`, {}, true);
}

export async function approveOrder(orderId, decision = {}) {
  return request("POST", `/admin/orders/${orderId}/approve`, decision, true);
}

export async function declineOrder(orderId, decision = {}) {
  return request("POST", `/admin/orders/${orderId}/decline`, decision, true);
}

export async function deleteOrder(orderId, password) {
  return request("POST", `/admin/orders/${orderId}/delete`, { password }, true);
}


export async function adminGetVariantsSummary(params = {}) {
  const qs = new URLSearchParams();
  if (params?.from) qs.set("from_ts", String(params.from));
  if (params?.to) qs.set("to_ts", String(params.to));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request("GET", `/admin/reports/variants-summary${suffix}`, undefined, true);
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
