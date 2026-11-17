create table public.clients (
  id bigint generated always as identity primary key,
  full_name text not null,
  email text,
  created_at timestamptz not null default now()
);

alter table public.clients enable row level security;

create policy "clients: the team works on all of them" on public.clients
  for all to authenticated
  using (true)
  with check (true);

grant select, insert, update, delete on table public.clients to authenticated;
grant select, insert, update, delete on table public.clients to service_role;

insert into public.clients (full_name, email) values
  ('Atelier Nord', 'hello@ateliernord.example'),
  ('Maison Sud', 'contact@maisonsud.example'),
  ('Studio Est', null);
