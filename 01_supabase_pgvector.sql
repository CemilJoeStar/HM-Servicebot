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

create table if not exists chat_attachments (
    id uuid primary key default gen_random_uuid(),
    chat_id text not null,
    student_id text not null references student_profiles(student_id),
    file_name text not null,
    storage_bucket text not null default 'chat-uploads',
    storage_path text not null,
    mime_type text not null,
    file_size integer not null,
    status text not null default 'stored',
    extracted_text text,
    indexed_chunk_count integer not null default 0,
    created_at timestamptz not null default now(),
    constraint chat_attachments_status_check
        check (status in ('stored', 'indexed', 'unsupported', 'failed'))
);

create table if not exists knowledge_documents (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    source_label text not null unique,
    document_type text not null default 'policy',
    status text not null default 'active',
    version text not null default '2026',
    chunk_count integer not null default 0,
    last_indexed_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists professors (
    id uuid primary key default gen_random_uuid(),
    display_name text not null unique,
    title text not null default 'Prof. Dr.',
    department text not null default 'Wirtschaftsinformatik',
    focus_topics text[] not null default '{}',
    capacity_status text not null default 'available',
    available_slots integer not null default 0,
    office text,
    email text,
    notes text,
    updated_at timestamptz not null default now(),
    constraint professors_capacity_status_check
        check (capacity_status in ('available', 'limited', 'unavailable'))
);

alter table public.student_profiles disable row level security;
alter table public.chat_sessions disable row level security;
alter table public.chat_attachments disable row level security;
alter table public.knowledge_documents disable row level security;
alter table public.professors disable row level security;
grant select, insert, update, delete on public.student_profiles to anon, authenticated;
grant select, insert, update, delete on public.chat_sessions to anon, authenticated;
grant select, insert, update, delete on public.chat_attachments to anon, authenticated;
grant select, insert, update, delete on public.knowledge_documents to anon, authenticated;
grant select, insert, update, delete on public.professors to anon, authenticated;

create index if not exists chat_sessions_student_updated_idx
on chat_sessions (student_id, updated_at desc);

create index if not exists chat_attachments_chat_created_idx
on chat_attachments (chat_id, created_at desc);

create index if not exists chat_attachments_student_created_idx
on chat_attachments (student_id, created_at desc);

create index if not exists knowledge_documents_status_idx
on knowledge_documents (status, last_indexed_at desc);

create index if not exists professors_capacity_status_idx
on professors (capacity_status, available_slots desc);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'chat-uploads',
    'chat-uploads',
    false,
    8388608,
    array[
        'application/pdf',
        'text/plain',
        'text/markdown',
        'text/csv',
        'image/png',
        'image/jpeg',
        'image/webp'
    ]
)
on conflict (id) do update
set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

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
    'Cemil Yilmaz',
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
        'advising_note', 'Profil- und Studienverlaufsdaten für erste individuelle Studienberatung; keine rechtsverbindliche Auskunft.'
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

insert into public.knowledge_documents (
    title,
    source_label,
    document_type,
    status,
    version,
    chunk_count,
    last_indexed_at
)
values
    (
        'Rückmeldeordnung Sommersemester 2026',
        'Rückmeldeordnung Sommersemester 2026 · verifiziert',
        'policy',
        'active',
        '2026',
        1,
        now()
    ),
    (
        'Allgemeine Prüfungsordnung 2024',
        'Allgemeine Prüfungsordnung 2024 · verifiziert',
        'policy',
        'active',
        '2024',
        2,
        now()
    ),
    (
        'Modulkatalog Wirtschaftsinformatik 2026',
        'Modulkatalog Wirtschaftsinformatik 2026',
        'module_catalog',
        'active',
        '2026',
        6,
        now()
    )
on conflict (source_label) do update
set
    title = excluded.title,
    document_type = excluded.document_type,
    status = excluded.status,
    version = excluded.version,
    chunk_count = excluded.chunk_count,
    last_indexed_at = excluded.last_indexed_at;

insert into public.professors (
    display_name,
    title,
    department,
    focus_topics,
    capacity_status,
    available_slots,
    office,
    email,
    notes
)
values
    (
        'Prof. Dr. Anna Keller',
        'Prof. Dr.',
        'Wirtschaftsinformatik',
        array['Data Analytics', 'Business Intelligence', 'Process Mining'],
        'available',
        3,
        'Lothstraße, Raum R 2.14',
        'anna.keller@hm.example',
        'Betreut datengetriebene Bachelorarbeiten und Praxisprojekte.'
    ),
    (
        'Prof. Dr. Markus Brandt',
        'Prof. Dr.',
        'Informatik',
        array['Software Engineering', 'Cloud-Anwendungen', 'IT-Sicherheit'],
        'limited',
        1,
        'Lothstraße, Raum R 3.08',
        'markus.brandt@hm.example',
        'Nimmt aktuell nur wenige neue Arbeiten an.'
    ),
    (
        'Prof. Dr. Selin Aydin',
        'Prof. Dr.',
        'Wirtschaftsinformatik',
        array['Digitale Prozesse', 'Geschäftsprozessmanagement', 'Projektseminar'],
        'available',
        2,
        'Pasing, Raum P 1.22',
        'selin.aydin@hm.example',
        'Fokus auf Prozessdigitalisierung und praxisnahe Projektarbeiten.'
    ),
    (
        'Prof. Dr. Tobias Reiter',
        'Prof. Dr.',
        'Wirtschaft',
        array['Marketing', 'Digitale Geschäftsmodelle', 'E-Commerce'],
        'unavailable',
        0,
        'Pasing, Raum P 2.04',
        'tobias.reiter@hm.example',
        'Für dieses Semester keine freien Betreuungskapazitäten.'
    )
on conflict (display_name) do update
set
    title = excluded.title,
    department = excluded.department,
    focus_topics = excluded.focus_topics,
    capacity_status = excluded.capacity_status,
    available_slots = excluded.available_slots,
    office = excluded.office,
    email = excluded.email,
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
