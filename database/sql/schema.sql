-- The structure of Drakkar, written by database/scripts/schema.py: never edit it.

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';

CREATE FUNCTION public.constrain_taxon() RETURNS integer
    LANGUAGE sql STRICT SECURITY DEFINER
    AS $$
CREATE RULE rule_taxon_i
       AS ON INSERT TO taxon
       WHERE (
             SELECT taxon_id FROM taxon 
             WHERE ncbi_taxon_id = new.ncbi_taxon_id
             )
       	     IS NOT NULL
       DO INSTEAD NOTHING
;
SELECT 1;
$$;

CREATE FUNCTION public.unconstrain_taxon() RETURNS integer
    LANGUAGE sql STRICT SECURITY DEFINER
    AS $$
DROP RULE rule_taxon_i ON taxon;
SELECT 1;
$$;

CREATE TABLE public.associations (
    id integer NOT NULL,
    run_id integer NOT NULL,
    pmid bigint NOT NULL,
    state character varying(10) DEFAULT 'pending'::character varying NOT NULL,
    annotation text DEFAULT ''::text NOT NULL,
    updated_at timestamp(0) without time zone DEFAULT now() NOT NULL,
    ai_pass_at timestamp without time zone,
    CONSTRAINT associations_state_check CHECK (((state)::text = ANY (ARRAY[('pending'::character varying)::text, ('selected'::character varying)::text, ('discarded'::character varying)::text, ('curated'::character varying)::text])))
);

CREATE SEQUENCE public.associations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.associations_id_seq OWNED BY public.associations.id;

CREATE TABLE public.descriptions_hh (
    stable_id character(10) NOT NULL,
    version smallint NOT NULL,
    association_id integer NOT NULL,
    method_id integer NOT NULL,
    protein1_id integer NOT NULL,
    mapping1 json NOT NULL,
    protein2_id integer NOT NULL,
    mapping2 json NOT NULL,
    created_at timestamp(0) without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp(0) without time zone,
    annotation text DEFAULT ''::text NOT NULL
);

CREATE TABLE public.descriptions_vh (
    stable_id character(10) NOT NULL,
    version smallint NOT NULL,
    association_id integer NOT NULL,
    method_id integer NOT NULL,
    protein1_id integer NOT NULL,
    mapping1 json NOT NULL,
    protein2_id integer NOT NULL,
    name2 character varying(32) NOT NULL,
    start2 integer NOT NULL,
    stop2 integer NOT NULL,
    mapping2 json NOT NULL,
    created_at timestamp(0) without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp(0) without time zone,
    annotation text DEFAULT ''::text NOT NULL
);

CREATE TABLE public.keywords (
    id integer NOT NULL,
    type character(1) NOT NULL,
    pattern character varying(255) NOT NULL
);

CREATE SEQUENCE public.keywords_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.keywords_id_seq OWNED BY public.keywords.id;

CREATE TABLE public.methods (
    id integer NOT NULL,
    psimi_id character varying(7) NOT NULL,
    name character varying(255) NOT NULL,
    search text,
    synonyms character varying[] DEFAULT '{}'::character varying[] NOT NULL,
    is_detection boolean NOT NULL
);

CREATE SEQUENCE public.methods_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.methods_id_seq OWNED BY public.methods.id;

CREATE TABLE public.proteins (
    id integer NOT NULL,
    type character(1) NOT NULL,
    ncbi_taxon_id integer NOT NULL,
    accession character varying(10) NOT NULL,
    name character varying(255) NOT NULL,
    description text NOT NULL,
    version character(7) NOT NULL,
    sequences jsonb NOT NULL,
    CONSTRAINT proteins_type_check CHECK (((type)::text = ANY (ARRAY[('h'::character varying)::text, ('v'::character varying)::text])))
);

CREATE SEQUENCE public.proteins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.proteins_id_seq OWNED BY public.proteins.id;

CREATE TABLE public.proteins_versions (
    accession character varying(10) NOT NULL,
    version character(7) NOT NULL,
    current_version character(7) NOT NULL,
    names character varying[] NOT NULL,
    features jsonb NOT NULL,
    search text,
    reviewed boolean NOT NULL,
    secondary_accessions character varying[] NOT NULL
);

CREATE TABLE public.publications (
    pmid bigint NOT NULL,
    populated boolean DEFAULT false,
    metadata jsonb
);

