const API = "/api";

// Axios instance
const api = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

// Read a cookie value by name
export function getCookie(name) {
  const match = document.cookie.match(
    new RegExp("(^|;\\s*)" + name + "=([^;]*)")
  );
  return match ? decodeURIComponent(match[2]) : "";
}

// Attach CSRF token when using cookie-based JWTs
api.interceptors.request.use((config) => {
  const method = (config.method || "get").toLowerCase();
  if (method !== "get") {
    const isRefresh = (config.url || "").includes("/auth/refresh");
    const csrf = getCookie(isRefresh ? "csrf_refresh_token" : "csrf_access_token");
    if (csrf) config.headers["X-CSRF-TOKEN"] = csrf;
  }
  return config;
});


let isRefreshing = false;
let refreshIntervalActive = false;

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config || {};

    // If logout or refresh endpoint itself fails, don't retry
    if (
      error.response?.status === 401 &&
      !original._retry &&
      !isRefreshing &&
      !original.url.includes("/auth/logout") &&
      !original.url.includes("/auth/refresh")
    ) {
      try {
        isRefreshing = true;
        console.log("Attempting token refresh");

        // Log all available cookies for debugging
        console.log("All cookies:", document.cookie);

        const csrf = getCookie("csrf_refresh_token");
        console.log("CSRF refresh token:", csrf);

        // Make the request with explicit headers
        await api.post(
          "/auth/refresh",
          {},
          {
            headers: {
              "X-CSRF-TOKEN": csrf,
            },
          }
        );

        console.log("Token refresh successful");
        isRefreshing = false;
        original._retry = true;
        return api(original);
      } catch (e) {
        console.error(
          "Token refresh failed:",
          e.response?.status,
          e.response?.data,
          e
        );
        isRefreshing = false;
        window.location.href = "/login";
      }
    }

    return Promise.reject(error);
  }
);

// Refresh CSRF token periodically (every 5 minutes), prevent overlap
setInterval(async () => {
  if (refreshIntervalActive) return;
  refreshIntervalActive = true;
  try {
    const csrf = getCookie("csrf_refresh_token");
    const res = await Post("/auth/refresh", {}, { "X-CSRF-TOKEN": csrf });
    if (res.success) {
      console.log("CSRF token refreshed successfully");
    } else {
      console.error("Failed to refresh CSRF token:", res.message);
    }
  } catch (error) {
    console.error("Error refreshing CSRF token:", error);
  } finally {
    refreshIntervalActive = false;
  }
}, 5 * 60 * 1000);

// Wrappers

// HTTP verb wrappers with custom headers support
export async function Get(path, headers = {}) {
  try {
    const res = await api.get(path, { headers });
    return res.data;
  } catch (err) {
    if (err.response && err.response.data) return err.response.data;
    throw err;
  }
}

export async function Post(path, payload = {}, headers = {}) {
  try {
    const res = await api.post(path, payload, { headers });
    return res.data;
  } catch (err) {
    if (err.response && err.response.data) return err.response.data;
    throw err;
  }
}

export async function Put(path, payload = {}, headers = {}) {
  try {
    const res = await api.put(path, payload, { headers });
    return res.data;
  } catch (err) {
    if (err.response && err.response.data) return err.response.data;
    throw err;
  }
}

export async function Delete(path, payload = {}, headers = {}) {
  try {
    const res = await api.delete(path, { data: payload, headers });
    return res.data;
  } catch (err) {
    if (err.response && err.response.data) return err.response.data;
    throw err;
  }
}

export async function Patch(path, payload = {}, headers = {}) {
  try {
    const res = await api.patch(path, payload, { headers });
    return res.data;
  } catch (err) {
    if (err.response && err.response.data) return err.response.data;
    throw err;
  }
}

// Export the axios instance for advanced use
export default api;
