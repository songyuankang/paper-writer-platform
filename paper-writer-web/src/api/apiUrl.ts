/**
 * Normalise an optional Vite API base URL before application paths are appended.
 * API base URLs cannot contain whitespace.  Application callers use `/api/...`
 * paths, so trailing slashes must also be removed to avoid duplicate separators.
 */
export function normalizeApiBase(value: string | undefined): string {
  return (value ?? "")
    .trim()
    .replace(/\s+/g, "")
    .replace(/\/+$/, "")
    .trim();
}

export function buildApiUrl(baseUrl: string | undefined, path: string): string {
  const base = normalizeApiBase(baseUrl);
  const normalizedPath = `/${path.trim().replace(/^\/+/, "")}`;
  return `${base}${normalizedPath}`;
}
