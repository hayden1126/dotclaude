alter table public.clients add column display_name text;

update public.clients set display_name = full_name;

alter table public.clients alter column display_name set not null;
alter table public.clients drop column full_name;
