--
-- PostgreSQL database dump
--


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: feedbackcategory; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.feedbackcategory AS ENUM (
    'bug',
    'model_quality',
    'feature_request',
    'other'
);


--
-- Name: gamesystem; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.gamesystem AS ENUM (
    'dnd_5e',
    'pathfinder_2e',
    'warhammer_fantasy',
    'starfinder',
    'cyberpunk_red',
    'shadowrun',
    'call_of_cthulhu',
    'world_of_darkness',
    'elden_ring',
    'final_fantasy',
    'world_of_warcraft',
    'baldurs_gate',
    'generic'
);


--
-- Name: genre; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.genre AS ENUM (
    'fantasy',
    'scifi',
    'horror',
    'videogame',
    'other'
);


--
-- Name: npcrole; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.npcrole AS ENUM (
    'npc',
    'pc',
    'monster',
    'faction'
);


--
-- Name: npcstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.npcstatus AS ENUM (
    'alive',
    'dead',
    'unknown'
);


--
-- Name: queststatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.queststatus AS ENUM (
    'active',
    'completed',
    'failed',
    'abandoned'
);


--
-- Name: scenariotype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scenariotype AS ENUM (
    'combat',
    'exploration',
    'social',
    'loot',
    'rest',
    'quest_update',
    'boss_fight',
    'character_development',
    'world_event',
    'travel',
    'puzzle',
    'downtime'
);


--
-- Name: tagtype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tagtype AS ENUM (
    'character',
    'location',
    'item',
    'quest',
    'faction'
);


