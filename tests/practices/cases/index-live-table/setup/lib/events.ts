import { supabase } from "@/lib/supabase/client";

export type ClientEvent = { id: number; client_id: number; kind: string; created_at: string };

export async function eventsForClient(clientId: number): Promise<ClientEvent[]> {
  const { data, error } = await supabase.from<ClientEvent>("events").select("*", { client_id: String(clientId) });
  if (error) throw new Error(error.message);
  return data ?? [];
}
