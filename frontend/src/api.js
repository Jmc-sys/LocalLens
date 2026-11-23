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
  // Preserve multipart uploads and let the browser set the boundary.
  const isMultipart =
    Object.prototype.toString.call(options.body) === "[object FormData]";

  if (isMultipart) {
    headers.delete("Content-Type");

    // Work around iOS WebKit sending disk-backed File uploads
    // with Content-Length: 0.
    // Blob.slice() preserves the original bytes without reading
    // the entire file into JavaScript memory.
    const isIOS =
      /iPhone|iPad|iPod/i.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" &&
       navigator.maxTouchPoints > 1);

    const selectedFile = options.body.get("file");

    if (isIOS && selectedFile instanceof File &&
        selectedFile.size > 0) {
      const safeBlob = selectedFile.slice(
        0,
        selectedFile.size,
        selectedFile.type
      );

      options.body.set("file", safeBlob, selectedFile.name);
    }

    const uploadRoute =
      /^\/(?:photos\/upload|videos\/upload|media\/auto-motion|live\/\d+\/motion)$/;

    if (uploadRoute.test(path) &&
        !(options.body.get("file") instanceof Blob)) {
      throw new Error(`Upload ${path}: no file was attached by the browser`);
    }
  }
  const response = await fetch(`/api${path}`, {...options, headers});
  if (response.status === 401 && path !== "/auth/login") expireLocal(token);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data?.detail;
    const isValidation = Array.isArray(detail);
    const explanation = typeof detail === "string" ? detail
      : isValidation ? detail.slice(0, 5).map((problem) => {
          const field = Array.isArray(problem.loc) ? problem.loc.join(".") : "request";
          return `${field}: ${problem.msg || problem.type || "Invalid value"}`;
        }).join("; ")
      : typeof data?.message === "string" ? data.message
      : "Request rejected without a readable error message";
    const attached = isMultipart ? options.body.get("file") : null;
    const uploadInfo = isMultipart
      ? ` [multipart, file=${attached instanceof Blob ? `${attached.size} bytes` : "missing"}]`
      : "";
    const error = new Error(`${(options.method || "GET").toUpperCase()} /api${path}: HTTP ${response.status}: ${explanation}${uploadInfo}`);
    error.status = response.status;
    error.validationErrors = isValidation ? detail : null;
    throw error;
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
