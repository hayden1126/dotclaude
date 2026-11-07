create table public.plans (
  id bigint generated always as identity primary key,
  name text not null unique,
  monthly_cents integer not null,
  invoice_limit integer,
  created_at timestamptz not null default now()
);

grant select on table public.plans to anon;
grant select, insert, update, delete on table public.plans to authenticated;
grant select, insert, update, delete on table public.plans to service_role;

insert into public.plans (name, monthly_cents, invoice_limit) values
  ('Free', 0, 10),
  ('Studio', 1900, null);
