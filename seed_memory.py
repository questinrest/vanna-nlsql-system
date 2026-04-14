import asyncio
from typing import Iterable
from logger_setup import logger

from vanna.capabilities.agent_memory import AgentMemory, ToolMemory
from vanna.core.tool import ToolContext
from vanna.core.user import User


TRAINING_EXAMPLES = [
    ToolMemory(
        question="How many patients do we have?",
        tool_name="run_sql",
        args={"sql": "SELECT COUNT(*) AS total_patients FROM patients"},
    ),
    ToolMemory(
        question="List all patients with their city and gender",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT id, first_name, last_name, city, gender
            FROM patients
            ORDER BY last_name, first_name
            """
        },
    ),
    ToolMemory(
        question="Show patients from Ahmedabad",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT id, first_name, last_name, city
            FROM patients
            WHERE city = 'Ahmedabad'
            ORDER BY last_name, first_name
            """
        },
    ),
    ToolMemory(
        question="How many female patients do we have?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT COUNT(*) AS female_patients
            FROM patients
            WHERE gender = 'female'
            """
        },
    ),
    ToolMemory(
        question="How many appointments does each doctor have?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT d.name, COUNT(a.id) AS appointment_count
            FROM doctors d
            LEFT JOIN appointments a ON d.id = a.doctor_id
            GROUP BY d.id, d.name
            ORDER BY appointment_count DESC, d.name
            """
        },
    ),
    ToolMemory(
        question="Who is the busiest doctor?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT d.name, COUNT(a.id) AS appointment_count
            FROM doctors d
            LEFT JOIN appointments a ON d.id = a.doctor_id
            GROUP BY d.id, d.name
            ORDER BY appointment_count DESC, d.name
            LIMIT 1
            """
        },
    ),
    ToolMemory(
        question="How many appointments do we have by status?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT status, COUNT(*) AS appointment_count
            FROM appointments
            GROUP BY status
            ORDER BY appointment_count DESC
            """
        },
    ),
    ToolMemory(
        question="Show appointment counts by month",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT strftime('%Y-%m', appointment_date) AS month, COUNT(*) AS appointment_count
            FROM appointments
            GROUP BY strftime('%Y-%m', appointment_date)
            ORDER BY month
            """
        },
    ),
    ToolMemory(
        question="Show appointments by doctor",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT d.name, a.status, COUNT(*) AS appointment_count
            FROM appointments a
            JOIN doctors d ON d.id = a.doctor_id
            GROUP BY d.id, d.name, a.status
            ORDER BY d.name, appointment_count DESC
            """
        },
    ),
    ToolMemory(
        question="What is the total revenue?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT ROUND(SUM(total_amount), 2) AS total_revenue
            FROM invoices
            """
        },
    ),
    ToolMemory(
        question="Show unpaid invoices",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT id, patient_id, invoice_date, total_amount, paid_amount, status
            FROM invoices
            WHERE paid_amount < total_amount OR status != 'Paid'
            ORDER BY invoice_date DESC, id DESC
            """
        },
    ),
    ToolMemory(
        question="What is the average treatment cost?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT ROUND(AVG(cost), 2) AS average_treatment_cost
            FROM treatments
            """
        },
    ),
    ToolMemory(
        question="Show appointments from the last 3 months",
        tool_name="run_sql",
        args={
            "sql": """
            WITH latest_date AS (
                SELECT DATE(MAX(appointment_date)) AS max_appointment_date
                FROM appointments
            )
            SELECT id, patient_id, doctor_id, appointment_date, status
            FROM appointments, latest_date
            WHERE DATE(appointment_date) >= DATE(max_appointment_date, '-3 months')
            ORDER BY appointment_date DESC
            """
        },
    ),
    ToolMemory(
        question="Show invoice revenue trend by month",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT strftime('%Y-%m', invoice_date) AS month,
                   ROUND(SUM(total_amount), 2) AS monthly_revenue
            FROM invoices
            GROUP BY strftime('%Y-%m', invoice_date)
            ORDER BY month
            """
        },
    ),
    ToolMemory(
        question="Which city has the most patients?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT city, COUNT(*) AS patient_count
            FROM patients
            GROUP BY city
            ORDER BY patient_count DESC, city
            LIMIT 1
            """
        },
    ),
]
async def seed_agent_memory(agent_memory: AgentMemory) -> int:
    your_user = User(
        id="default_user",
        email="user@example.com",
        group_memberships=[],
    )
    context = ToolContext(
        user=your_user,
        conversation_id="memory-seed",
        request_id="memory-seed",
        agent_memory=agent_memory,
        metadata={},
    )
    existing_memories = await agent_memory.get_recent_memories(context, limit=5000)
    existing_questions = set()
    for memory in existing_memories:
        existing_questions.add(memory.question)

    inserted_count = 0
    for example in TRAINING_EXAMPLES:
        if example.question in existing_questions:
            continue

        try:
            # Add to agent memory using the same ToolContext pattern shown in the docs.
            await agent_memory.save_tool_usage(
                question=example.question,
                tool_name=example.tool_name,
                args=example.args,
                context=context,
                success=True,
            )
            inserted_count += 1
        except Exception as e:
            logger.error("Failed to insert seed memory", query=example.question, exc_info=True)

    logger.info("Agent memory seeding complete", total_inserted=inserted_count)
    return inserted_count


def count_seeded_memories(agent_memory: AgentMemory) -> int:
    your_user = User(
        id="default_user",
        email="user@example.com",
        group_memberships=[],
    )
    context = ToolContext(
        user=your_user,
        conversation_id="memory-seed",
        request_id="memory-seed",
        agent_memory=agent_memory,
        metadata={},
    )
    memories = asyncio.run(agent_memory.get_recent_memories(context, limit=5000))
    seeded_questions = set()
    for example in TRAINING_EXAMPLES:
        seeded_questions.add(example.question)
    
    count = 0
    for memory in memories:
        if memory.question in seeded_questions:
            count += 1
            
    return count
