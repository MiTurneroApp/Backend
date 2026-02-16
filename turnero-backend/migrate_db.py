from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

def run_migration():
    print("Añadiendo columna 'price' a 'appointments'...")
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE appointments ADD COLUMN price INTEGER;"))
            conn.commit()
            print("Columna 'price' añadida con éxito.")
        except Exception as e:
            conn.rollback()
            print(f"Nota: No se pudo añadir 'price' (posiblemente ya existe): {e}")

    print("Añadiendo columna 'appointment_interval' a 'profile'...")
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE profile ADD COLUMN appointment_interval INTEGER DEFAULT 30;"))
            conn.commit()
            print("Columna 'appointment_interval' añadida con éxito.")
        except Exception as e:
            conn.rollback()
            print(f"Nota: No se pudo añadir 'appointment_interval' (posiblemente ya existe): {e}")

    print("Añadiendo columna 'customer_email' a 'appointments'...")
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE appointments ADD COLUMN customer_email VARCHAR;"))
            conn.commit()
            print("Columna 'customer_email' añadida con éxito.")
        except Exception as e:
            conn.rollback()
            print(f"Nota: No se pudo añadir 'customer_email' (posiblemente ya existe): {e}")

    print("Añadiendo columna 'customer_phone' a 'appointments'...")
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE appointments ADD COLUMN customer_phone VARCHAR;"))
            conn.commit()
            print("Columna 'customer_phone' añadida con éxito.")
        except Exception as e:
            conn.rollback()
            print(f"Nota: No se pudo añadir 'customer_phone' (posiblemente ya existe): {e}")

if __name__ == "__main__":
    run_migration()
