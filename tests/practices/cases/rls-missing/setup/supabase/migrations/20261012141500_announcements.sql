create table public.announcements (
  id bigint generated always as identity primary key,
  title text not null,
  body text not null,
  published_at timestamptz,
  created_at timestamptz not null default now()
);

create index announcements_published_at_idx on public.announcements (published_at desc);

grant select on table public.announcements to anon;
grant select, insert, update, delete on table public.announcements to authenticated;
grant select, insert, update, delete on table public.announcements to service_role;
