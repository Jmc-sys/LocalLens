const TOKEN_KEY = "locallens_access_token";
export function getToken() { return sessionStorage.getItem(TOKEN_KEY); }
export function setToken(token) { sessionStorage.setItem(TOKEN_KEY, token); }
export function clearToken() { sessionStorage.removeItem(TOKEN_KEY); }
function expireLocal(token) {
  if (token && getToken() === token) {
    clearToken();
    window.dispatchEvent(new Event("locallens:logout"));
  }
}
export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, {...options, headers});
  if (response.status === 401 && path !== "/auth/login") expireLocal(token);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Request failed: HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}
export async function login(username, password) {
  const result = await api("/auth/login", {method: "POST", body: JSON.stringify({username, password})});
  setToken(result.access_token);
  return api("/auth/me");
}
export async function logout() {
  const token = getToken();
  clearToken();
  window.dispatchEvent(new Event("locallens:logout"));
  if (!token) return;
  try {
    const response = await fetch("/api/auth/logout", {method: "POST", headers: {Authorization: `Bearer ${token}`}, signal: AbortSignal.timeout(5000)});
    if (!response.ok && response.status !== 401) throw new Error("Server logout failed");
  } catch (error) {
    console.warn("Server logout could not be confirmed", error);
    window.alert("Signed out locally, but server session revocation could not be confirmed. The token will expire automatically.");
  }
}
export async function mediaBlob(photoId, type = "thumbnail", signal) {
  const token = getToken();
  const response = await fetch(`/api/photos/${photoId}/${type}`, {headers: {Authorization: `Bearer ${token}`}, signal});
  if (response.status === 401) expireLocal(token);
  if (!response.ok) throw new Error("Unable to retrieve photo");
  return response.blob();
}
