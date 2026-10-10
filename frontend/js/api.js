// Thin fetch wrapper: JSON in/out, errors carry the server's message.

async function request(method, path, body, { raw = false } = {}) {
  const options = { method, headers: {} };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Cannot reach the server. Is it running?");
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      if (data.detail) {
        message = typeof data.detail === "string" ? data.detail
          : data.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
      }
    } catch { /* not JSON */ }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (raw) return response;
  return response.status === 204 ? null : response.json();
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body),
  patch: (path, body) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
  upload: (path, files, field = "files") => {
    const form = new FormData();
    for (const file of files) form.append(field, file);
    return request("POST", path, form);
  },
};

export function query(params) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") q.set(key, value);
  }
  const text = q.toString();
  return text ? `?${text}` : "";
}
