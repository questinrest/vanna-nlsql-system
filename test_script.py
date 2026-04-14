"""
NL-to-SQL evaluation script.

Behaviour
---------
- Sends each question to the FastAPI endpoint one at a time.
- Waits SLEEP_SECONDS between questions to respect API rate limits.
- Patches SafeSqliteRunner.run_sql to record every SQL the agent executes.
- Writes a structured report to RESULTS.md after every question so progress
  is visible even if the run is interrupted.
"""

import json
import time
import traceback
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from vanna_setup import db_tool

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESULTS_PATH = Path("RESULTS.md")
RAW_RESULTS_PATH = Path("test_run_results.json")

# One question every 60 seconds to stay inside LLM rate limits.
SLEEP_SECONDS = 60

QUESTIONS = [
    "How many patients do we have?",
    "List all doctors and their specializations",
    "Show me appointments for last month",
    "Which doctor has the most appointments?",
    "What is the total revenue?",
    "Show revenue by doctor",
    "How many cancelled appointments last quarter?",
    "Top 5 patients by spending",
    "Average treatment cost by specialization",
    "Show monthly appointment count for the past 6 months",
    "Which city has the most patients?",
    "List patients who visited more than 3 times",
    "Show unpaid invoices",
    "What percentage of appointments are no-shows?",
    "Show the busiest day of the week for appointments",
    "Revenue trend by month",
    "Average appointment duration by doctor",
    "List patients with overdue invoices",
    "Compare revenue between departments",
    "Show patient registration trend by month",
]

EXPECTED_BEHAVIOR = [
    "Returns count",
    "Returns doctor list",
    "Filters by date",
    "Aggregation + ordering",
    "SUM of invoice amounts",
    "JOIN + GROUP BY",
    "Status filter + date",
    "JOIN + ORDER + LIMIT",
    "Multi-table JOIN + AVG",
    "Date grouping",
    "GROUP BY + COUNT",
    "HAVING clause",
    "Status filter",
    "Percentage calculation",
    "Date function",
    "Time series",
    "AVG + GROUP BY",
    "JOIN + filter",
    "JOIN + GROUP BY",
    "Date grouping",
]


# ---------------------------------------------------------------------------
# Response-parsing helpers
# ---------------------------------------------------------------------------

def sanitize_value(value):
    """Convert non-JSON-serialisable values to safe types."""
    # NaN check
    if value != value:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def dataframe_to_records(df):
    if df is None:
        return [], []
    columns = [str(c) for c in df.columns]
    rows = []
    for row in df.to_dict(orient="records"):
        rows.append({k: sanitize_value(v) for k, v in row.items()})
    return rows, columns


def extract_text_chunks(chunks):
    """Pull all simple-text strings out of an SSE chunk list."""
    texts = []
    for chunk in chunks:
        simple = chunk.get("simple")
        if simple and simple.get("text"):
            texts.append(simple["text"])
    return texts


def final_answer_from_chunks(chunks):
    """
    Return the last meaningful text answer from the chunk list.
    Prefers rich-text content; falls back to simple-text.
    """
    for chunk in reversed(chunks):
        rich = chunk.get("rich") or {}
        if rich.get("type") == "text":
            content = ((rich.get("data") or {}).get("content") or "").strip()
            if content:
                return content

    texts = [t.strip() for t in extract_text_chunks(chunks) if t.strip()]
    return texts[-1] if texts else "No readable answer returned."


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_question(client, question_number, question, expected_behavior):
    """
    Send one question to the API, capture every SQL the agent executes,
    and return a structured result dict.
    """
    sql_entries = []
    original_run_sql = db_tool.sql_runner.run_sql

    async def capturing_run_sql(args, context):
        df = await original_run_sql(args, context)
        rows, columns = dataframe_to_records(df)
        # An error row is a single-column frame named "Error"
        has_error = bool(rows) and list(rows[0].keys()) == ["Error"]
        sql_entries.append({
            "sql": args.sql,
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "has_error": has_error,
        })
        return df

    # Patch the runner so we intercept every SQL call.
    db_tool.sql_runner.run_sql = capturing_run_sql
    try:
        response = client.post(
            "/api/vanna/v2/chat_poll",
            json={
                "message": question,
                "conversation_id": f"eval_run_{question_number}",
            },
        )
    finally:
        # Always restore the original runner.
        db_tool.sql_runner.run_sql = original_run_sql

    result = {
        "id": question_number,
        "question": question,
        "expected_behavior": expected_behavior,
        "status_code": response.status_code,
        "sql_entries": sql_entries,
        "final_answer": "",
        "all_text": [],
        "correct": False,
        "issue": "",
    }

    if response.status_code != 200:
        result["final_answer"] = "API Request Failed"
        result["issue"] = f"HTTP {response.status_code}: {response.text}"
        return result

    payload = response.json()
    chunks = payload.get("chunks", [])
    result["all_text"] = extract_text_chunks(chunks)
    result["final_answer"] = final_answer_from_chunks(chunks)
    result["issue"] = _classify_issue(response.status_code, sql_entries, result["final_answer"])
    result["correct"] = bool(sql_entries) and not result["issue"]
    return result


def _classify_issue(status_code, sql_entries, final_answer):
    if status_code != 200:
        return "API request failed."
    if "unexpected error" in final_answer.lower():
        return "The model failed before SQL generation; the API returned a generic error message."
    if not sql_entries:
        return "No SQL was executed."
    error_entries = [e for e in sql_entries if e["has_error"]]
    if error_entries and len(error_entries) == len(sql_entries):
        return "Every SQL attempt failed."
    if error_entries:
        return "Agent reached a final answer after one or more failed SQL attempts."
    return ""


