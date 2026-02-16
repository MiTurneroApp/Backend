from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

def migrate():
    with engine.connect() as conn:
        print("Agregando columnas faltantes a la tabla 'users'...")
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE;"))
            print("- Columna 'is_admin' agregada.")
        except Exception as e:
            print(f"- Error o ya existe 'is_admin': {e}")
            
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN subscription_active BOOLEAN DEFAULT TRUE;"))
            print("- Columna 'subscription_active' agregada.")
        except Exception as e:
            print(f"- Error o ya existe 'subscription_active': {e}")
            
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
            print("- Columna 'created_at' agregada.")
        except Exception as e:
            print(f"- Error o ya existe 'created_at': {e}")
            
        conn.commit()
        print("Migración completada.")

if __name__ == "__main__":
    migrate()
