import sqlite3
from faker import Faker
import random
from datetime import datetime, timedelta
from logger_setup import logger

try:
    from .config import DB_NAME, TABLE_RECORD_COUNTS
except ImportError:
    from config import DB_NAME, TABLE_RECORD_COUNTS

# TABLE CREATION SQL STATEMENTS

table_creation_statements = [
    """CREATE TABLE IF NOT EXISTS patients 
    (id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name text NOT NULL,
    last_name text NOT NULL,
    email text,
    phone text,
    date_of_birth DATE,
    gender text,
    city text,
    registered_date DATE);""",

    """CREATE TABLE IF NOT EXISTS doctors 
    (id INTEGER PRIMARY KEY AUTOINCREMENT,
    name text NOT NULL,
    specialization text,
    department text,
    phone text
    );""",

    """CREATE TABLE IF NOT EXISTS appointments 
    (id INTEGER PRIMARY KEY AUTOINCREMENT, 
    patient_id INTEGER,
    doctor_id INTEGER,
    appointment_date DATETIME,
    status text,
    notes text,
    FOREIGN key (patient_id) REFERENCES patients (id),
    FOREIGN key (doctor_id) REFERENCES doctors (id)
    );""",

    """CREATE TABLE IF NOT EXISTS treatments
    (id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER,
    treatment_id text,
    cost REAL,
    duration_minutes INTEGER,
    FOREIGN KEY (appointment_id) REFERENCES appointments (id)
    );""",

    """CREATE TABLE IF NOT EXISTS invoices 
    (id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER,
    invoice_date DATE,
    total_amount REAL,
    paid_amount REAL,
    status text,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
    );"""
]

fake = Faker(locale="en_IN")

# HELPERS FUNCTIONS

def indian_mobile():
    number_string = "+91 " + str(random.randint(6, 9))
    for _ in range(9):
        number_string = number_string + str(random.randint(0, 9))
    return number_string

def random_date():
    start = datetime.now() - timedelta(days=365)
    return (start + timedelta(days=random.randint(0, 365))).strftime("%Y-%m-%d")

def random_datetime():
    start = datetime.now() - timedelta(days=365)
    base_date = start + timedelta(days=random.randint(0, 365))
    # assuming these slots
    time_slots = [
        (10, 0), (10, 15), (10, 30), (10, 45),
        (11, 0), (11, 15), (11, 30), (11, 45),
        (12, 0), (12, 15), (12, 30), (12, 45),
        (13, 0),
        (16, 0), (16, 15), (16, 30), (16, 45),
        (17, 0), (17, 15), (17, 30), (17, 45),
        (18, 0), (18, 15), (18, 30), (18, 45),
        (19, 0)
    ]

    hour, minute = random.choice(time_slots)

    return base_date.replace(hour=hour, minute=minute, second=0).strftime("%Y-%m-%d %H:%M:%S")

def phone_or_none():
    if random.random() > 0.2:
        return indian_mobile()
    else:
        return None

def email_or_none():
    if random.random() > 0.2:
        return fake.email()
    else:
        return None
    

# SQL QUERIES FOR DATA INSERTION

def add_doctor_data():
    return """INSERT INTO doctors(name,specialization,department, phone)
              VALUES(?,?,?,?)"""

def add_patient_data():
    return """INSERT INTO patients(first_name, last_name, email, phone, date_of_birth, gender, city, registered_date)
              VALUES(?,?,?,?,?,?,?,?)"""

def add_appointment_data():
    return """INSERT INTO appointments(patient_id, doctor_id, appointment_date, status, notes)
              VALUES(?,?,?,?,?)"""

def add_treatment_data():
    return """INSERT INTO treatments(appointment_id, treatment_id, cost, duration_minutes)
              VALUES(?,?,?,?)"""

def add_invoice_data():
    return """INSERT INTO invoices(patient_id, invoice_date, total_amount, paid_amount, status)
              VALUES(?,?,?,?,?)"""

# DATA GENERATION FUNCTIONS

def generate_doctor_data(n):
    specialization = ["Dermatology", "Cardiology", "Orthopedics", "General", "Pediatrics"]
    doctors = []
    for _ in range(n):
        spec = random.choice(specialization)
        if spec == "General":
            department = "OPD"
        else:
            department = f"Department of {spec}"
        doctors.append((
            fake.name(),
            spec,
            department,
            phone_or_none()
        ))

    return doctors


