create table public.notes (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  body text not null,
  created_at timestamptz not null default now()
);

alter table public.notes enable row level security;

create policy "notes: read own" on public.notes
  for select to authenticated
  using (user_id = auth.uid());

create policy "notes: add own" on public.notes
  for insert to authenticated
  with check (user_id = auth.uid());

create policy "notes: change own" on public.notes
  for update to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "notes: remove own" on public.notes
  for delete to authenticated
  using (user_id = auth.uid());

grant select on table public.notes to anon;
grant select, insert, update, delete on table public.notes to authenticated;
grant select, insert, update, delete on table public.notes to service_role;
