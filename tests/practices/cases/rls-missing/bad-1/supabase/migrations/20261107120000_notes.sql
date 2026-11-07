create table public.notes (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  body text not null,
  created_at timestamptz not null default now()
);

grant select on table public.notes to anon;
grant select, insert, update, delete on table public.notes to authenticated;
grant select, insert, update, delete on table public.notes to service_role;