# ---------------------------------------------------------------------------
# Report generation — writes to RESULTS.md
# ---------------------------------------------------------------------------

def _sql_display(sql_entries):
    """Return all captured SQL as a single fenced block."""
    if not sql_entries:
        return "None"
    return "\n\n".join(entry["sql"].strip() for entry in sql_entries)


def build_results_md(results):
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    passed = sum(1 for r in results if r["correct"])
    total = len(QUESTIONS)

    lines = [
        "# NL2SQL Evaluation Results",
        "",
        f"**Run completed:** {run_time}",
        f"**Passed:** {passed} out of {total}",
        "",
        "## Summary Table",
        "",
        "| Q# | Question | SQL Captured | Correct | Final Answer |",
        "| --- | --- | --- | --- | --- |",
    ]

    for r in results:
        question = r["question"].replace("|", "\\|")
        # Show only the first SQL in the summary column (truncated)
        if r["sql_entries"]:
            first_sql = r["sql_entries"][0]["sql"].strip().replace("\n", " ").replace("|", "\\|")
            if len(first_sql) > 80:
                first_sql = first_sql[:77] + "..."
            sql_col = f"`{first_sql}`"
        else:
            sql_col = "None"
        correct_col = "Yes" if r["correct"] else "No"
        answer_col = r["final_answer"].replace("|", "\\|").replace("\n", " ")
        if len(answer_col) > 120:
            answer_col = answer_col[:117] + "..."
        lines.append(f"| {r['id']} | {question} | {sql_col} | {correct_col} | {answer_col} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Detailed Results")
    lines.append("")

    for r in results:
        lines.append(f"### Q{r['id']}: {r['question']}")
        lines.append("")
        lines.append(f"**Expected Behaviour:** {r['expected_behavior']}")
        lines.append("")
        lines.append(f"**Correct:** {'Yes ✓' if r['correct'] else 'No ✗'}")
        lines.append("")

        # SQL block
        lines.append("**SQL Executed by Agent:**")
        lines.append("```sql")
        lines.append(_sql_display(r["sql_entries"]))
        lines.append("```")
        lines.append("")

        # Per-attempt data preview (first 5 rows of each attempt)
        if r["sql_entries"]:
            for idx, entry in enumerate(r["sql_entries"], start=1):
                prefix = f"Attempt {idx}" if len(r["sql_entries"]) > 1 else "Result"
                if entry["has_error"]:
                    lines.append(f"**{prefix} – Error:** {entry['rows'][0].get('Error', 'unknown error')}")
                else:
                    lines.append(f"**{prefix} – Row count:** {entry['row_count']}")
                    if entry["rows"]:
                        preview = entry["rows"][:5]
                        lines.append(f"**{prefix} – Preview (up to 5 rows):**")
                        lines.append("```json")
                        lines.append(json.dumps(preview, indent=2, ensure_ascii=False))
                        lines.append("```")
                lines.append("")

        lines.append("**Final Answer from Agent:**")
        lines.append("")
        lines.append(r["final_answer"])
        lines.append("")

        if r["issue"]:
            lines.append("**Issue / Failure Explanation:**")
            lines.append("")
            lines.append(r["issue"])
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def save_results_md(results):
    RESULTS_PATH.write_text(build_results_md(results), encoding="utf-8")


def save_raw_results(results):
    RAW_RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    print("=" * 60)
    print("NL-to-SQL evaluation run starting.")
    print(f"Questions   : {len(QUESTIONS)}")
    print(f"Rate limit  : one question every {SLEEP_SECONDS} seconds")
    print(f"Output      : {RESULTS_PATH}")
    print("=" * 60)
    print()

    results = []

    with TestClient(app) as client:
        for index, question in enumerate(QUESTIONS, start=1):
            print(f"[{index:02d}/{len(QUESTIONS)}] Question: {question}")
            try:
                result = evaluate_question(
                    client=client,
                    question_number=index,
                    question=question,
                    expected_behavior=EXPECTED_BEHAVIOR[index - 1],
                )
            except Exception as exc:
                result = {
                    "id": index,
                    "question": question,
                    "expected_behavior": EXPECTED_BEHAVIOR[index - 1],
                    "status_code": None,
                    "sql_entries": [],
                    "final_answer": "Script exception encountered",
                    "all_text": [],
                    "correct": False,
                    "issue": f"Python exception: {exc}",
                    "traceback": traceback.format_exc(),
                }

            results.append(result)

            # Persist after every question so progress isn't lost.
            save_results_md(results)
            save_raw_results(results)

            # Console summary for this question.
            sql_count = len(result["sql_entries"])
            print(f"         SQL captured : {sql_count} statement(s)")
            if result["sql_entries"]:
                for i, entry in enumerate(result["sql_entries"], 1):
                    tag = "[ERROR]" if entry["has_error"] else "[OK]"
                    snippet = entry["sql"].strip().replace("\n", " ")[:120]
                    print(f"           {i}. {tag} {snippet}")
            print(f"         Final answer : {result['final_answer'][:120]}")
            if result["issue"]:
                print(f"         Issue        : {result['issue']}")
            print()

            # Rate-limit pause between questions.
            if index < len(QUESTIONS):
                print(f"Sleeping {SLEEP_SECONDS}s before next question...\n")
                time.sleep(SLEEP_SECONDS)

    passed = sum(1 for r in results if r["correct"])
    print("=" * 60)
    print(f"Run complete. Passed: {passed} / {len(QUESTIONS)}")
    print(f"Results written to : {RESULTS_PATH}")
    print(f"Raw JSON saved to  : {RAW_RESULTS_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    run()
