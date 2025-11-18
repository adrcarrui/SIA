--
-- PostgreSQL database dump
--

\restrict wERFGw6j8zhkM2blWlVLtP6f8k5kdrNUg9CnRA2tMdhmajala4Vn9MYbRpuF5Fv

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: device_status; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.device_status AS ENUM (
    'assigned',
    'available',
    'lost',
    'annulled'
);


ALTER TYPE public.device_status OWNER TO postgres;

--
-- Name: device_type; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.device_type AS ENUM (
    'vending',
    'canteen',
    'instructor',
    'guest'
);


ALTER TYPE public.device_type OWNER TO postgres;

--
-- Name: user_type; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.user_type AS ENUM (
    'vending',
    'canteen',
    'instructor',
    'guest'
);


ALTER TYPE public.user_type OWNER TO postgres;

--
-- Name: set_course_status(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.set_course_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.start_date IS NULL OR NEW.end_date IS NULL THEN
    NEW.status := 'planned';  -- o lo que prefieras como fallback
  ELSIF CURRENT_DATE < NEW.start_date THEN
    NEW.status := 'planned';
  ELSIF CURRENT_DATE > NEW.end_date THEN
    NEW.status := 'finished';
  ELSE
    NEW.status := 'active';
  END IF;
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.set_course_status() OWNER TO postgres;

--
-- Name: set_update_at(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.set_update_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.update_at := now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.set_update_at() OWNER TO postgres;

--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.set_updated_at() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: assignments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.assignments (
    id integer NOT NULL,
    device_id integer NOT NULL,
    course_id integer NOT NULL,
    assigned_at timestamp with time zone DEFAULT now() NOT NULL,
    released_at timestamp with time zone,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_by integer,
    notes character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_assign_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'closed'::character varying, 'expired'::character varying, 'forced_return'::character varying])::text[])))
);


ALTER TABLE public.assignments OWNER TO postgres;

--
-- Name: assign_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.assign_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.assign_id_seq OWNER TO postgres;

--
-- Name: assign_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.assign_id_seq OWNED BY public.assignments.id;


--
-- Name: courses; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.courses (
    id integer NOT NULL,
    course character varying(150) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status character varying(20) DEFAULT 'planned'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    notes character varying(255),
    trainees integer NOT NULL,
    name character varying(255),
    CONSTRAINT chk_courses_status CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, 'active'::character varying, 'finished'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT courses_dates_check CHECK (((start_date IS NULL) OR (end_date IS NULL) OR (start_date <= end_date)))
);


ALTER TABLE public.courses OWNER TO postgres;

--
-- Name: courses_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.courses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.courses_id_seq OWNER TO postgres;

--
-- Name: courses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.courses_id_seq OWNED BY public.courses.id;


--
-- Name: devices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.devices (
    id integer NOT NULL,
    uid character varying(64) NOT NULL,
    name character varying(100),
    type character varying(50) DEFAULT 'guest'::character varying NOT NULL,
    status character varying(30) DEFAULT 'available'::character varying NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    notes character varying(255),
    CONSTRAINT chk_devices_status CHECK (((status)::text = ANY ((ARRAY['assigned'::character varying, 'available'::character varying, 'lost'::character varying, 'annulled'::character varying])::text[])))
);


ALTER TABLE public.devices OWNER TO postgres;

--
-- Name: devices_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.devices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.devices_id_seq OWNER TO postgres;

--
-- Name: devices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.devices_id_seq OWNED BY public.devices.id;


--
-- Name: movements; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.movements (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id integer,
    action character varying(20) NOT NULL,
    before_data jsonb,
    after_data jsonb,
    success boolean DEFAULT true NOT NULL,
    description text,
    user_agent text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_movements_action CHECK (((action)::text = ANY ((ARRAY['create'::character varying, 'update'::character varying, 'delete'::character varying, 'assign'::character varying])::text[]))),
    CONSTRAINT chk_movements_entity_type CHECK (((entity_type)::text = ANY ((ARRAY['user'::character varying, 'device'::character varying, 'course'::character varying])::text[])))
);