CREATE TABLE public.runs (
    id integer NOT NULL,
    type character(2) NOT NULL,
    name text NOT NULL,
    populated boolean DEFAULT false NOT NULL,
    created_at timestamp(0) without time zone DEFAULT now() NOT NULL,
    info text DEFAULT ''::text NOT NULL,
    CONSTRAINT runs_type_check CHECK (((type)::text = ANY (ARRAY[('hh'::character varying)::text, ('vh'::character varying)::text])))
);

CREATE SEQUENCE public.runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.runs_id_seq OWNED BY public.runs.id;

CREATE SEQUENCE public.taxon_pk_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE public.taxon (
    taxon_id integer DEFAULT nextval('public.taxon_pk_seq'::regclass) NOT NULL,
    ncbi_taxon_id integer,
    parent_taxon_id integer,
    node_rank character varying(32),
    genetic_code smallint,
    mito_genetic_code smallint,
    left_value integer,
    right_value integer,
    search text
);

CREATE TABLE public.taxon_name (
    taxon_id integer NOT NULL,
    name character varying(255) NOT NULL,
    name_class character varying(32) NOT NULL
);

ALTER TABLE ONLY public.associations ALTER COLUMN id SET DEFAULT nextval('public.associations_id_seq'::regclass);

ALTER TABLE ONLY public.keywords ALTER COLUMN id SET DEFAULT nextval('public.keywords_id_seq'::regclass);

ALTER TABLE ONLY public.methods ALTER COLUMN id SET DEFAULT nextval('public.methods_id_seq'::regclass);

ALTER TABLE ONLY public.proteins ALTER COLUMN id SET DEFAULT nextval('public.proteins_id_seq'::regclass);

ALTER TABLE ONLY public.runs ALTER COLUMN id SET DEFAULT nextval('public.runs_id_seq'::regclass);

ALTER TABLE ONLY public.associations
    ADD CONSTRAINT associations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.associations
    ADD CONSTRAINT associations_run_id_pmid_key UNIQUE (run_id, pmid);

ALTER TABLE ONLY public.descriptions_hh
    ADD CONSTRAINT descriptions_hh_pkey PRIMARY KEY (stable_id, version);

ALTER TABLE ONLY public.descriptions_vh
    ADD CONSTRAINT descriptions_vh_pkey PRIMARY KEY (stable_id, version);

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT keywords_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.methods
    ADD CONSTRAINT methods_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.methods
    ADD CONSTRAINT methods_psimi_id_key UNIQUE (psimi_id);

ALTER TABLE ONLY public.proteins
    ADD CONSTRAINT proteins_accession_version_key UNIQUE (accession, version);

ALTER TABLE ONLY public.proteins
    ADD CONSTRAINT proteins_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.proteins_versions
    ADD CONSTRAINT proteins_versions_accession_current_version_key UNIQUE (accession, current_version);

ALTER TABLE ONLY public.proteins_versions
    ADD CONSTRAINT proteins_versions_pkey PRIMARY KEY (accession, version);

ALTER TABLE ONLY public.publications
    ADD CONSTRAINT publications_pkey PRIMARY KEY (pmid);

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.taxon_name
    ADD CONSTRAINT taxon_name_name_name_class_taxon_id_key UNIQUE (name, name_class, taxon_id);

ALTER TABLE ONLY public.taxon
    ADD CONSTRAINT taxon_pkey PRIMARY KEY (taxon_id);

ALTER TABLE ONLY public.taxon
    ADD CONSTRAINT xaktaxon_left_value UNIQUE (left_value);

ALTER TABLE ONLY public.taxon
    ADD CONSTRAINT xaktaxon_ncbi_taxon_id UNIQUE (ncbi_taxon_id);

ALTER TABLE ONLY public.taxon
    ADD CONSTRAINT xaktaxon_right_value UNIQUE (right_value);

CREATE INDEX descriptions_hh_association_id_key ON public.descriptions_hh USING btree (association_id);

CREATE INDEX descriptions_hh_method_id_key ON public.descriptions_hh USING btree (method_id);

CREATE INDEX descriptions_hh_protein1_id_key ON public.descriptions_hh USING btree (protein1_id);

