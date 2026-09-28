-- FinIntel: org-only Google login (@avaipl.com), private PDF storage, extracted documents.
--
-- After running this in the Supabase SQL editor (or via `supabase db push`):
-- 1. Authentication → Providers → Google: enable, paste the Google OAuth client id and secret.
--    Authorized redirect URI in Google Cloud:
--    https://<project-ref>.supabase.co/auth/v1/callback
-- 2. Authentication → Hooks → Before user created: select public.hook_restrict_signup.
--    The trigger below also rejects any other email domain if the hook is not enabled yet.
-- 3. Authentication → URL configuration: add the app origin (http://localhost:5173 and production).

create extension if not exists pgcrypto;

-- Reject sign-ups whose email is not the organisation domain.
-- Register this function as the "Before user created" auth hook in the dashboard.
create or replace function public.hook_restrict_signup(event jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  user_email text;
begin
  user_email := lower(coalesce(event->'user'->>'email', ''));

  if user_email !~ '@avaipl\.com$' then
    return jsonb_build_object(
      'error', jsonb_build_object(
        'http_code', 403,
        'message', 'Only @avaipl.com Google accounts can sign in.'
      )
    );
  end if;

  return '{}'::jsonb;
end;
$$;

grant execute on function public.hook_restrict_signup(jsonb) to supabase_auth_admin;
revoke execute on function public.hook_restrict_signup(jsonb) from authenticated, anon, public;

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  full_name text not null default '',
  avatar_url text not null default '',
  created_at timestamptz not null default now()
);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  user_email text;
begin
  user_email := lower(coalesce(new.email, ''));

  if user_email !~ '@avaipl\.com$' then
    raise exception 'Only @avaipl.com Google accounts can sign in'
      using errcode = '42501';
  end if;

  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    user_email,
    coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name', ''),
    coalesce(new.raw_user_meta_data->>'avatar_url', new.raw_user_meta_data->>'picture', '')
  )
  on conflict (id) do update
    set email = excluded.email,
        full_name = excluded.full_name,
        avatar_url = excluded.avatar_url;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

alter table public.profiles enable row level security;

drop policy if exists "org members read profiles" on public.profiles;
create policy "org members read profiles"
  on public.profiles
  for select
  to authenticated
  using ((auth.jwt() ->> 'email') ilike '%@avaipl.com');

-- One row per processed upload. `extraction` is the full normalized job JSON.
create table if not exists public.documents (
  id uuid primary key,
  uploaded_by uuid references auth.users (id) on delete set null,
  file_name text not null default '',
  storage_bucket text not null default 'invoices',
  storage_path text not null default '',
  content_hash text not null default '',
  status text not null default 'completed',
  document_type text not null default 'unknown',
  invoice_number text not null default '',
  vendor_name text not null default '',
  vendor_gstin text not null default '',
  customer_name text not null default '',
  grand_total numeric,
  line_item_count integer not null default 0,
  document_date text not null default '',
  extraction jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists documents_invoice_number_idx on public.documents (invoice_number);
create index if not exists documents_vendor_gstin_idx on public.documents (vendor_gstin);
create index if not exists documents_content_hash_idx on public.documents (content_hash);
create index if not exists documents_created_at_idx on public.documents (created_at desc);

create table if not exists public.document_line_items (
  id bigint generated always as identity primary key,
  document_id uuid not null references public.documents (id) on delete cascade,
  line_index integer not null,
  item jsonb not null,
  unique (document_id, line_index)
);

create index if not exists document_line_items_document_id_idx
  on public.document_line_items (document_id);

alter table public.documents enable row level security;
alter table public.document_line_items enable row level security;

-- Reads are limited to signed-in @avaipl.com users.
-- Writes go through the API with the service role, which bypasses RLS.
drop policy if exists "org members read documents" on public.documents;
create policy "org members read documents"
  on public.documents
  for select
  to authenticated
  using ((auth.jwt() ->> 'email') ilike '%@avaipl.com');

drop policy if exists "org members read line items" on public.document_line_items;
create policy "org members read line items"
  on public.document_line_items
  for select
  to authenticated
  using ((auth.jwt() ->> 'email') ilike '%@avaipl.com');

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'invoices',
  'invoices',
  false,
  52428800,
  array['application/pdf', 'image/jpeg', 'image/png', 'image/tiff']
)
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "org members read invoices" on storage.objects;
create policy "org members read invoices"
  on storage.objects
  for select
  to authenticated
  using (
    bucket_id = 'invoices'
    and (auth.jwt() ->> 'email') ilike '%@avaipl.com'
  );