ALTER TABLE public.movements OWNER TO postgres;

--
-- Name: movements_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.movements_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.movements_id_seq OWNER TO postgres;

--
-- Name: movements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.movements_id_seq OWNED BY public.movements.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    surname character varying(100),
    uid character varying(60),
    username character varying(100),
    password_hash text,
    email character varying(255),
    role character varying(50) DEFAULT 'user'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    update_at timestamp with time zone DEFAULT now() NOT NULL,
    active boolean DEFAULT true NOT NULL
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: assignments id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.assignments ALTER COLUMN id SET DEFAULT nextval('public.assign_id_seq'::regclass);


--
-- Name: courses id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.courses ALTER COLUMN id SET DEFAULT nextval('public.courses_id_seq'::regclass);


--
-- Name: devices id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.devices ALTER COLUMN id SET DEFAULT nextval('public.devices_id_seq'::regclass);


--
-- Name: movements id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.movements ALTER COLUMN id SET DEFAULT nextval('public.movements_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Data for Name: assignments; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.assignments (id, device_id, course_id, assigned_at, released_at, status, created_by, notes, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: courses; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.courses (id, course, start_date, end_date, status, created_at, updated_at, notes, trainees, name) FROM stdin;
5	ANC2352	2025-11-04	2025-11-07	active	2025-11-05 10:11:55.715656+01	2025-11-07 12:37:12.024579+01	\N	3	\N
3	TNC1799	2025-11-11	2025-11-17	active	2025-11-05 10:00:52.699339+01	2025-11-11 10:06:55.516353+01	\N	2	\N
2	ANC2330	2025-11-04	2025-11-14	active	2025-11-05 10:00:52.699339+01	2025-11-11 11:35:23.149979+01	None	7	None
6	TNC2525	2025-11-02	2025-11-11	planned	2025-11-05 10:21:45.05127+01	2025-11-12 13:21:23.811755+01	None	4	None
1	NC5453	2025-11-14	2025-11-18	planned	2025-11-05 10:00:52.699339+01	2025-11-13 07:27:26.045419+01	None	6	None
23	course_placeholder	2025-11-14	2025-11-18	planned	2025-11-13 09:44:34.052408+01	2025-11-13 09:44:53.686428+01		5	course_placeholder
24	123	2025-11-17	2025-11-21	cancelled	2025-11-13 10:10:38.354268+01	2025-11-13 10:11:10.955181+01		3	123
\.


--
-- Data for Name: devices; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.devices (id, uid, name, type, status, active, created_at, updated_at, notes) FROM stdin;
2	001	vending2	vending	annulled	f	2025-11-07 12:40:56.218792+01	2025-11-13 09:05:22.90176+01	None
5	device_placeholder	device_placeholder	guest	available	f	2025-11-13 08:33:57.06282+01	2025-11-17 07:32:13.598806+01	None
9	3CF572C2	50	canteen	available	f	2025-11-18 08:30:18.653151+01	2025-11-18 09:30:18.644768+01	\N
\.


--
-- Data for Name: movements; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.movements (id, user_id, entity_type, entity_id, action, before_data, after_data, success, description, user_agent, created_at) FROM stdin;
1	20	user	28	create	null	{"id": 28, "role": "User", "email": null, "active": true, "username": "user1"}	t	User 'user1' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-17 09:41:09.291566+01
13	20	user	28	update	{"id": 28, "uid": null, "role": "User", "email": null, "active": true, "username": "user1"}	{"id": 28, "uid": null, "role": "User", "email": "None@gmail.com", "active": true, "username": "user1"}	t	User 'user1' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-17 10:52:37.691591+01
15	20	user	28	delete	{"id": 28, "role": "User", "email": "None@gmail.com", "active": true, "username": "user1"}	null	t	User 'user1' deleted	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-17 10:55:48.606512+01
16	20	device	8	create	null	{"id": 8, "uid": "11111", "name": "device1", "type": "guest", "notes": null, "active": false, "status": "available"}	t	Device 'device1' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 06:20:21.941774+01
17	20	device	8	update	{"id": 8, "uid": "11111", "name": "device1", "type": "guest", "notes": null, "active": false, "status": "available"}	{"id": 8, "uid": "11111", "name": "device11", "type": "guest", "notes": "None", "active": false, "status": "available"}	t	Device 'device11' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 06:34:36.556401+01
18	20	device	8	delete	{"id": 8, "uid": "11111", "name": "device11", "type": "guest", "notes": "None", "active": false, "status": "available"}	null	t	Device 'device11' deleted	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 06:35:40.330649+01
19	20	course	27	create	null	{"id": 27, "name": null, "notes": null, "course": "curso", "status": "planned", "end_date": "2025-11-21", "trainees": 1, "start_date": "2025-11-20"}	t	Course 'curso' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 06:48:16.85808+01
20	20	course	27	update	{"id": 27, "name": null, "notes": null, "course": "curso", "status": "planned", "end_date": "2025-11-21", "trainees": 1, "start_date": "2025-11-20"}	{"id": 27, "name": "None", "notes": "None", "course": "curso", "status": "planned", "end_date": "2025-11-21", "trainees": 1, "start_date": "2025-11-18"}	t	Course 'curso' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 06:57:08.361788+01
21	20	course	27	delete	{"id": 27, "name": "None", "notes": "None", "course": "curso", "status": "active", "end_date": "2025-11-21", "trainees": 1, "start_date": "2025-11-18"}	null	t	Course 'curso' deleted	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 06:58:29.607581+01
22	20	device	9	create	null	{"id": 9, "uid": "3CF572C2", "name": "50", "type": "canteen", "notes": null, "active": false, "status": "available"}	t	Device '50' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 08:30:18.653151+01
23	20	user	29	create	null	{"id": 29, "role": "User", "email": "ivan.naranjo@atexis.com", "active": true, "username": "inaranjo"}	t	User 'inaranjo' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-18 09:03:53.353386+01
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (id, name, surname, uid, username, password_hash, email, role, created_at, update_at, active) FROM stdin;
4	name1	surname1	uid1	username1	$2b$12$T9dzVMtxxTDDC41gsv2Utet3U.7ezBUsWNIDbtJM8foAivT2xA6cm	email1@gmail.com	Student	2025-11-05 20:45:46.392074+01	2025-11-05 20:46:19.79113+01	t
9	rivera	rivera	163804A3E0373D	rivera	$2b$12$av0cOkjIW7lkDnlsA8w9.OlC1HQXiEhBSe5Cm4Z3m4s9eDosK5cgi	rivera@atexis.com	Student	2025-11-13 07:58:12.962504+01	2025-11-13 07:58:12.962504+01	t
20	admin		\N	admin	$2b$12$yChXcHrsZGN30t.n..7ty.xg.Hlh5BFwJjjmB5G6rhKMZH/lRyPIa	\N	User	2025-11-13 09:29:49.263091+01	2025-11-13 09:29:49.263091+01	t
21	user_placeholder		\N	user_placeholder	$2b$12$PHC1OJR2gZBM5A7KldQpHOEavQ6/dPbhavTZnX/CORNsoCoaE7ZES	\N	User	2025-11-13 09:33:44.675873+01	2025-11-13 09:33:44.675873+01	t
22	Mitchell		16380409EA373D	mit	$2b$12$hpvRkTr5w6bEgXilAvbwfu16TtEaGr.52mxvKTt7FvDWtWRiXH5N.	\N	User	2025-11-13 10:07:56.736985+01	2025-11-13 10:07:56.736985+01	t
1	Adrian	Cardona Ruiz	16380CF382023C	acardona	$2b$12$9HIoa9ZIV2biwxxuTX7aluzzC9S7QZhEOc37rcLA84sMgdGlkHMfq	adrian.cardonaruiz@atexis.com	admin	2025-11-05 20:23:20.803042+01	2025-11-13 10:08:25.452452+01	f
10	user		None	username	$2b$12$7nNIQOU/noi/y4crTBXxD.kRwL0eSza3BVL2nw9mhg5srd1JFqbLy	\N	user	2025-11-13 08:02:26.957609+01	2025-11-13 10:18:58.385149+01	t
29	Iván	Naranjo López	163804470BF83D	inaranjo	$2b$12$Vifq.1l6FCIA9Twd4yVMF.aC9HY71GCTn/LSAPWVXKAxTH4Kxm4f.	ivan.naranjo@atexis.com	User	2025-11-18 10:03:53.356164+01	2025-11-18 10:03:53.356164+01	t
\.


--
-- Name: assign_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.assign_id_seq', 1, false);


--
-- Name: courses_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.courses_id_seq', 27, true);


--
-- Name: devices_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.devices_id_seq', 9, true);


--
-- Name: movements_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.movements_id_seq', 23, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.users_id_seq', 29, true);


