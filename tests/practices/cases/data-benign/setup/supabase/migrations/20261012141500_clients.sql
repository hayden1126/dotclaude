create table public.clients (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  name text not null,
  email text,
  created_at timestamptz not null default now()
);

alter table public.clients enable row level security;

create policy "clients: read own" on public.clients
  for select to authenticated
  using (user_id = auth.uid());

create policy "clients: add own" on public.clients
  for insert to authenticated
  with check (user_id = auth.uid());

create policy "clients: change own" on public.clients
  for update to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "clients: remove own" on public.clients
  for delete to authenticated
  using (user_id = auth.uid());

grant select, insert, update, delete on table public.clients to authenticated;
grant select, insert, update, delete on table public.clients to service_role;
