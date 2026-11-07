create table public.events (
  id bigint generated always as identity primary key,
  client_id bigint not null,
  kind text not null,
  created_at timestamptz not null default now()
);

grant select on table public.events to authenticated;
grant select, insert, update, delete on table public.events to service_role;
