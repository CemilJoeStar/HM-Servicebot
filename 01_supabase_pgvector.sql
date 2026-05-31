-- Supabase SQL setup for a minimal LangChain + pgvector RAG prototype.
-- Run this once in the Supabase SQL Editor.

create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(768) not null,
    created_at timestamptz not null default now()
);

-- Prototype setting: allow local ingestion with a simple publishable/anon key setup.
-- For production, enable RLS again and add proper policies/service-role usage.
alter table public.documents disable row level security;
grant usage on schema public to anon, authenticated;
grant select, insert, update, delete on public.documents to anon, authenticated;

-- If your Supabase project/dashboard keeps RLS enabled, use this permissive
-- local-prototype policy instead. It is intentionally broad for testing only.
create policy if not exists "prototype allow all documents access"
on public.documents
for all
to anon, authenticated
using (true)
with check (true);

-- Cosine-distance index. Lists can be tuned later when the table grows.
create index if not exists documents_embedding_ivfflat_idx
on documents
using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

create index if not exists documents_metadata_gin_idx
on documents
using gin (metadata);

-- RPC function used by LangChain's SupabaseVectorStore.
-- The Python prototype uses gemini-embedding-001 with output_dimensionality=768.
create or replace function match_documents(
    query_embedding vector(768),
    match_count int default 4,
    filter jsonb default '{}'::jsonb
)
returns table (
    id uuid,
    content text,
    metadata jsonb,
    similarity float
)
language plpgsql
security definer
set search_path = public
as $$
begin
    return query
    select
        documents.id,
        documents.content,
        documents.metadata,
        1 - (documents.embedding <=> query_embedding) as similarity
    from documents
    where documents.metadata @> filter
    order by documents.embedding <=> query_embedding
    limit match_count;
end;
$$;

grant execute on function public.match_documents(vector(768), int, jsonb) to anon, authenticated;

-- Make PostgREST pick up table/function changes immediately.
notify pgrst, 'reload schema';
