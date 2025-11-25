--
-- PostgreSQL database dump
--

\restrict dyUGyb2eBZEB8Kcu9ZlWmkF5g6RoX1Dv3VucxwKXBAGnkaRUUgZKq9qbO4w3tRt

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
    CONSTRAINT chk_assign_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'overdue_1'::character varying, 'overdue_2'::character varying])::text[])))
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
    course character varying(150),
    start_date date NOT NULL,
    end_date date NOT NULL,
    status character varying(20) DEFAULT 'planned'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    notes character varying(255),
    trainees integer NOT NULL,
    name character varying(255),
    client character varying(255),
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
    CONSTRAINT chk_movements_action CHECK (((action)::text = ANY ((ARRAY['create'::character varying, 'update'::character varying, 'delete'::character varying, 'assign'::character varying, 'return'::character varying])::text[])))
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
23	11	23	2025-11-25 07:28:45.972743+01	\N	active	20	\N	2025-11-25 07:28:45.972743+01	2025-11-25 07:28:45.972743+01
\.


--
-- Data for Name: courses; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.courses (id, course, start_date, end_date, status, created_at, updated_at, notes, trainees, name, client) FROM stdin;
29	None	2025-11-18	2025-11-19	finished	2025-11-19 08:45:52.125742+01	2025-11-24 14:58:41.003007+01	None	0	Instructor	\N
5	ANC2352	2025-11-04	2025-11-07	active	2025-11-05 10:11:55.715656+01	2025-11-07 12:37:12.024579+01	\N	3	\N	\N
23	course_placeholder	2025-11-01	2025-11-24	finished	2025-11-13 09:44:34.052408+01	2025-11-25 10:00:40.570958+01	None	5	course_placeholder	\N
3	TNC1799	2025-11-11	2025-11-17	active	2025-11-05 10:00:52.699339+01	2025-11-11 10:06:55.516353+01	\N	2	\N	\N
2	ANC2330	2025-11-04	2025-11-14	active	2025-11-05 10:00:52.699339+01	2025-11-11 11:35:23.149979+01	None	7	None	\N
6	TNC2525	2025-11-02	2025-11-11	planned	2025-11-05 10:21:45.05127+01	2025-11-12 13:21:23.811755+01	None	4	None	\N
1	NC5453	2025-11-14	2025-11-18	planned	2025-11-05 10:00:52.699339+01	2025-11-13 07:27:26.045419+01	None	6	None	\N
24	123	2025-11-17	2025-11-21	cancelled	2025-11-13 10:10:38.354268+01	2025-11-19 08:52:44.82433+01	\N	3	123	\N
\.


--
-- Data for Name: devices; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.devices (id, uid, name, type, status, active, created_at, updated_at, notes) FROM stdin;
11	BCA670F5	47	guest	available	f	2025-11-19 09:07:43.806717+01	2025-11-24 20:58:06.03305+01	None
5	device_placeholder	device_placeholder	guest	assigned	f	2025-11-13 08:33:57.06282+01	2025-11-25 11:43:04.030643+01	None
9	3CF572C2	50	canteen	available	f	2025-11-18 08:30:18.653151+01	2025-11-25 12:26:42.244499+01	None
10	8888	dev	guest	available	f	2025-11-18 10:10:45.07014+01	2025-11-18 11:10:45.06712+01	\N
2	001	vending2	vending	available	f	2025-11-07 12:40:56.218792+01	2025-11-19 10:30:50.547343+01	None
\.