--
-- Name: assignments assign_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assign_pkey PRIMARY KEY (id);


--
-- Name: courses courses_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.courses
    ADD CONSTRAINT courses_pkey PRIMARY KEY (id);


--
-- Name: devices devices_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_pkey PRIMARY KEY (id);


--
-- Name: devices devices_uid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_uid_key UNIQUE (uid);


--
-- Name: movements movements_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.movements
    ADD CONSTRAINT movements_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_uid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_uid_key UNIQUE (uid);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: idx_assign_course; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_assign_course ON public.assignments USING btree (course_id);


--
-- Name: idx_assign_device_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_assign_device_active ON public.assignments USING btree (device_id, released_at, status);


--
-- Name: idx_assign_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_assign_status ON public.assignments USING btree (status);


--
-- Name: idx_courses_dates; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_courses_dates ON public.courses USING btree (start_date, end_date);


--
-- Name: idx_courses_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_courses_status ON public.courses USING btree (status);


--
-- Name: idx_devices_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devices_active ON public.devices USING btree (active);


--
-- Name: idx_devices_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devices_status ON public.devices USING btree (status);


--
-- Name: idx_movements_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_movements_created_at ON public.movements USING btree (created_at DESC);


--
-- Name: idx_movements_entity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_movements_entity ON public.movements USING btree (entity_type, entity_id, created_at DESC);


--
-- Name: idx_movements_user_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_movements_user_created_at ON public.movements USING btree (user_id, created_at DESC);


--
-- Name: assignments trg_assign_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_assign_updated BEFORE UPDATE ON public.assignments FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: courses trg_courses_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_courses_updated BEFORE UPDATE ON public.courses FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: devices trg_devices_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_devices_updated BEFORE UPDATE ON public.devices FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: courses trg_set_course_status_ins; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_set_course_status_ins BEFORE INSERT ON public.courses FOR EACH ROW EXECUTE FUNCTION public.set_course_status();


--
-- Name: courses trg_set_course_status_upd; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_set_course_status_upd BEFORE UPDATE OF start_date, end_date ON public.courses FOR EACH ROW EXECUTE FUNCTION public.set_course_status();


--
-- Name: users trg_users_update_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_users_update_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.set_update_at();


--
-- Name: assignments assign_course_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assign_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.courses(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: assignments assign_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assign_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: movements fk_movements_user; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.movements
    ADD CONSTRAINT fk_movements_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: movements movements_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.movements
    ADD CONSTRAINT movements_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict wERFGw6j8zhkM2blWlVLtP6f8k5kdrNUg9CnRA2tMdhmajala4Vn9MYbRpuF5Fv

