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

create table if not exists student_profiles (
    student_id text primary key,
    display_name text not null,
    study_program text not null,
    semester integer not null,
    ects_earned integer not null,
    enrollment_status text not null,
    semester_fee_paid boolean not null default false,
    thesis_registered boolean not null default false,
    notes jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists chat_sessions (
    id uuid primary key default gen_random_uuid(),
    student_id text not null references student_profiles(student_id),
    title text not null,
    meta text not null default 'gerade eben',
    messages jsonb not null default '[]'::jsonb,
    pinned boolean not null default false,
    archived_at timestamptz,
    deleted_at timestamptz,
    updated_at timestamptz not null default now()
);

alter table public.student_profiles disable row level security;
alter table public.chat_sessions disable row level security;
grant select, insert, update, delete on public.student_profiles to anon, authenticated;
grant select, insert, update, delete on public.chat_sessions to anon, authenticated;

create index if not exists chat_sessions_student_updated_idx
on chat_sessions (student_id, updated_at desc);

insert into public.student_profiles (
    student_id,
    display_name,
    study_program,
    semester,
    ects_earned,
    enrollment_status,
    semester_fee_paid,
    thesis_registered,
    notes
)
values (
    'demo-student-001',
    'Demo Student',
    'Wirtschaftsinformatik B.Sc.',
    5,
    118,
    'immatrikuliert',
    false,
    false,
    jsonb_build_object(
        'campus', 'Lothstraße',
        'interests', jsonb_build_array('Data Analytics', 'Software Engineering', 'Digitale Prozesse'),
        'completed_modules', jsonb_build_array(
            jsonb_build_object('name', 'Programmierung 1', 'ects', 5, 'category', 'Pflichtmodul'),
            jsonb_build_object('name', 'Datenbanken', 'ects', 5, 'category', 'Pflichtmodul'),
            jsonb_build_object('name', 'Statistik', 'ects', 5, 'category', 'Pflichtmodul'),
            jsonb_build_object('name', 'Software Engineering', 'ects', 5, 'category', 'Pflichtmodul'),
            jsonb_build_object('name', 'Geschäftsprozessmanagement', 'ects', 5, 'category', 'Pflichtmodul'),
            jsonb_build_object('name', 'Marketing', 'ects', 5, 'category', 'Wahlpflichtmodul'),
            jsonb_build_object('name', 'Business Intelligence', 'ects', 5, 'category', 'Wahlpflichtmodul')
        ),
        'open_modules', jsonb_build_array(
            jsonb_build_object('name', 'IT-Sicherheit', 'ects', 5, 'category', 'Pflichtmodul'),
            jsonb_build_object('name', 'Projektseminar', 'ects', 5, 'category', 'Pflichtmodul')
        ),
        'advising_note', 'Demo-Daten für erste individuelle Studienberatung; keine rechtsverbindliche Auskunft.'
    )
)
on conflict (student_id) do update
set
    display_name = excluded.display_name,
    study_program = excluded.study_program,
    semester = excluded.semester,
    ects_earned = excluded.ects_earned,
    enrollment_status = excluded.enrollment_status,
    semester_fee_paid = excluded.semester_fee_paid,
    thesis_registered = excluded.thesis_registered,
    notes = excluded.notes,
    updated_at = now();

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