--
-- Data for Name: movements; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.movements (id, user_id, entity_type, entity_id, action, before_data, after_data, success, description, user_agent, created_at) FROM stdin;
54	1	device	11	return	{"assignment": {"id": 15, "status": "active", "course_id": 23, "device_id": 11, "assigned_at": "2025-11-20T05:41:35.078107+01:00"}, "device_status": "assigned"}	{"assignment": null, "device_status": "available"}	t	Assignment return: device 11 -> course 23	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 08:01:22.281283+01
55	1	device	9	update	{"id": 9, "uid": "3CF572C2", "name": "50", "type": "canteen", "notes": "None", "active": false, "status": "assigned"}	{"id": 9, "uid": "3CF572C2", "name": "50", "type": "canteen", "notes": "None", "active": false, "status": "available"}	t	Device '50' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 08:01:52.233034+01
56	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-26", "trainees": 5, "start_date": "2025-11-19"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-18", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:00:29.887794+01
57	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-18", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:01:50.056041+01
58	1	device	11	assign	{"device_status": "available"}	{"assigned_at": "2025-11-20T09:02:43.937362", "device_status": "assigned", "assignment_status": "active"}	t	Assignment assign: device 11 -> course 23	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:02:43.937362+01
59	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:03:02.354381+01
60	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:15:04.405253+01
61	1	device	11	update	{"id": 11, "uid": "BCA670F5", "name": "47", "type": "guest", "notes": "None", "active": false, "status": "assigned"}	{"id": 11, "uid": "BCA670F5", "name": "47", "type": "guest", "notes": "None", "active": false, "status": "available"}	t	Device '47' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:15:23.936806+01
62	1	device	11	assign	{"device_status": "available"}	{"assigned_at": "2025-11-20T09:15:32.937835", "device_status": "assigned", "assignment_status": "active"}	t	Assignment assign: device 11 -> course 23	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:15:32.937835+01
63	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:15:50.45257+01
64	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-13", "trainees": 5, "start_date": "2025-11-10"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:19:23.737163+01
65	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-13", "trainees": 5, "start_date": "2025-11-10"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:20:41.986496+01
66	1	device	11	update	{"id": 11, "uid": "BCA670F5", "name": "47", "type": "guest", "notes": "None", "active": false, "status": "assigned"}	{"id": 11, "uid": "BCA670F5", "name": "47", "type": "guest", "notes": "None", "active": false, "status": "available"}	t	Device '47' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:33:44.890579+01
67	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:34:02.354332+01
68	1	device	11	assign	{"device_status": "available"}	{"assigned_at": "2025-11-20T09:34:13.108326", "device_status": "assigned", "assignment_status": "active"}	t	Assignment assign: device 11 -> course 23	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:34:13.111503+01
69	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-18", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:34:32.488181+01
70	1	device	9	assign	{"device_status": "available"}	{"assigned_at": "2025-11-20T09:35:48.488977", "device_status": "assigned", "assignment_status": "active"}	t	Assignment assign: device 9 -> course 29	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:35:48.509174+01
71	1	course	29	update	{"id": 29, "name": "Instructor", "notes": null, "course": null, "status": "planned", "end_date": "2025-11-21", "trainees": 0, "start_date": "2025-11-20"}	{"id": 29, "name": "Instructor", "notes": "None", "course": "None", "status": "planned", "end_date": "2025-11-19", "trainees": 0, "start_date": "2025-11-18"}	t	Course 'None' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:36:02.338272+01
72	1	device	11	update	{"id": 11, "uid": "BCA670F5", "name": "47", "type": "guest", "notes": "None", "active": false, "status": "assigned"}	{"id": 11, "uid": "BCA670F5", "name": "47", "type": "guest", "notes": "None", "active": false, "status": "available"}	t	Device '47' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:38:29.321366+01
73	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-18", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:38:59.971072+01
74	1	device	11	assign	{"device_status": "available"}	{"assigned_at": "2025-11-20T09:39:23.788036", "device_status": "assigned", "assignment_status": "active"}	t	Assignment assign: device 11 -> course 23	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:39:23.802349+01
75	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-21", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:39:57.920432+01
76	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-22", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:41:05.937289+01
77	1	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-22", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-20 09:41:13.503846+01
78	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-19", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-26", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 07:21:36.037398+01
79	20	course	29	update	{"id": 29, "name": "Instructor", "notes": "None", "course": "None", "status": "finished", "end_date": "2025-11-19", "trainees": 0, "start_date": "2025-11-18"}	{"id": 29, "name": "Instructor", "notes": "None", "course": "None", "status": "finished", "end_date": "2025-11-25", "trainees": 0, "start_date": "2025-11-18"}	t	Course 'None' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 13:54:08.893309+01
80	20	course	29	update	{"id": 29, "name": "Instructor", "notes": "None", "course": "None", "status": "active", "end_date": "2025-11-25", "trainees": 0, "start_date": "2025-11-18"}	{"id": 29, "name": "Instructor", "notes": "None", "course": "None", "status": "active", "end_date": "2025-11-19", "trainees": 0, "start_date": "2025-11-18"}	t	Course 'None' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 13:58:41.005715+01
85	20	Assignment	20	return	{"id": 20, "course_id": 29, "device_id": 9, "assigned_at": "2025-11-20T09:35:48.488977+01:00", "released_at": null}	{"id": 20, "course_id": 29, "device_id": 9, "assigned_at": "2025-11-20T09:35:48.488977+01:00", "released_at": "2025-11-24T14:35:27.258776"}	t	Assignment 20 returned for device 9 in course 29	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 14:35:27.264792+01
86	20	Assignment	21	return	{"id": 21, "course_id": 23, "device_id": 11, "assigned_at": "2025-11-20T09:39:23.788036+01:00", "released_at": null}	{"id": 21, "course_id": 23, "device_id": 11, "assigned_at": "2025-11-20T09:39:23.788036+01:00", "released_at": "2025-11-24T14:35:27.258776"}	t	Assignment 21 returned for device 11 in course 23	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 14:35:27.264792+01
87	20	Assignment	20	return	{"id": 20, "course_id": 29, "device_id": 9, "assigned_at": "2025-11-20T09:35:48.488977+01:00", "released_at": "2025-11-24T14:35:27.258776+01:00"}	{"id": 20, "course_id": 29, "device_id": 9, "assigned_at": "2025-11-20T09:35:48.488977+01:00", "released_at": "2025-11-24T19:58:06.037031"}	t	Card '50' returned.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 19:58:06.07488+01
88	20	Device	9	update	{"id": 9, "uid": "3CF572C2", "name": "50", "status": "assigned"}	{"id": 9, "uid": "3CF572C2", "name": "50", "status": "available"}	t	Device '50' set to available on return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 19:58:06.07488+01
89	20	Assignment	21	return	{"id": 21, "course_id": 23, "device_id": 11, "assigned_at": "2025-11-20T09:39:23.788036+01:00", "released_at": "2025-11-24T14:35:27.258776+01:00"}	{"id": 21, "course_id": 23, "device_id": 11, "assigned_at": "2025-11-20T09:39:23.788036+01:00", "released_at": "2025-11-24T19:58:06.040879"}	t	Card '47' returned.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 19:58:06.07488+01
90	20	Device	11	update	{"id": 11, "uid": "BCA670F5", "name": "47", "status": "assigned"}	{"id": 11, "uid": "BCA670F5", "name": "47", "status": "available"}	t	Device '47' set to available on return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 19:58:06.07488+01
91	20	Assignment	21	delete	{"id": 21, "course_id": 23, "device_id": 11, "assigned_at": "2025-11-20T09:39:23.788036+01:00", "released_at": "2025-11-24T19:58:06.040879+01:00"}	null	t	Assignment for device '47' deleted on bulk return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 20:00:45.731096+01
92	20	Device	11	update	{"id": 11, "uid": "BCA670F5", "name": "47", "status": "available"}	{"id": 11, "uid": "BCA670F5", "name": "47", "status": "available"}	t	Device '47' set to available on bulk return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 20:00:45.731096+01
93	20	Assignment	20	delete	{"id": 20, "course_id": 29, "device_id": 9, "assigned_at": "2025-11-20T09:35:48.488977+01:00", "released_at": "2025-11-24T19:58:06.037031+01:00"}	null	t	Assignment for device '50' deleted on bulk return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 20:01:07.428252+01
94	20	Device	9	update	{"id": 9, "uid": "3CF572C2", "name": "50", "status": "available"}	{"id": 9, "uid": "3CF572C2", "name": "50", "status": "available"}	t	Device '50' set to available on bulk return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-24 20:01:07.428252+01
95	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-26", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-20", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 06:45:41.601329+01
96	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-20", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-25", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 06:45:53.319075+01
97	20	device	9	assign	{"device_status": "available"}	{"assigned_at": "2025-11-25T06:46:13.219402", "device_status": "assigned", "assignment_status": "active"}	t	Assignment assign: device 9 -> course 23	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 06:46:13.23647+01
98	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-25", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-18", "trainees": 5, "start_date": "2025-11-17"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 06:46:31.487723+01
99	20	Assignment	22	delete	{"id": 22, "course_id": 23, "device_id": 9, "assigned_at": "2025-11-25T06:46:13.219402+01:00", "released_at": null}	null	t	Assignment for device '50' deleted on bulk return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 06:47:17.807108+01
100	20	Device	9	update	{"id": 9, "uid": "3CF572C2", "name": "50", "status": "assigned"}	{"id": 9, "uid": "3CF572C2", "name": "50", "status": "available"}	t	Device '50' set to available on bulk return.	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 06:47:17.807108+01
101	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-18", "trainees": 5, "start_date": "2025-11-17"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-14", "trainees": 5, "start_date": "2025-11-01"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 07:42:00.123627+01
102	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-14", "trainees": 5, "start_date": "2025-11-01"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-15", "trainees": 5, "start_date": "2025-11-01"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 07:43:05.123539+01
103	20	device	12	create	null	{"id": 12, "uid": "11111", "name": "name", "type": "guest", "notes": null, "active": false, "status": "available"}	t	Device 'name' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:02:57.122946+01
104	20	device	12	delete	{"id": 12, "uid": "11111", "name": "name", "type": "guest", "notes": null, "active": false, "status": "available"}	null	t	Device 'name' deleted	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:03:00.097974+01
105	20	user	30	create	null	{"id": 30, "role": "User", "email": null, "active": true, "username": "ad"}	t	User 'ad' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:07:48.196749+01
106	20	user	30	update	{"id": 30, "uid": null, "role": "User", "email": null, "active": true, "username": "ad"}	{"id": 30, "uid": null, "role": "User", "email": "None", "active": true, "username": "ad"}	t	User 'ad' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:12:25.935516+01
107	20	user	30	delete	{"id": 30, "role": "User", "email": "None", "active": true, "username": "ad"}	null	t	User 'ad' deleted	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:12:56.538245+01
108	20	user	10	update	{"id": 10, "uid": "None", "role": "user", "email": null, "active": true, "username": "username"}	{"id": 10, "uid": null, "role": "User", "email": "None", "active": true, "username": "username"}	t	User 'username' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:14:03.302964+01
109	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-15", "trainees": 5, "start_date": "2025-11-01"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "finished", "end_date": "2025-11-29", "trainees": 5, "start_date": "2025-11-01"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:14:29.538609+01
110	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-29", "trainees": 5, "start_date": "2025-11-01"}	{"id": 23, "name": "course_placeholder", "notes": "Anotacion de prueba", "course": "course_placeholder", "status": "active", "end_date": "2025-11-29", "trainees": 5, "start_date": "2025-11-01"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:46:08.115261+01
111	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": "Anotacion de prueba", "course": "course_placeholder", "status": "active", "end_date": "2025-11-29", "trainees": 5, "start_date": "2025-11-01"}	{"id": 23, "name": "course_placeholder", "notes": null, "course": "course_placeholder", "status": "active", "end_date": "2025-11-29", "trainees": 5, "start_date": "2025-11-01"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 08:47:04.599196+01
112	20	course	23	update	{"id": 23, "name": "course_placeholder", "notes": null, "course": "course_placeholder", "status": "active", "end_date": "2025-11-29", "trainees": 5, "start_date": "2025-11-01"}	{"id": 23, "name": "course_placeholder", "notes": "None", "course": "course_placeholder", "status": "active", "end_date": "2025-11-24", "trainees": 5, "start_date": "2025-11-01"}	t	Course 'course_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 09:00:40.580391+01
113	20	device	5	update	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "available"}	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "assigned"}	t	Device 'device_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 10:39:39.896365+01
114	20	device	5	update	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "assigned"}	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "lost"}	t	Device 'device_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 10:39:51.545392+01
115	20	device	5	update	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "lost"}	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "annulled"}	t	Device 'device_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 10:39:57.812977+01
116	20	device	5	update	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "annulled"}	{"id": 5, "uid": "device_placeholder", "name": "device_placeholder", "type": "guest", "notes": "None", "active": false, "status": "assigned"}	t	Device 'device_placeholder' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 10:43:04.029532+01
117	20	user	31	create	null	{"id": 31, "role": "User", "email": null, "active": true, "username": "ad"}	t	User 'ad' created	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:16:57.431494+01
118	20	course	6	update	{"id": 6, "name": "None", "notes": "None", "course": "TNC2525", "status": "planned", "end_date": "2025-11-11", "trainees": 4, "start_date": "2025-11-02"}	{"id": 6, "name": "None", "notes": "None", "course": "TNC2525", "status": "planned", "end_date": "2025-11-11", "trainees": 4, "start_date": "2025-11-02"}	t	Course 'TNC2525' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:20:14.199507+01
119	20	user	9	update	{"id": 9, "uid": "163804A3E0373D", "role": "Student", "email": "rivera@atexis.com", "active": true, "username": "rivera"}	{"id": 9, "uid": null, "role": "Student", "email": "rivera@atexis.com", "active": true, "username": "rivera"}	t	User 'rivera' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:23:06.847534+01
120	20	user	9	update	{"id": 9, "uid": null, "role": "Student", "email": "rivera@atexis.com", "active": true, "username": "rivera"}	{"id": 9, "uid": null, "role": "Student", "email": "rivera@atexis.com", "active": true, "username": "rivera"}	t	User 'rivera' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:23:14.525205+01
121	20	device	9	update	{"id": 9, "uid": "3CF572C2", "name": "50", "type": "canteen", "notes": "None", "active": false, "status": "available"}	{"id": 9, "uid": "3CF572C2", "name": "50", "type": "canteen", "notes": "None", "active": false, "status": "available"}	t	Device '50' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:23:26.5995+01
122	20	course	6	update	{"id": 6, "name": "None", "notes": "None", "course": "TNC2525", "status": "planned", "end_date": "2025-11-11", "trainees": 4, "start_date": "2025-11-02"}	{"id": 6, "name": "None", "notes": "None", "course": "TNC2525", "status": "planned", "end_date": "2025-11-11", "trainees": 4, "start_date": "2025-11-02"}	t	Course 'TNC2525' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:23:30.69856+01
123	20	device	9	update	{"id": 9, "uid": "3CF572C2", "name": "50", "type": "canteen", "notes": "None", "active": false, "status": "available"}	{"id": 9, "uid": "3CF572C2", "name": "50", "type": "canteen", "notes": "None", "active": false, "status": "available"}	t	Device '50' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:26:42.24713+01
124	20	user	20	update	{"id": 20, "uid": null, "role": "User", "email": null, "active": true, "username": "admin"}	{"id": 20, "uid": null, "role": "User", "email": "Non", "active": true, "username": "admin"}	t	User 'admin' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:27:04.761815+01
125	20	user	10	update	{"id": 10, "uid": null, "role": "User", "email": "None", "active": true, "username": "username"}	{"id": 10, "uid": null, "role": "User", "email": null, "active": true, "username": "username"}	t	User 'username' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:27:20.66679+01
126	20	user	10	update	{"id": 10, "uid": null, "role": "User", "email": null, "active": true, "username": "username"}	{"id": 10, "uid": null, "role": "User", "email": "None", "active": true, "username": "username"}	t	User 'username' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:27:23.666022+01
127	20	user	10	update	{"id": 10, "uid": null, "role": "User", "email": "None", "active": true, "username": "username"}	{"id": 10, "uid": null, "role": "User", "email": null, "active": true, "username": "username"}	t	User 'username' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:27:27.682313+01
128	20	user	10	update	{"id": 10, "uid": null, "role": "User", "email": null, "active": true, "username": "username"}	{"id": 10, "uid": null, "role": "User", "email": null, "active": true, "username": "username"}	t	User 'username' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:27:30.728634+01
129	20	user	20	update	{"id": 20, "uid": null, "role": "User", "email": "Non", "active": true, "username": "admin"}	{"id": 20, "uid": null, "role": "User", "email": null, "active": true, "username": "admin"}	t	User 'admin' updated	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36	2025-11-25 11:27:35.466879+01
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (id, name, surname, uid, username, password_hash, email, role, created_at, update_at, active) FROM stdin;
4	name1	surname1	uid1	username1	$2b$12$T9dzVMtxxTDDC41gsv2Utet3U.7ezBUsWNIDbtJM8foAivT2xA6cm	email1@gmail.com	Student	2025-11-05 20:45:46.392074+01	2025-11-05 20:46:19.79113+01	t
10	user		\N	username	$2b$12$7nNIQOU/noi/y4crTBXxD.kRwL0eSza3BVL2nw9mhg5srd1JFqbLy	\N	User	2025-11-13 08:02:26.957609+01	2025-11-25 12:27:27.693537+01	t
20	admin		\N	admin	$2b$12$yChXcHrsZGN30t.n..7ty.xg.Hlh5BFwJjjmB5G6rhKMZH/lRyPIa	\N	User	2025-11-13 09:29:49.263091+01	2025-11-25 12:27:35.465006+01	t
21	user_placeholder		\N	user_placeholder	$2b$12$PHC1OJR2gZBM5A7KldQpHOEavQ6/dPbhavTZnX/CORNsoCoaE7ZES	\N	User	2025-11-13 09:33:44.675873+01	2025-11-13 09:33:44.675873+01	t
22	Mitchell		16380409EA373D	mit	$2b$12$hpvRkTr5w6bEgXilAvbwfu16TtEaGr.52mxvKTt7FvDWtWRiXH5N.	\N	User	2025-11-13 10:07:56.736985+01	2025-11-13 10:07:56.736985+01	t
29	Iván	Naranjo López	163804470BF83D	inaranjo	$2b$12$Vifq.1l6FCIA9Twd4yVMF.aC9HY71GCTn/LSAPWVXKAxTH4Kxm4f.	ivan.naranjo@atexis.com	User	2025-11-18 10:03:53.356164+01	2025-11-18 10:03:53.356164+01	t
1	Adrian	Cardona Ruiz	16380CF382023C	acardona	$2b$12$9HIoa9ZIV2biwxxuTX7aluzzC9S7QZhEOc37rcLA84sMgdGlkHMfq	adrian.cardonaruiz@atexis.com	admin	2025-11-05 20:23:20.803042+01	2025-11-18 11:10:19.051662+01	t
31	ad		\N	ad	$2b$12$wU87sYBhSyBYc29sJ25IL.KITwZeXLr8dEuOUScbUB9Q8ecGURqnG	\N	User	2025-11-25 12:16:57.431064+01	2025-11-25 12:16:57.431064+01	t
9	rivera	rivera	\N	rivera	$2b$12$av0cOkjIW7lkDnlsA8w9.OlC1HQXiEhBSe5Cm4Z3m4s9eDosK5cgi	rivera@atexis.com	Student	2025-11-13 07:58:12.962504+01	2025-11-25 12:23:06.843867+01	t
\.


--
-- Name: assign_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.assign_id_seq', 23, true);


--
-- Name: courses_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.courses_id_seq', 29, true);


--
-- Name: devices_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.devices_id_seq', 12, true);


--
-- Name: movements_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.movements_id_seq', 129, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.users_id_seq', 31, true);


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
-- Name: assignments assignments_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assignments_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: movements fk_movements_user; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.movements
    ADD CONSTRAINT fk_movements_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict dyUGyb2eBZEB8Kcu9ZlWmkF5g6RoX1Dv3VucxwKXBAGnkaRUUgZKq9qbO4w3tRt

