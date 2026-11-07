import { supabase } from "@/lib/supabase/client";

export type Client = { id: number; display_name: string; email: string | null };

const COLUMNS = "id,display_name,email";

export async function listClients(): Promise<Client[]> {
  const { data, error } = await supabase.from<Client>("clients").select(COLUMNS);
  if (error) throw new Error(error.message);
  return data ?? [];
}

export async function getClient(id: string): Promise<Client | null> {
  const { data, error } = await supabase.from<Client>("clients").select(COLUMNS, { id });
  if (error) throw new Error(error.message);
  return data?.[0] ?? null;
}

export async function addClient(displayName: string, email: string | null = null): Promise<Client | null> {
  const { data, error } = await supabase.from<Client>("clients").insert({ display_name: displayName, email });
  if (error) throw new Error(error.message);
  return data?.[0] ?? null;
}
