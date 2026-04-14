from datetime import datetime
from pathlib import Path
from logger_setup import logger
from vanna import Agent
from vanna.core.agent.config import AgentConfig
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt.base import SystemPromptBuilder
from vanna.core.user import UserResolver, User, RequestContext
from vanna.tools import RunSqlTool
from vanna.tools.agent_memory import SaveQuestionToolArgsTool, SearchSavedCorrectToolUsesTool
from vanna.integrations.sqlite import SqliteRunner
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.openai import OpenAILlmService
from caching_middleware import CachingMiddleware
from validation_middleware import InputValidationMiddleware
from sql_validation_check import validate_sql

try:
    from .config import model_name, GROQ_API_KEY, base_url
    from .seed_memory import seed_agent_memory
except ImportError:
    from config import model_name, GROQ_API_KEY, base_url
    from seed_memory import seed_agent_memory

DB_PATH = Path(__file__).resolve().parent / "clinic.db"

SCHEMA_CONTEXT = """\
DATABASE: clinic.db  (SQLite)

============================================================
TABLE: patients
============================================================
CREATE TABLE patients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name      TEXT    NOT NULL,
    last_name       TEXT    NOT NULL,
    email           TEXT,
    phone           TEXT,
    date_of_birth   DATE,            -- format: YYYY-MM-DD
    gender          TEXT,            -- e.g. 'male', 'female', 'other'
    city            TEXT,
    registered_date DATE             -- format: YYYY-MM-DD
);

============================================================
TABLE: doctors
============================================================
CREATE TABLE doctors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    specialization  TEXT,            -- e.g. 'Cardiology', 'Dermatology'
    department      TEXT,            -- e.g. 'Outpatient', 'ICU'
    phone           TEXT
);

============================================================
TABLE: appointments
============================================================
CREATE TABLE appointments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id       INTEGER REFERENCES patients(id),
    doctor_id        INTEGER REFERENCES doctors(id),
    appointment_date DATETIME,       -- format: YYYY-MM-DD HH:MM:SS
    status           TEXT,           -- 'Scheduled', 'Completed', 'Cancelled', 'No-show'
    notes            TEXT
);

============================================================
TABLE: treatments
============================================================
CREATE TABLE treatments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id   INTEGER REFERENCES appointments(id),
    treatment_id     TEXT,           -- treatment code / name
    cost             REAL,           -- cost in local currency
    duration_minutes INTEGER
);

============================================================
TABLE: invoices
============================================================
CREATE TABLE invoices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER REFERENCES patients(id),
    invoice_date DATE,               -- format: YYYY-MM-DD
    total_amount REAL,
    paid_amount  REAL,
    status       TEXT                -- 'Paid', 'Pending', 'Overdue'
);

============================================================
KEY RELATIONSHIPS
============================================================
- appointments.patient_id  -> patients.id
- appointments.doctor_id   -> doctors.id
- treatments.appointment_id -> appointments.id
- invoices.patient_id      -> patients.id

============================================================
USEFUL QUERY PATTERNS
============================================================
-- Revenue = SUM(invoices.total_amount)
-- Unpaid   = WHERE paid_amount < total_amount OR status != 'Paid'
-- "last month" -> strftime('%Y-%m', appointment_date) = strftime('%Y-%m', 'now', '-1 month')
-- "this year"  -> strftime('%Y', appointment_date) = strftime('%Y', 'now')
-- No-show rate -> COUNT(*) FILTER (WHERE status='No-show') * 100.0 / COUNT(*)
-- Doctor revenue -> JOIN appointments ON doctor_id, JOIN invoices ON patient_id
-- Always use strftime for date grouping in SQLite.
"""


class SchemaAwareSystemPromptBuilder(SystemPromptBuilder):
    async def build_system_prompt(self, user, tools):
        today = datetime.now().strftime("%Y-%m-%d")
        tool_names = [t.name for t in tools]
        has_search = "search_saved_correct_tool_uses" in tool_names
        has_save   = "save_question_tool_args" in tool_names

        parts = [
            f"You are Vanna, an AI data analyst assistant for a clinic management system. Today's date is {today}.",
            "",
            "## DATABASE SCHEMA",
            "",
            SCHEMA_CONTEXT,
            "",
            "## RESPONSE GUIDELINES",
            "",
            "- Use the schema above to write accurate SQLite queries — do NOT run PRAGMA statements.",
            "- When you execute a query, the raw results are shown to the user outside your response.",
            "  Focus your reply on interpreting and summarising the data.",
            "- Any final summary or observations should be the LAST step.",
            f"- Available tools: {', '.join(tool_names)}",
        ]

        if has_search or has_save:
            parts += [
                "",
                "## MEMORY WORKFLOW",
                "",
            ]
            if has_search:
                parts += [
                    "BEFORE executing run_sql, call `search_saved_correct_tool_uses` with the user's",
                    "question to check for existing successful patterns.",
                ]
            if has_save:
                parts += [
                    "AFTER a successful run_sql call, call `save_question_tool_args` to save the",
                    "pattern for future reuse.",
                ]
            parts += [
                "",
                "Do NOT skip the search step. Do NOT forget to save successful executions.",
            ]

        return "\n".join(parts)



# Core services


class OpenUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id="default_user", email="user@example.com", group_memberships=[])


llm = OpenAILlmService(
    base_url=base_url,
    model=model_name,
    api_key=GROQ_API_KEY,
)

validation_mw = InputValidationMiddleware()
caching_mw    = CachingMiddleware(ttl=3600)


class SafeSqliteRunner(SqliteRunner):
    async def run_sql(self, args, context):
        import pandas as pd
        logger.info("Intercepted SQL execution request", query=args.sql)

        is_safe, error_msg = validate_sql(args.sql)
        if not is_safe:
            logger.warning(
                "Generated SQL failed safety validation",
                query=args.sql,
                validation_error=error_msg,
            )
            return pd.DataFrame({"Error": [f"Oops! The generated SQL was rejected: {error_msg}"]})

        try:
            df = await super().run_sql(args, context)

            if df is None or df.empty:
                logger.info("SQL query executed but returned no results", query=args.sql)
                return pd.DataFrame({"Message": ["No data found"]})

            logger.info("SQL query executed successfully", rows_returned=len(df), query=args.sql)
            return df

        except Exception as e:
            logger.error("Database execution failed", query=args.sql, exc_info=True)
            return pd.DataFrame({"Error": [f"Database execution failed: {str(e)}"]})


db_tool = RunSqlTool(sql_runner=SafeSqliteRunner(database_path=str(DB_PATH)))

agent_memory = DemoAgentMemory(max_items=1000)

tools = ToolRegistry()
tools.register_local_tool(SaveQuestionToolArgsTool(), access_groups=[])
tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=[])
tools.register_local_tool(db_tool, access_groups=[])

user_resolver = OpenUserResolver()

agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=user_resolver,
    agent_memory=agent_memory,
    llm_middlewares=[validation_mw, caching_mw],
    config=AgentConfig(max_tool_iterations=25),
    system_prompt_builder=SchemaAwareSystemPromptBuilder(),
)
