alter table public.clients add column display_name text;

update public.clients set display_name = full_name;

-- Old instances write full_name and new ones display_name until the rollout ends: each fills the other.
-- full_name and this trigger go in a later migration, once no instance reads it.
create function public.clients_sync_names() returns trigger language plpgsql as $$
begin
  if tg_op = 'INSERT' then
    new.display_name := coalesce(new.display_name, new.full_name);
    new.full_name := coalesce(new.full_name, new.display_name);
  elsif new.display_name is distinct from old.display_name then
    new.full_name := new.display_name;
  elsif new.full_name is distinct from old.full_name then
    new.display_name := new.full_name;
  end if;
  return new;
end;
$$;

create trigger clients_sync_names before insert or update on public.clients
  for each row execute function public.clients_sync_names();