def generate_patient_data(n):
    cities = ["Ahmedabad","Pune","Jaipur","Lucknow","Chandigarh",
              "Indore","Bhopal","Kochi","Coimbatore","Nagpur"]
    data = []
    for _ in range(n):
        gender = random.choice(["male", "female"])
        if gender == "male":
            first = fake.first_name_male()
        else:
            first = fake.first_name_female()
        data.append((
            first,
            fake.last_name(),
            email_or_none(),
            phone_or_none(),
            fake.date_of_birth(minimum_age=1, maximum_age=90).strftime("%Y-%m-%d"),
            gender,
            random.choice(cities),
            random_date()
        ))
    return data


def generate_appointments(n, patient_ids, doctor_ids):
    statuses = ["Scheduled", "Completed", "Cancelled"]
    data = []
    for _ in range(n):
        status = random.choice(statuses)
        if status == "Scheduled":
            if random.random() > 0.2:
                notes = fake.sentence(nb_words=8)
            else:
                notes = None
        elif status == "Completed":
            if random.random() > 0.2:
                notes = fake.sentence(nb_words=8)
            else:
                notes = None
        else:
            notes = None
        data.append((
            random.choice(patient_ids),
            random.choice(doctor_ids),
            random_datetime(),
            status,
            notes
        ))

    return data


def generate_treatments(n, appointment_ids):
    treatments = []
    for _ in range(n):
        treatments.append((
            random.choice(appointment_ids),
            f"TREAT-{random.randint(1000,9999)}",
            round(random.uniform(50, 5000), 2),
            random.randint(10, 180)
        ))

    return treatments


def generate_invoices(n, patient_ids):
    statuses = ["Paid", "Pending", "Overdue"]
    data = []
    for _ in range(n):
        total = round(random.uniform(50, 5000), 2)
        if random.random() < 0.5:
            paid = total
        else:
            paid = round(random.uniform(0, total), 2)
        data.append((
            random.choice(patient_ids),
            random_date(),
            total,
            paid,
            random.choice(statuses)
        ))
    return data


# MAIN FUNCTION
def main():
    logger.info("Starting database initialization and mock data generation.")
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()

            # create tables
            for statement in table_creation_statements:
                cursor.execute(statement)

            # doctors
            doctors = generate_doctor_data(TABLE_RECORD_COUNTS["doctors"])
            cursor.executemany(add_doctor_data(), doctors)

            # patients
            patients = generate_patient_data(TABLE_RECORD_COUNTS["patients"])
            cursor.executemany(add_patient_data(), patients)

            # fetch ids
            cursor.execute("SELECT id FROM patients")
            patient_ids = []
            for x in cursor.fetchall():
                patient_ids.append(x[0])

            cursor.execute("SELECT id FROM doctors")
            doctor_ids = []
            for x in cursor.fetchall():
                doctor_ids.append(x[0])

            # appointments
            appointments = generate_appointments(
                TABLE_RECORD_COUNTS["appointments"],
                patient_ids,
                doctor_ids
            )
            cursor.executemany(add_appointment_data(), appointments)

            # completed appointments
            cursor.execute("SELECT id FROM appointments WHERE status='Completed'")
            completed_ids = []
            for x in cursor.fetchall():
                completed_ids.append(x[0])

            # treatments
            treatments = generate_treatments(
                TABLE_RECORD_COUNTS["treatments"],
                completed_ids
            )
            cursor.executemany(add_treatment_data(), treatments)

            # invoices
            invoices = generate_invoices(
                TABLE_RECORD_COUNTS["invoices"],
                patient_ids
            )
            cursor.executemany(add_invoice_data(), invoices)

            conn.commit()

            logger.info(
                "Data inserted successfully.",
                patients=TABLE_RECORD_COUNTS['patients'],
                doctors=TABLE_RECORD_COUNTS['doctors'],
                appointments=TABLE_RECORD_COUNTS['appointments'],
                treatments=TABLE_RECORD_COUNTS['treatments'],
                invoices=TABLE_RECORD_COUNTS['invoices'],
            )
    except Exception as e:
        logger.error("Failed to mock database", exc_info=True)
        raise e

#################################

if __name__ == "__main__":
    main()