CREATE INDEX descriptions_hh_protein2_id_key ON public.descriptions_hh USING btree (protein2_id);

CREATE INDEX descriptions_vh_association_id_key ON public.descriptions_vh USING btree (association_id);

CREATE INDEX descriptions_vh_method_id_key ON public.descriptions_vh USING btree (method_id);

CREATE INDEX descriptions_vh_protein1_id_key ON public.descriptions_vh USING btree (protein1_id);

CREATE INDEX descriptions_vh_protein2_id_key ON public.descriptions_vh USING btree (protein2_id);

CREATE INDEX methods_search_key ON public.methods USING gin (search public.gin_trgm_ops);

CREATE INDEX proteins_ncbi_taxon_id_key ON public.proteins USING btree (ncbi_taxon_id);

CREATE INDEX proteins_versions_search_key ON public.proteins_versions USING gin (search public.gin_trgm_ops);

CREATE INDEX proteins_versions_secondary_accessions_key ON public.proteins_versions USING gin (secondary_accessions);

CREATE INDEX taxnamename ON public.taxon_name USING btree (name);

CREATE INDEX taxnametaxonid ON public.taxon_name USING btree (taxon_id);

CREATE INDEX taxon_search_key ON public.taxon USING gin (search public.gin_trgm_ops);

CREATE INDEX taxparent ON public.taxon USING btree (parent_taxon_id);

CREATE RULE rule_taxon_i AS
    ON INSERT TO public.taxon
   WHERE (( SELECT taxon.taxon_id
           FROM public.taxon
          WHERE (taxon.ncbi_taxon_id = new.ncbi_taxon_id)) IS NOT NULL) DO INSTEAD NOTHING;

CREATE RULE rule_taxon_name_i AS
    ON INSERT TO public.taxon_name
   WHERE (( SELECT taxon_name.taxon_id
           FROM public.taxon_name
          WHERE ((taxon_name.taxon_id = new.taxon_id) AND ((taxon_name.name)::text = (new.name)::text) AND ((taxon_name.name_class)::text = (new.name_class)::text))) IS NOT NULL) DO INSTEAD NOTHING;

ALTER TABLE ONLY public.associations
    ADD CONSTRAINT associations_pmid_fkey FOREIGN KEY (pmid) REFERENCES public.publications(pmid);

ALTER TABLE ONLY public.associations
    ADD CONSTRAINT associations_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);

ALTER TABLE ONLY public.descriptions_hh
    ADD CONSTRAINT descriptions_hh_association_id_fkey FOREIGN KEY (association_id) REFERENCES public.associations(id);

ALTER TABLE ONLY public.descriptions_hh
    ADD CONSTRAINT descriptions_hh_method_id_fkey FOREIGN KEY (method_id) REFERENCES public.methods(id);

ALTER TABLE ONLY public.descriptions_hh
    ADD CONSTRAINT descriptions_hh_protein1_id_fkey FOREIGN KEY (protein1_id) REFERENCES public.proteins(id);

ALTER TABLE ONLY public.descriptions_hh
    ADD CONSTRAINT descriptions_hh_protein2_id_fkey FOREIGN KEY (protein2_id) REFERENCES public.proteins(id);

ALTER TABLE ONLY public.descriptions_vh
    ADD CONSTRAINT descriptions_vh_association_id_fkey FOREIGN KEY (association_id) REFERENCES public.associations(id);

ALTER TABLE ONLY public.descriptions_vh
    ADD CONSTRAINT descriptions_vh_method_id_fkey FOREIGN KEY (method_id) REFERENCES public.methods(id);

ALTER TABLE ONLY public.descriptions_vh
    ADD CONSTRAINT descriptions_vh_protein1_id_fkey FOREIGN KEY (protein1_id) REFERENCES public.proteins(id);

ALTER TABLE ONLY public.descriptions_vh
    ADD CONSTRAINT descriptions_vh_protein2_id_fkey FOREIGN KEY (protein2_id) REFERENCES public.proteins(id);

ALTER TABLE ONLY public.taxon_name
    ADD CONSTRAINT fktaxon_taxonname FOREIGN KEY (taxon_id) REFERENCES public.taxon(taxon_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.proteins_versions
    ADD CONSTRAINT proteins_versions_accession_version_fkey FOREIGN KEY (accession, version) REFERENCES public.proteins(accession, version);