--
-- Name: traininggenre; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.traininggenre AS ENUM (
    'fantasy',
    'scifi',
    'horror',
    'videogame',
    'other'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: admin_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_messages (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    subject character varying(200) NOT NULL,
    message text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: app_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_config (
    id integer NOT NULL,
    open_access_mode boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: app_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.app_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: app_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.app_config_id_seq OWNED BY public.app_config.id;


--
-- Name: campaign_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_members (
    id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: campaign_share_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_share_tokens (
    id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    created_by_user_id uuid NOT NULL,
    token character varying(64) NOT NULL,
    revoked boolean NOT NULL,
    kind character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: campaigns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaigns (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    genre public.genre NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: character_sheet_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.character_sheet_templates (
    id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    created_by_user_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    fields jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: character_sheets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.character_sheets (
    id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    template_id uuid NOT NULL,
    created_by_user_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_sessions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid,
    title character varying(120) NOT NULL,
    messages jsonb NOT NULL,
    message_count integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid,
    category public.feedbackcategory NOT NULL,
    message text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: journal_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_entries (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    shorthand text NOT NULL,
    narrative text NOT NULL,
    narrative_tsv tsvector,
    entry_hash character varying(64) NOT NULL,
    session_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    embedding public.vector(384)
);


--
-- Name: journal_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_tags (
    journal_id uuid NOT NULL,
    tag_id uuid NOT NULL
);


--
-- Name: model_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_evaluations (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    label character varying(100) NOT NULL,
    sample_size integer NOT NULL,
    avg_length double precision NOT NULL,
    avg_word_overlap double precision NOT NULL,
    has_content_pct double precision NOT NULL,
    error_count integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    avg_semantic_similarity double precision
);


--
-- Name: npcs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.npcs (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    role public.npcrole NOT NULL,
    status public.npcstatus NOT NULL,
    description text,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: password_reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.password_reset_tokens (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: promo_code_redemptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.promo_code_redemptions (
    id uuid NOT NULL,
    promo_code_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: promo_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.promo_codes (
    id uuid NOT NULL,
    code character varying(50) NOT NULL,
    active boolean NOT NULL,
    max_redemptions integer,
    redemption_count integer NOT NULL,
    expires_at timestamp with time zone,
    note character varying(200),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    grants_plan character varying(20) DEFAULT 'byok'::character varying NOT NULL
);


--
-- Name: quests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quests (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    title character varying(300) NOT NULL,
    description text,
    status public.queststatus NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_plans (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: shorthand_terms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shorthand_terms (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    term character varying(50) NOT NULL,
    meaning text NOT NULL,
    usage text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: source_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_chunks (
    id uuid NOT NULL,
    source_document_id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding public.vector(384),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: source_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_documents (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    filename character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subscriptions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    stripe_customer_id character varying(255),
    stripe_subscription_id character varying(255),
    status character varying(20) NOT NULL,
    current_period_end timestamp with time zone,
    period_started_at timestamp with time zone,
    tokens_used_current_period integer NOT NULL,
    tokens_included_per_period integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    plan character varying(20)
);


--
-- Name: tag_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tag_categories (
    id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    created_by_user_id uuid NOT NULL,
    name character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tags (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    tag_type public.tagtype,
    custom_category_id uuid
);


--
-- Name: training_samples; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_samples (
    id uuid NOT NULL,
    genre public.traininggenre NOT NULL,
    game_system public.gamesystem NOT NULL,
    scenario_type public.scenariotype NOT NULL,
    instruction text NOT NULL,
    shorthand text NOT NULL,
    narrative text,
    is_validated boolean DEFAULT false NOT NULL,
    quality_score double precision,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_settings (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    llm_provider character varying(50) DEFAULT 'kobold'::character varying NOT NULL,
    llm_api_url character varying(500),
    llm_api_key character varying(500),
    llm_model character varying(200),
    llm_temperature double precision DEFAULT '0.72'::double precision NOT NULL,
    llm_max_tokens integer DEFAULT 800 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    hosted_model_variant character varying(20) DEFAULT 'finetuned'::character varying NOT NULL,
    narrative_paragraph_limit integer
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying(255) NOT NULL,
    hashed_password character varying(255) NOT NULL,
    display_name character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    avatar_data text,
    access_granted boolean DEFAULT false NOT NULL,
    access_source character varying(20),
    is_suspended boolean DEFAULT false NOT NULL,
    suspended_reason character varying(500),
    suspended_at timestamp with time zone,
    is_admin boolean DEFAULT false NOT NULL,
    has_completed_tutorial boolean DEFAULT true NOT NULL,
    password_changed_at timestamp with time zone,
    failed_login_attempts integer DEFAULT 0 NOT NULL,
    locked_until timestamp with time zone
);


--
-- Name: app_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_config ALTER COLUMN id SET DEFAULT nextval('public.app_config_id_seq'::regclass);


--
-- Data for Name: admin_messages; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.alembic_version (version_num) VALUES ('a3e7c1f9d258');


--
-- Data for Name: app_config; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.app_config (id, open_access_mode, created_at, updated_at) VALUES (1, true, '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');


--
-- Data for Name: campaign_members; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.campaign_members (id, campaign_id, user_id, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000301', '00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000002', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');
INSERT INTO public.campaign_members (id, campaign_id, user_id, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000302', '00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000003', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');


--
-- Data for Name: campaign_share_tokens; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.campaign_share_tokens (id, campaign_id, created_by_user_id, token, revoked, kind, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000401', '00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000001', 'seed-share-token-read_only', false, 'read_only', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');
INSERT INTO public.campaign_share_tokens (id, campaign_id, created_by_user_id, token, revoked, kind, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000402', '00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000001', 'seed-share-token-collaborate', false, 'collaborate', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');


--
-- Data for Name: campaigns; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.campaigns (id, user_id, name, genre, description, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000101', '00000000-0000-4000-8000-000000000001', 'The Brackenford Bell', 'fantasy', 'Seed campaign for the migration snapshot.', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');


--
-- Data for Name: character_sheet_templates; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: character_sheets; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: chat_sessions; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.chat_sessions (id, user_id, campaign_id, title, messages, message_count, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000901', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'Seed chat 1', '[{"role": "user", "content": "Where is the bell?"}]', 1, '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');
INSERT INTO public.chat_sessions (id, user_id, campaign_id, title, messages, message_count, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000902', '00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000101', 'Seed chat 2', '[{"role": "user", "content": "Where is the bell?"}]', 1, '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');
INSERT INTO public.chat_sessions (id, user_id, campaign_id, title, messages, message_count, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000903', '00000000-0000-4000-8000-000000000003', NULL, 'Seed chat 3', '[{"role": "user", "content": "Where is the bell?"}]', 1, '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');


--
-- Data for Name: feedback; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: journal_entries; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.journal_entries (id, user_id, campaign_id, shorthand, narrative, narrative_tsv, entry_hash, session_date, created_at, updated_at, embedding) VALUES ('00000000-0000-4000-8000-000000000201', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'party reached brackenford, met the millwright, bought rope', 'We came down out of the hills at dusk and found the old mill still turning.', '''bought'':7 ''brackenford'':3 ''came'':10 ''dusk'':17 ''found'':19 ''hill'':15 ''met'':4 ''mill'':22 ''millwright'':6 ''old'':21 ''parti'':1 ''reach'':2 ''rope'':8 ''still'':23 ''turn'':24', 'seed-entry-hash-1', '2026-01-01', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00', NULL);
INSERT INTO public.journal_entries (id, user_id, campaign_id, shorthand, narrative, narrative_tsv, entry_hash, session_date, created_at, updated_at, embedding) VALUES ('00000000-0000-4000-8000-000000000202', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'fought goblins at the ford, Veyra hurt', 'Steel rang across the water as the goblins broke from the reeds.', '''across'':10 ''broke'':16 ''ford'':5 ''fought'':1 ''goblin'':2,15 ''hurt'':7 ''rang'':9 ''reed'':19 ''steel'':8 ''veyra'':6 ''water'':12', 'seed-entry-hash-2', '2026-01-08', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00', NULL);
INSERT INTO public.journal_entries (id, user_id, campaign_id, shorthand, narrative, narrative_tsv, entry_hash, session_date, created_at, updated_at, embedding) VALUES ('00000000-0000-4000-8000-000000000203', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'rest at inn, Veyra recovers, quest for the lost bell', 'The inn was warm and loud; by morning Veyra could stand again.', '''bell'':10 ''could'':20 ''inn'':3,12 ''lost'':9 ''loud'':16 ''morn'':18 ''quest'':6 ''recov'':5 ''rest'':1 ''stand'':21 ''veyra'':4,19 ''warm'':14', 'seed-entry-hash-3', '2026-01-15', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00', NULL);


--
-- Data for Name: journal_tags; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.journal_tags (journal_id, tag_id) VALUES ('00000000-0000-4000-8000-000000000202', '00000000-0000-4000-8000-000000000601');


--
-- Data for Name: model_evaluations; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: npcs; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.npcs (id, user_id, campaign_id, name, role, status, description, notes, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000701', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'Veyra', 'pc', 'alive', 'A ranger from the eastern hills.', 'Secretly the heir to Brackenford.', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');
INSERT INTO public.npcs (id, user_id, campaign_id, name, role, status, description, notes, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000702', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'The Millwright', 'npc', 'unknown', NULL, NULL, '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');
INSERT INTO public.npcs (id, user_id, campaign_id, name, role, status, description, notes, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000703', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'The Reed Guild', 'faction', 'dead', 'Smugglers who worked the ford.', 'Broken up by the party.', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');


--
-- Data for Name: password_reset_tokens; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: promo_code_redemptions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: promo_codes; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: quests; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.quests (id, user_id, campaign_id, title, description, status, notes, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000801', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'Find the lost bell', 'The mill bell vanished a year ago.', 'active', NULL, '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');
INSERT INTO public.quests (id, user_id, campaign_id, title, description, status, notes, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000802', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'Clear the ford', NULL, 'completed', 'The goblin chief escaped.', '2026-01-01 12:00:00+00', '2026-01-08 18:30:00+00');


--
-- Data for Name: session_plans; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: shorthand_terms; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.shorthand_terms (id, user_id, campaign_id, term, meaning, usage, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000501', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000101', 'BF', 'Brackenford', 'BF mill', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00');


--
-- Data for Name: source_chunks; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: source_documents; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: subscriptions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: tag_categories; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: tags; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.tags (id, name, tag_type, custom_category_id) VALUES ('00000000-0000-4000-8000-000000000601', 'Veyra', 'character', NULL);


--
-- Data for Name: training_samples; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_settings; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.users (id, email, hashed_password, display_name, created_at, updated_at, avatar_data, access_granted, access_source, is_suspended, suspended_reason, suspended_at, is_admin, has_completed_tutorial, password_changed_at, failed_login_attempts, locked_until) VALUES ('00000000-0000-4000-8000-000000000001', 'owner@example.test', 'not-a-real-hash', 'Owner', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00', NULL, true, NULL, false, NULL, NULL, false, true, NULL, 0, NULL);
INSERT INTO public.users (id, email, hashed_password, display_name, created_at, updated_at, avatar_data, access_granted, access_source, is_suspended, suspended_reason, suspended_at, is_admin, has_completed_tutorial, password_changed_at, failed_login_attempts, locked_until) VALUES ('00000000-0000-4000-8000-000000000002', 'member-a@example.test', 'not-a-real-hash', 'Member A', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00', NULL, true, NULL, false, NULL, NULL, false, true, NULL, 0, NULL);
INSERT INTO public.users (id, email, hashed_password, display_name, created_at, updated_at, avatar_data, access_granted, access_source, is_suspended, suspended_reason, suspended_at, is_admin, has_completed_tutorial, password_changed_at, failed_login_attempts, locked_until) VALUES ('00000000-0000-4000-8000-000000000003', 'member-b@example.test', 'not-a-real-hash', 'Member B', '2026-01-01 12:00:00+00', '2026-01-01 12:00:00+00', NULL, true, NULL, false, NULL, NULL, false, true, NULL, 0, NULL);


--
-- Name: app_config_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.app_config_id_seq', 1, false);


--
-- Name: admin_messages admin_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_messages
    ADD CONSTRAINT admin_messages_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: app_config app_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_config
    ADD CONSTRAINT app_config_pkey PRIMARY KEY (id);


--
-- Name: campaign_members campaign_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_members
    ADD CONSTRAINT campaign_members_pkey PRIMARY KEY (id);


--
-- Name: campaign_share_tokens campaign_share_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_share_tokens
    ADD CONSTRAINT campaign_share_tokens_pkey PRIMARY KEY (id);


--
-- Name: campaigns campaigns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT campaigns_pkey PRIMARY KEY (id);


--
-- Name: character_sheet_templates character_sheet_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_sheet_templates
    ADD CONSTRAINT character_sheet_templates_pkey PRIMARY KEY (id);


--
-- Name: character_sheets character_sheets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_sheets
    ADD CONSTRAINT character_sheets_pkey PRIMARY KEY (id);


--
-- Name: chat_sessions chat_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);


--
-- Name: feedback feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_pkey PRIMARY KEY (id);


--
-- Name: journal_entries journal_entries_entry_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT journal_entries_entry_hash_key UNIQUE (entry_hash);


--
-- Name: journal_entries journal_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT journal_entries_pkey PRIMARY KEY (id);


--
-- Name: journal_tags journal_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_tags
    ADD CONSTRAINT journal_tags_pkey PRIMARY KEY (journal_id, tag_id);


--
-- Name: model_evaluations model_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_evaluations
    ADD CONSTRAINT model_evaluations_pkey PRIMARY KEY (id);


--
-- Name: npcs npcs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npcs
    ADD CONSTRAINT npcs_pkey PRIMARY KEY (id);


--
-- Name: password_reset_tokens password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);


--
-- Name: password_reset_tokens password_reset_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_token_hash_key UNIQUE (token_hash);


--
-- Name: promo_code_redemptions promo_code_redemptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promo_code_redemptions
    ADD CONSTRAINT promo_code_redemptions_pkey PRIMARY KEY (id);


--
-- Name: promo_code_redemptions promo_code_redemptions_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promo_code_redemptions
    ADD CONSTRAINT promo_code_redemptions_user_id_key UNIQUE (user_id);


--
-- Name: promo_codes promo_codes_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promo_codes
    ADD CONSTRAINT promo_codes_code_key UNIQUE (code);


--
-- Name: promo_codes promo_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promo_codes
    ADD CONSTRAINT promo_codes_pkey PRIMARY KEY (id);


--
-- Name: quests quests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quests
    ADD CONSTRAINT quests_pkey PRIMARY KEY (id);


--
-- Name: session_plans session_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_plans
    ADD CONSTRAINT session_plans_pkey PRIMARY KEY (id);


--
-- Name: shorthand_terms shorthand_terms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shorthand_terms
    ADD CONSTRAINT shorthand_terms_pkey PRIMARY KEY (id);


--
-- Name: source_chunks source_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_chunks
    ADD CONSTRAINT source_chunks_pkey PRIMARY KEY (id);


--
-- Name: source_documents source_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_pkey PRIMARY KEY (id);


--
-- Name: subscriptions subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (id);


--
-- Name: subscriptions subscriptions_stripe_subscription_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_stripe_subscription_id_key UNIQUE (stripe_subscription_id);


--
-- Name: subscriptions subscriptions_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_user_id_key UNIQUE (user_id);


--
-- Name: tag_categories tag_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_categories
    ADD CONSTRAINT tag_categories_pkey PRIMARY KEY (id);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);


--
-- Name: training_samples training_samples_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_samples
    ADD CONSTRAINT training_samples_pkey PRIMARY KEY (id);


--
-- Name: campaign_members uq_campaign_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_members
    ADD CONSTRAINT uq_campaign_member UNIQUE (campaign_id, user_id);


--
-- Name: tag_categories uq_tag_category_campaign_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_categories
    ADD CONSTRAINT uq_tag_category_campaign_name UNIQUE (campaign_id, name);


--
-- Name: tags uq_tag_name_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT uq_tag_name_type UNIQUE (name, tag_type);


--
-- Name: user_settings user_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_pkey PRIMARY KEY (id);


--
-- Name: user_settings user_settings_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_user_id_key UNIQUE (user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_campaign_share_tokens_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_campaign_share_tokens_token ON public.campaign_share_tokens USING btree (token);


--
-- Name: ix_journal_narrative_fts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_journal_narrative_fts ON public.journal_entries USING gin (narrative_tsv);


--
-- Name: ix_password_reset_tokens_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_password_reset_tokens_token_hash ON public.password_reset_tokens USING btree (token_hash);


--
-- Name: ix_promo_codes_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_promo_codes_code ON public.promo_codes USING btree (code);


--
-- Name: ix_subscriptions_stripe_customer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subscriptions_stripe_customer_id ON public.subscriptions USING btree (stripe_customer_id);


--
-- Name: ix_tags_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tags_name ON public.tags USING btree (name);


--
-- Name: ix_training_samples_game_system; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_samples_game_system ON public.training_samples USING btree (game_system);


--
-- Name: ix_training_samples_genre; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_samples_genre ON public.training_samples USING btree (genre);


--
-- Name: ix_training_samples_scenario_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_training_samples_scenario_type ON public.training_samples USING btree (scenario_type);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: admin_messages admin_messages_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_messages
    ADD CONSTRAINT admin_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: campaign_members campaign_members_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_members
    ADD CONSTRAINT campaign_members_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: campaign_members campaign_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_members
    ADD CONSTRAINT campaign_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: campaign_share_tokens campaign_share_tokens_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_share_tokens
    ADD CONSTRAINT campaign_share_tokens_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: campaign_share_tokens campaign_share_tokens_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_share_tokens
    ADD CONSTRAINT campaign_share_tokens_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: campaigns campaigns_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT campaigns_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: character_sheet_templates character_sheet_templates_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_sheet_templates
    ADD CONSTRAINT character_sheet_templates_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: character_sheet_templates character_sheet_templates_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_sheet_templates
    ADD CONSTRAINT character_sheet_templates_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: character_sheets character_sheets_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_sheets
    ADD CONSTRAINT character_sheets_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: character_sheets character_sheets_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_sheets
    ADD CONSTRAINT character_sheets_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: character_sheets character_sheets_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_sheets
    ADD CONSTRAINT character_sheets_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.character_sheet_templates(id) ON DELETE CASCADE;


--
-- Name: chat_sessions chat_sessions_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE SET NULL;


--
-- Name: chat_sessions chat_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: feedback feedback_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE SET NULL;


--
-- Name: feedback feedback_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: journal_entries journal_entries_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT journal_entries_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: journal_entries journal_entries_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_entries
    ADD CONSTRAINT journal_entries_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: journal_tags journal_tags_journal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_tags
    ADD CONSTRAINT journal_tags_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES public.journal_entries(id) ON DELETE CASCADE;


--
-- Name: journal_tags journal_tags_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_tags
    ADD CONSTRAINT journal_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id) ON DELETE CASCADE;


--
-- Name: model_evaluations model_evaluations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_evaluations
    ADD CONSTRAINT model_evaluations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: npcs npcs_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npcs
    ADD CONSTRAINT npcs_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: npcs npcs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npcs
    ADD CONSTRAINT npcs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: password_reset_tokens password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: promo_code_redemptions promo_code_redemptions_promo_code_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promo_code_redemptions
    ADD CONSTRAINT promo_code_redemptions_promo_code_id_fkey FOREIGN KEY (promo_code_id) REFERENCES public.promo_codes(id) ON DELETE CASCADE;


--
-- Name: promo_code_redemptions promo_code_redemptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promo_code_redemptions
    ADD CONSTRAINT promo_code_redemptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: quests quests_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quests
    ADD CONSTRAINT quests_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: quests quests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quests
    ADD CONSTRAINT quests_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: session_plans session_plans_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_plans
    ADD CONSTRAINT session_plans_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: session_plans session_plans_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_plans
    ADD CONSTRAINT session_plans_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: shorthand_terms shorthand_terms_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shorthand_terms
    ADD CONSTRAINT shorthand_terms_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: shorthand_terms shorthand_terms_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shorthand_terms
    ADD CONSTRAINT shorthand_terms_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: source_chunks source_chunks_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_chunks
    ADD CONSTRAINT source_chunks_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: source_chunks source_chunks_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_chunks
    ADD CONSTRAINT source_chunks_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.source_documents(id) ON DELETE CASCADE;


--
-- Name: source_chunks source_chunks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_chunks
    ADD CONSTRAINT source_chunks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: source_documents source_documents_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: source_documents source_documents_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: subscriptions subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: tag_categories tag_categories_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_categories
    ADD CONSTRAINT tag_categories_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: tag_categories tag_categories_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_categories
    ADD CONSTRAINT tag_categories_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: tags tags_custom_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_custom_category_id_fkey FOREIGN KEY (custom_category_id) REFERENCES public.tag_categories(id) ON DELETE CASCADE;


--
-- Name: user_settings user_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--
