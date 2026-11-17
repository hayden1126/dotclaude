// The browser's client for Supabase: the REST and auth endpoints over fetch, in the shape of
// supabase-js, for the few calls this app makes.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export type AuthUser = { id: string; email: string };
export type Result<T> = { data: T | null; error: { message: string } | null };

function headers(): Record<string, string> {
  const token = globalThis.localStorage?.getItem("sb-access-token");
  return { apikey: anonKey, Authorization: `Bearer ${token ?? anonKey}`, "Content-Type": "application/json" };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<Result<T>> {
  const response = await fetch(`${url}${path}`, { ...init, headers: { ...headers(), ...init.headers } });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  return response.ok ? { data: body as T, error: null } : { data: null, error: { message: body?.message ?? response.statusText } };
}

function query(filters: Record<string, string>): string {
  return Object.entries(filters).map(([column, value]) => `&${column}=eq.${encodeURIComponent(value)}`).join("");
}

export const supabase = {
  auth: {
    getUser: () => request<AuthUser>("/auth/v1/user"),
  },
  from<Row>(table: string) {
    return {
      select: (columns = "*", filters: Record<string, string> = {}) =>
        request<Row[]>(`/rest/v1/${table}?select=${columns}${query(filters)}`),
      insert: (row: Partial<Row>) =>
        request<Row[]>(`/rest/v1/${table}`, { method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify(row) }),
      update: (patch: Partial<Row>, filters: Record<string, string>) =>
        request<Row[]>(`/rest/v1/${table}?${query(filters).slice(1)}`, { method: "PATCH", headers: { Prefer: "return=representation" }, body: JSON.stringify(patch) }),
      delete: (filters: Record<string, string>) =>
        request<null>(`/rest/v1/${table}?${query(filters).slice(1)}`, { method: "DELETE" }),
    };
  },
};
