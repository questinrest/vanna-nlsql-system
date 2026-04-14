import os
from dotenv import load_dotenv

DB_NAME = "clinic.db"

TABLE_RECORD_COUNTS = {
    "doctors": 15,
    "patients": 200,
    "appointments": 500,
    "treatments": 350,
    "invoices": 300,
}

load_dotenv()


## llm configs
base_url = 'https://api.groq.com/openai/v1'
model_name = "openai/gpt-oss-120b"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
