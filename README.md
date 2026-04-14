# NL-to-SQL System

A production-grade Natural Language to SQL pipeline built on top of [Vanna](https://vanna.ai). Ask questions in plain English and get instant, accurate SQL queries executed against a clinic management SQLite database — served through a FastAPI REST API.

**Test results: 19/20 questions answered correctly on the first automated run.**

---

## Table of Contents

- [Project Description](#project-description)
- [Architecture Overview](#architecture-overview)
- [Database Schema](#database-schema)
- [About the Database (Faker-generated)](#about-the-database-faker-generated)
- [Setup Instructions](#setup-instructions)
- [Running the Server](#running-the-server)
- [API Documentation](#api-documentation)
- [Running the Evaluation Script](#running-the-evaluation-script)
- [Project Structure](#project-structure)

---

## Project Description

This system lets users query a clinic database using plain English. It uses:

- **Vanna** as the NL-to-SQL agent framework
- **Groq** (via OpenAI-compatible API) as the LLM backend — model: `openai/gpt-oss-120b`
- **SQLite** (`clinic.db`) as the database
- **FastAPI** to expose a streaming chat REST API
- **Custom SQL validation** to block dangerous queries (only `SELECT` statements allowed)
- **Schema-aware system prompt** — the full database schema is injected into every LLM request so the agent never wastes iterations on introspection
- **In-memory agent memory** with seeded training examples for common questions
- **LRU caching middleware** (1-hour TTL) on LLM requests
- **Input validation middleware** using Pydantic

The database covers a simulated Indian clinic with patients, doctors, appointments, treatments, and invoices.

---

## Architecture Overview

```
User Query (plain English)
        │
        ▼
FastAPI  (/api/vanna/v2/chat_poll)
        │
        ▼
InputValidationMiddleware  ──► rejects empty / too-short prompts
        │
        ▼
CachingMiddleware  ──► returns cached LLM response if identical prompt seen within 1h
        │
        ▼
Vanna Agent (max 25 tool iterations)
  ├── system prompt: full clinic.db schema + memory workflow instructions
  ├── search_saved_correct_tool_uses  ──► checks agent memory for similar past questions
  ├── run_sql (SafeSqliteRunner)
  │     ├── validate_sql  ──► blocks non-SELECT / dangerous keywords
  │     └── executes query against clinic.db
  └── save_question_tool_args  ──► saves successful SQL to agent memory
        │
        ▼
Streaming JSON response (SSE chunks)
```

**Key design decisions:**

| Decision | Reason |
|---|---|
| Schema baked into system prompt | Eliminates PRAGMA introspection calls, saving tool iterations |
| `max_tool_iterations=25` | Gives agent room for memory search + multi-attempt SQL + save |
| PRAGMA blocked in validator | Schema is baked into the system prompt — agent has no need for PRAGMA introspection calls |
| 60-second delay in test script | Respects Groq API rate limits during bulk evaluation |

---

## Database Schema

The SQLite database (`clinic.db`) contains 5 tables:

```
patients        (id, first_name, last_name, email, phone, date_of_birth, gender, city, registered_date)
doctors         (id, name, specialization, department, phone)
appointments    (id, patient_id→patients, doctor_id→doctors, appointment_date, status, notes)
treatments      (id, appointment_id→appointments, treatment_id, cost, duration_minutes)
invoices        (id, patient_id→patients, invoice_date, total_amount, paid_amount, status)
```

**Default record counts** (configurable in `config.py`):

| Table        | Records |
|---|---|
| doctors      | 15      |
| patients     | 200     |
| appointments | 500     |
| treatments   | 350     |
| invoices     | 300     |

---

## About the Database (Faker-generated)

The `clinic.db` SQLite database is generated entirely by the [Faker](https://faker.readthedocs.io) library with random Indian-locale data. This means:

- Every time you run `python setup_database.py` you get a **fresh, different dataset** — different patient names, doctor names, amounts, dates, and cities.
- The structure (tables, columns, foreign keys, record counts) is always identical; only the content changes.
- All the example answers in this README ("200 patients", "Januja Kala has 40 appointments", "total revenue 754,921.83", etc.) come from the specific database used during the benchmark run. Your numbers will be different.

### Want to use the exact database from the benchmark?

If you want to reproduce the 19/20 result and see the same names/numbers as in [RESULTS.md](./RESULTS.md), download the pre-built database and drop it into the project root:

> **Download:** [clinic.db (Google Drive)](https://drive.google.com/file/d/1JT68JbSajxAD4P_vmu6mxIKOs7ZJH3rM/view?usp=sharing)
>
> Place the downloaded `clinic.db` file in the project root (next to `main.py`) and **skip** `python setup_database.py`. Then go straight to:
>
> ```bash
> pip install -r requirements.txt && python seed_memory.py && uvicorn main:app --port 8000
> ```

If you generate your own database instead, everything will still work — the SQL queries and agent logic are schema-driven, not data-driven.

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- A [Groq API key](https://console.groq.com)

### Step 1 — Clone and enter the project

```bash
git clone <your-repo-url>
cd nl-to-sql-system
```

### Step 2 — Create and activate a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### Step 3 — Set up your environment variables

```bash
cp .env.example .env
```

Open `.env` and add your Groq API key:

```
GROQ_API_KEY=gsk_your_key_here
```

### Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 5 — Initialise the database

```bash
python setup_database.py
```

This creates `clinic.db` and seeds it with:
- 15 doctors across 5 specializations
- 200 patients from 10 Indian cities
- 500 appointments (Scheduled / Completed / Cancelled)
- 350 treatments linked to completed appointments
- 300 invoices (Paid / Pending / Overdue)

### Step 6 — Seed agent memory

```bash
python seed_memory.py
```

This loads 15 curated question/SQL training examples into the agent's in-memory store so common queries are answered accurately from the first request.

### One-liner (steps 4–6 + server start)

```bash
pip install -r requirements.txt && python setup_database.py && python seed_memory.py && uvicorn main:app --port 8000
```

---

## Running the Server

```bash
uvicorn main:app --port 8000
```

The server starts at `http://127.0.0.1:8000`.

For development with auto-reload:

```bash
uvicorn main:app --port 8000 --reload
```

---

## API Documentation

### Health Check

**GET** `/health`

Returns database connectivity status and the number of seeded memory items.

```bash
curl http://127.0.0.1:8000/health
```

**Response:**
```json
{
  "status": "ok",
  "database": "connected",
  "agent_memory_items": 15
}
```

---

### Chat (NL-to-SQL)

**POST** `/api/vanna/v2/chat_poll`

Send a natural language question. The agent generates and executes SQL, then returns a plain-language answer.

**Request body:**

```json
{
  "message": "How many patients do we have?",
  "conversation_id": "my-session-001"
}
```

| Field             | Type   | Required | Description                                              |
|---|---|---|---|
| `message`         | string | Yes      | Your question in plain English                           |
| `conversation_id` | string | Yes      | Unique session identifier; use different IDs per session |

**Example requests and responses:**

#### Count query

```bash
curl -X POST http://127.0.0.1:8000/api/vanna/v2/chat_poll \
  -H "Content-Type: application/json" \
  -d '{"message": "How many patients do we have?", "conversation_id": "demo-1"}'
```

SQL executed:
```sql
SELECT COUNT(*) AS total_patients FROM patients
```

Agent answer: *"We have 200 patients registered in the clinic."*

---

#### Aggregation + JOIN

```bash
curl -X POST http://127.0.0.1:8000/api/vanna/v2/chat_poll \
  -H "Content-Type: application/json" \
  -d '{"message": "Which doctor has the most appointments?", "conversation_id": "demo-2"}'
```

SQL executed:
```sql
SELECT d.name, COUNT(a.id) AS appointment_count
FROM doctors d
JOIN appointments a ON d.id = a.doctor_id
GROUP BY d.id
ORDER BY appointment_count DESC
LIMIT 1
```

Agent answer: *"The doctor with the highest number of appointments is Januja Kala, who has 40 appointments."*

---

#### Revenue query

```bash
curl -X POST http://127.0.0.1:8000/api/vanna/v2/chat_poll \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the total revenue?", "conversation_id": "demo-3"}'
```

SQL executed:
```sql
SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM invoices
```

Agent answer: *"The clinic's total revenue is 754,921.83."*

---

#### Date-filtered query

```bash
curl -X POST http://127.0.0.1:8000/api/vanna/v2/chat_poll \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me appointments for last month", "conversation_id": "demo-4"}'
```

SQL executed:
```sql
SELECT id, patient_id, doctor_id, appointment_date, status, notes
FROM appointments
WHERE strftime('%Y-%m', appointment_date) = strftime('%Y-%m', 'now', '-1 month')
ORDER BY appointment_date
```

---

**Response format:**

The response is a JSON object containing a list of `chunks`. Each chunk is either:

- `simple` — plain text (agent's thinking / intermediate steps)
- `rich` — structured content of type `"text"` containing the final markdown answer

```json
{
  "chunks": [
    {
      "simple": { "text": "Searching memory for similar questions..." }
    },
    {
      "rich": {
        "type": "text",
        "data": {
          "content": "We have **200 patients** registered in the clinic."
        }
      }
    }
  ]
}
```

**Error response (validation failure):**

```json
{
  "detail": "Message is too short or empty."
}
```

---

### SQL Safety Rules

The system only allows read-only queries. The following are **blocked**:

- `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`
- `EXEC`, `GRANT`, `REVOKE`, `SHUTDOWN`
- `xp_*` and `sp_*` prefixes
- Access to `sqlite_master` system table

`PRAGMA` statements are **blocked** — the full schema is embedded in the system prompt, so the agent has no need for runtime introspection.

---

## Running the Evaluation Script

The test script sends all 20 benchmark questions to the API (one per 60 seconds to respect rate limits), captures the SQL the agent ran, and writes results to `RESULTS.md`.

```bash
python test_script.py
```

Results are saved to:
- `RESULTS.md` — human-readable report with SQL, row previews, and agent answers
- `test_run_results.json` — full raw JSON for programmatic use

**Latest benchmark result: 19/20 questions passed.**

See [RESULTS.md](./RESULTS.md) for the full breakdown.

---

## Project Structure

```
nl-to-sql-system/
├── main.py                  # FastAPI app, lifespan hooks, health route
├── vanna_setup.py           # Agent, LLM, tools, schema-aware system prompt
├── config.py                # Model config, DB name, table record counts
├── setup_database.py        # Creates clinic.db and seeds mock data
├── seed_memory.py           # Loads training examples into agent memory
├── sql_validation_check.py  # SQL safety validator (SELECT only)
├── caching_middleware.py    # LRU cache for LLM responses (1h TTL)
├── validation_middleware.py # Pydantic input validation for prompts
├── logger_setup.py          # Structured logging with structlog
├── test_script.py           # Automated 20-question evaluation harness
├── clinic.db                # SQLite database — generate with setup_database.py OR download pre-built (see README)
├── RESULTS.md               # Latest evaluation results
├── requirements.txt         # Python dependencies
├── .env                     # API keys (not committed)
└── .env.example             # Template for .env
```
