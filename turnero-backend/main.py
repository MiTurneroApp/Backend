from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Response
from sqlalchemy.orm import Session
import models
from database import engine, get_db
models.Base.metadata.create_all(bind=engine)
from pydantic import BaseModel
from typing import List
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi.staticfiles import StaticFiles
from fastapi import File, UploadFile
import shutil
import uuid
import os
from supabase import create_client, Client
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException


SECRET_KEY = os.getenv("CLAVE")
ALGORITHM = os.getenv("ALGORITMO")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TIEMPO"))
HASH_PWWD = os.getenv("HASH_PWW")

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token") 

def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"Error al verificar password: {e}")
        return False

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=401, detail="Credenciales inválidas", headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_admin(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No tienes permisos de administrador")
    return current_user

models.Base.metadata.create_all(bind=engine)

def run_migrations_and_seed():
    db = SessionLocal()
    try:
        from sqlalchemy import text
        print("Verificando esquema de base de datos...")
        # Agregar columnas si faltan (PostgreSQL/SQLite safe)
        columns = [
            ("is_admin", "BOOLEAN DEFAULT FALSE"),
            ("subscription_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        for col, typ in columns:
            try:
                db.execute(text(f"ALTER TABLE users ADD COLUMN {col} {typ};"))
                db.commit()
                print(f"Columna '{col}' agregada a 'users' con éxito.")
            except Exception:
                db.rollback()
                pass

        # Sembrar Administrador
        admin_username = "Administrador"
        existing_admin = db.query(models.User).filter(models.User.username == admin_username).first()
        if not existing_admin:
            print("Creando usuario Administrador inicial...")
            hashed_pwd = get_password_hash(HASH_PWWD)
            new_admin = models.User(
                username=admin_username, 
                hashed_password=hashed_pwd, 
                is_admin=True,
                subscription_active=True
            )
            db.add(new_admin)
            db.commit()
            print("Usuario Administrador creado.")
    finally:
        db.close()

from database import SessionLocal
run_migrations_and_seed()

app = FastAPI(title="BarberShop API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuración Brevo
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY
brevo_api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))


# Montar archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root():
    return {"message": "Barber API Online"}

@app.get("/services")
def get_services(
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.Service).filter(models.Service.owner_id == current_user.id).all()

@app.post("/services")
def create_service(
    name: str, price: float, duration: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    new_service = models.Service(
        name=name, price=price, duration=duration, 
        owner_id=current_user.id
    )
    db.add(new_service)
    db.commit()
    return new_service

@app.put("/services/{service_id}")
def update_service(
    service_id: int, 
    name: str, price: float, duration: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    service = db.query(models.Service).filter(
        models.Service.id == service_id,
        models.Service.owner_id == current_user.id
    ).first()
    
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
        
    service.name = name
    service.price = price
    service.duration = duration
    db.commit()
    db.refresh(service)
    return service
@app.get("/services/{slug}")
def get_public_services(slug: str, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    
    # VALIDACIÓN: Si el usuario está suspendido, no mostramos nada
    if not profile.owner.is_active:
        raise HTTPException(status_code=404, detail="Este Negocio se encuentra suspendido")

    return db.query(models.Service).filter(models.Service.owner_id == profile.owner_id).all()

@app.get("/appointments")
def get_appointments(
    status: str = None, 
    date: str = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Usamos un join para traer el nombre del servicio directamente
    query = db.query(
        models.Appointment,
        models.Service.name.label("service_name")
    ).join(
        models.Service, models.Appointment.service_id == models.Service.id
    ).filter(models.Appointment.owner_id == current_user.id)
    
    if status:
        query = query.filter(models.Appointment.status == status)
    
    if date:
        try:
            search_date = datetime.strptime(date, "%Y-%m-%d")
            start_day = search_date.replace(hour=0, minute=0, second=0)
            end_day = search_date.replace(hour=23, minute=59, second=59)
            query = query.filter(
                models.Appointment.date_time >= start_day,
                models.Appointment.date_time <= end_day
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido (YYYY-MM-DD)")
            
    results = query.order_by(models.Appointment.date_time.asc()).all()
    
    # Aplanamos el resultado para que el frontend lo reciba igual que antes + service_name
    appointments = []
    for apt, s_name in results:
        apt_dict = {column.name: getattr(apt, column.name) for column in apt.__table__.columns}
        apt_dict["service_name"] = s_name
        appointments.append(apt_dict)
        
    return appointments

@app.get("/appointments/public/{slug}")
def get_public_appointments(slug: str, date: str, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    
    if not profile.owner.is_active:
        raise HTTPException(status_code=404, detail="Negocio suspendido")
   
    # Parsear la fecha para filtrar por día (YYYY-MM-DD)
    try:
        search_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido (YYYY-MM-DD)")

    # Buscar turnos para ese día y ese barbero
    start_day = search_date.replace(hour=0, minute=0, second=0)
    end_day = search_date.replace(hour=23, minute=59, second=59)

    appointments = db.query(models.Appointment).filter(
        models.Appointment.owner_id == profile.owner_id,
        models.Appointment.date_time >= start_day,
        models.Appointment.date_time <= end_day,
        models.Appointment.status != "cancelled"
    ).all()

    # Solo devolver las horas ocupadas y su duración
    return [
        {"time": a.date_time.strftime("%H:%M"), "duration": a.service.duration} 
        for a in appointments
    ]

@app.post("/appointments")
def create_appointment(
    customer_name: str, 
    service_id: int, 
    date_time: str,
    customer_email: str = None,
    customer_phone: str = None,
    db: Session = Depends(get_db)
):
    # Parsear fecha
    try:
        # Si viene con Z, lo tratamos como UTC y lo convertimos a naive local (o lo guardamos tal cual)
        # Pero si el frontend manda local nominal, fromisoformat lo toma bien.
        if "Z" in date_time:
            dt_obj = datetime.fromisoformat(date_time.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            dt_obj = datetime.fromisoformat(date_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")

    # Obtener el owner_id desde el servicio
    service = db.query(models.Service).filter(models.Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")

    # VALIDACIÓN: Prevenir doble reserva
    existing = db.query(models.Appointment).filter(
        models.Appointment.owner_id == service.owner_id,
        models.Appointment.date_time == dt_obj,
        models.Appointment.status != "cancelled"
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Este horario ya está reservado")

    new_appo = models.Appointment(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        service_id=service_id,
        date_time=dt_obj,
        owner_id=service.owner_id,
        price=service.price
    )
    db.add(new_appo)
    db.commit()
    db.refresh(new_appo)
    return new_appo

@app.patch("/appointments/{appointment_id}/status")
def update_status(
    appointment_id: int, 
    status: str, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    appointment = db.query(models.Appointment).filter(
        models.Appointment.id == appointment_id,
        models.Appointment.owner_id == current_user.id
    ).first()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    
    # Si el estado es "cancelled", enviar email de cancelación y eliminar el turno
    if status == "cancelled":
        # Enviar email de cancelación antes de eliminar
        if appointment.customer_email:
            try:
                send_cancellation_email(
                    customer_name=appointment.customer_name,
                    customer_email=appointment.customer_email,
                    service_name=appointment.service.name,
                    appointment_date=appointment.date_time,
                    business_name=current_user.profile.name if current_user.profile else "Negocio"
                )
            except Exception as e:
                print(f"Error al enviar email de cancelación: {e}")
                # No bloqueamos la cancelación si falla el email
        
        db.delete(appointment)
        db.commit()
        return {"message": "Turno eliminado"}
    
    # Para otros estados, actualizar
    appointment.status = status
    db.commit()
    
    # Si el estado es "confirmed" o "concretado", enviar email de confirmación
    if status in ["confirmed", "concretado"] and appointment.customer_email:
        try:
            send_confirmation_email(
                customer_name=appointment.customer_name,
                customer_email=appointment.customer_email,
                service_name=appointment.service.name,
                appointment_date=appointment.date_time,
                business_name=current_user.profile.name if current_user.profile else "Negocio"
            )
        except Exception as e:
            print(f"Error al enviar email de confirmación: {e}")
            # No bloqueamos la confirmación si falla el email
    
    return {"message": f"Turno actualizado a {status}"}


def send_confirmation_email(customer_name: str, customer_email: str, service_name: str, appointment_date: datetime, business_name: str):
    """
    Envía un email de confirmación usando Brevo cuando se confirma un turno.
    """
    if not BREVO_API_KEY:
        print("ADVERTENCIA: BREVO_API_KEY no está configurado. El email no será enviado.")
        return
    
    try:
        # Formatear la fecha del turno
        from datetime import datetime
        fecha_formateada = appointment_date.strftime("%d/%m/%Y")
        hora_formateada = appointment_date.strftime("%H:%M")
        
        # Crear el email
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": customer_email, "name": customer_name}],
            sender={"email": "negosaas@outlook.com", "name": business_name},
            subject=f"✅ Turno Confirmado - {business_name}",
            html_content=f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px; color: white; text-align: center;">
                        <h1 style="margin: 0; font-size: 28px;">✅ ¡Turno Confirmado!</h1>
                    </div>
                    
                    <div style="padding: 30px; background-color: #f9f9f9; border-radius: 10px; margin-top: 20px;">
                        <p style="font-size: 18px; color: #333;">Hola <strong>{customer_name}</strong>,</p>
                        
                        <p style="font-size: 16px; color: #555; line-height: 1.6;">
                            Tu turno ha sido <strong style="color: #667eea;">confirmado</strong> por {business_name}.
                        </p>
                        
                        <div style="background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #667eea;">
                            <p style="margin: 5px 0; font-size: 16px; color: #333;"><strong>📋 Servicio:</strong> {service_name}</p>
                            <p style="margin: 5px 0; font-size: 16px; color: #333;"><strong>📅 Fecha:</strong> {fecha_formateada}</p>
                            <p style="margin: 5px 0; font-size: 16px; color: #333;"><strong>🕐 Hora:</strong> {hora_formateada}hs</p>
                        </div>
                        
                        <p style="font-size: 14px; color: #777; margin-top: 30px;">
                            Te esperamos! Si necesitas cancelar o reprogramar, por favor contacta al negocio.
                        </p>
                    </div>
                    
                    <div style="text-align: center; margin-top: 20px; padding: 20px; color: #999; font-size: 12px;">
                        <p>Este es un email automático, por favor no respondas a este mensaje.</p>
                    </div>
                </body>
            </html>
            """
        )
        
        # Enviar el email
        api_response = brevo_api.send_transac_email(send_smtp_email)
        print(f"Email de confirmación enviado exitosamente a {customer_email}")
        return api_response
        
    except ApiException as e:
        print(f"Error de Brevo API al enviar email: {e}")
        raise
    except Exception as e:
        print(f"Error inesperado al enviar email: {e}")
        raise

def send_cancellation_email(customer_name: str, customer_email: str, service_name: str, appointment_date: datetime, business_name: str):
    """
    Envía un email de notificación de cancelación usando Brevo cuando se cancela un turno.
    """
    if not BREVO_API_KEY:
        print("ADVERTENCIA: BREVO_API_KEY no está configurado. El email no será enviado.")
        return
    
    try:
        # Formatear la fecha del turno
        from datetime import datetime
        fecha_formateada = appointment_date.strftime("%d/%m/%Y")
        hora_formateada = appointment_date.strftime("%H:%M")
        
        # Crear el email
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": customer_email, "name": customer_name}],
            sender={"email": "negosaas@outlook.com", "name": business_name},
            subject=f"❌ Turno Cancelado - {business_name}",
            html_content=f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background: linear-gradient(135deg, #f56565 0%, #c53030 100%); padding: 30px; border-radius: 10px; color: white; text-align: center;">
                        <h1 style="margin: 0; font-size: 28px;">❌ Turno Cancelado</h1>
                    </div>
                    
                    <div style="padding: 30px; background-color: #f9f9f9; border-radius: 10px; margin-top: 20px;">
                        <p style="font-size: 18px; color: #333;">Hola <strong>{customer_name}</strong>,</p>
                        
                        <p style="font-size: 16px; color: #555; line-height: 1.6;">
                            Lamentamos informarte que tu turno con <strong>{business_name}</strong> ha sido <strong style="color: #f56565;">cancelado</strong>.
                        </p>
                        
                        <div style="background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #f56565;">
                            <p style="margin: 5px 0; font-size: 16px; color: #333;"><strong>📋 Servicio:</strong> {service_name}</p>
                            <p style="margin: 5px 0; font-size: 16px; color: #333;"><strong>📅 Fecha:</strong> {fecha_formateada}</p>
                            <p style="margin: 5px 0; font-size: 16px; color: #333;"><strong>🕐 Hora:</strong> {hora_formateada}hs</p>
                        </div>
                        
                        <p style="font-size: 14px; color: #777; margin-top: 30px;">
                            Si tienes alguna consulta o deseas reprogramar, por favor contacta directamente al negocio.
                        </p>
                    </div>
                    
                    <div style="text-align: center; margin-top: 20px; padding: 20px; color: #999; font-size: 12px;">
                        <p>Este es un email automático, por favor no respondas a este mensaje.</p>
                    </div>
                </body>
            </html>
            """
        )
        
        # Enviar el email
        api_response = brevo_api.send_transac_email(send_smtp_email)
        print(f"Email de cancelación enviado exitosamente a {customer_email}")
        return api_response
        
    except ApiException as e:
        print(f"Error de Brevo API al enviar email de cancelación: {e}")
        raise
    except Exception as e:
        print(f"Error inesperado al enviar email de cancelación: {e}")
        raise

@app.delete("/services/{service_id}")
def delete_service(
    service_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    service = db.query(models.Service).filter(
        models.Service.id == service_id,
        models.Service.owner_id == current_user.id
    ).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    db.delete(service)
    db.commit()
    return {"message": "Servicio eliminado"}


class ScheduleSchema(BaseModel):
    day_of_week: str
    is_open: bool
    start_time: str
    end_time: str

@app.get("/schedule")
def get_schedule(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Schedule).filter(models.Schedule.owner_id == current_user.id).all()

@app.post("/schedule")
def update_schedule(schedules: List[ScheduleSchema], db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    # Eliminar solo los horarios del usuario actual
    db.query(models.Schedule).filter(models.Schedule.owner_id == current_user.id).delete()    
    for s in schedules:
        db_schedule = models.Schedule(
            day_of_week=s.day_of_week,
            is_open=s.is_open,
            start_time=s.start_time,
            end_time=s.end_time,
            owner_id=current_user.id
        )
        db.add(db_schedule)
    
    db.commit()
    return {"message": "Horarios actualizados"}

@app.get("/schedule/{slug}")
def get_public_schedule(slug: str, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    
    if not profile.owner.is_active:
        raise HTTPException(status_code=404, detail="Negocio suspendido")

    return db.query(models.Schedule).filter(models.Schedule.owner_id == profile.owner_id).all()

class ProfileSchema(BaseModel):
    name: str
    slug: str
    specialty: str
    bio: str
    avatar_url: str
    monthly_goal: int
    appointment_interval: int

@app.get("/profile")
def get_profile(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    profile = current_user.profile
    if not profile:
        return {
            "name": "", "slug": "", "specialty": "", 
            "bio": "", "avatar_url": "", "monthly_goal": 500000,
            "appointment_interval": 30
        }
    return profile

@app.get("/profile/{slug}")
def get_public_profile(slug: str, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    
    if not profile.owner.is_active:
        raise HTTPException(status_code=404, detail="Perfil suspendido")

    return profile

@app.post("/profile")
def update_profile(data: ProfileSchema, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    profile = current_user.profile
    if not profile:
        profile = models.Profile(owner_id=current_user.id)
        db.add(profile)
    
    profile.name = data.name
    profile.slug = data.slug
    profile.specialty = data.specialty
    profile.bio = data.bio
    profile.avatar_url = data.avatar_url
    profile.monthly_goal = data.monthly_goal
    profile.appointment_interval = data.appointment_interval
    
    db.commit()
    db.refresh(profile)
    return profile

@app.post("/register")
def register_user(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if user:
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    hashed_password = get_password_hash(form_data.password)
    new_user = models.User(username=form_data.username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)    
    default_profile = models.Profile(owner_id=new_user.id, name="Negocio Nuevo", slug=f"negocio-{new_user.id}")
    db.add(default_profile)
    db.commit()
    
    return {"message": f"Usuario {new_user.username} creado exitosamente"}

@app.post("/token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    print(f"Intentando loguear a: {form_data.username}") # DEBUG
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    
    if not user:
        print("RESULTADO: Usuario no encontrado en BD") # DEBUG
        raise HTTPException(
            status_code=401,
            detail="Usuario incorrecto (No existe)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    print(f"Usuario encontrado. Verificando password...") # DEBUG
    is_password_correct = verify_password(form_data.password, user.hashed_password)
    
    if not is_password_correct:
        print("RESULTADO: Password incorrecto") # DEBUG
        raise HTTPException(
            status_code=401,
            detail="Contraseña incorrecta",
            headers={"WWW-Authenticate": "Bearer"},
        )

    print("RESULTADO: Login Exitoso. Generando Token.") # DEBUG
    access_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "is_admin": user.is_admin
    }

@app.post("/upload")
def upload_file(file: UploadFile = File(...), current_user: models.User = Depends(get_current_user)):
    # Generar nombre único
    file_extension = file.filename.split(".")[-1]
    file_name = f"{uuid.uuid4()}.{file_extension}"
    
    # Leer archivo en memoria
    file_content = file.file.read()
    
    # Subir a Supabase
    bucket_name = "Images" 
    try:
        supabase.storage.from_(bucket_name).upload(file_name, file_content, {"content-type": file.content_type})
    except Exception as e:
        print(f"Error subiendo a Supabase: {e}")
        raise HTTPException(status_code=500, detail="Error al subir imagen")

    # Obtener URL pública
    public_url = supabase.storage.from_(bucket_name).get_public_url(file_name)
    
    return {"url": public_url}

@app.get("/finance/history")
def get_finance_history(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_and_close_months(db, current_user.id)
    return db.query(models.MonthlyHistory).filter(models.MonthlyHistory.owner_id == current_user.id).order_by(models.MonthlyHistory.date_code.desc()).all()

def check_and_close_months(db: Session, owner_id: int):
    now = datetime.now()
    first_day_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    old_appointments = db.query(models.Appointment).filter(
        models.Appointment.owner_id == owner_id,
        models.Appointment.date_time < first_day_this_month
    ).all()
    
    if not old_appointments:
        return

    months_to_close = {}
    for apt in old_appointments:
        code = apt.date_time.strftime("%Y-%m")
        if code not in months_to_close:
            months_to_close[code] = {"earnings": 0, "count": 0, "label": apt.date_time.strftime("%B %Y"), "apts": []}
        
        if apt.status in ['completed', 'concretado']:
            months_to_close[code]["earnings"] += (apt.price or 0)
            months_to_close[code]["count"] += 1
        
        months_to_close[code]["apts"].append(apt)

    for code, data in months_to_close.items():
        existing = db.query(models.MonthlyHistory).filter(
            models.MonthlyHistory.owner_id == owner_id,
            models.MonthlyHistory.date_code == code
        ).first()
        
        if not existing:
            new_history = models.MonthlyHistory(
                owner_id=owner_id,
                month_label=data["label"],
                total_earnings=data["earnings"],
                total_appointments=data["count"],
                date_code=code
            )
            db.add(new_history)
        
        for apt in data["apts"]:
            db.delete(apt)
    
    db.commit()

# --- ENDPOINTS DE ADMINISTRADOR ---

# --- ENDPOINTS DE ADMINISTRADOR ---

@app.get("/admin/users")
def list_users(db: Session = Depends(get_db), current_admin: models.User = Depends(get_current_admin)):
    users = db.query(models.User).all()
    result = []
    for u in users:
        result.append({
            "id": u.id,
            "username": u.username,
            "is_admin": u.is_admin,
            "subscription_active": u.subscription_active,
            "created_at": u.created_at,
            "is_active": u.is_active,
            "profile_name": u.profile.name if u.profile else "Sin Perfil"
        })
    return result

@app.put("/admin/users/{user_id}")
def admin_update_user(
    user_id: int, 
    subscription_active: bool = None,
    is_active: bool = None,
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(get_current_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    if subscription_active is not None:
        user.subscription_active = subscription_active
    if is_active is not None:
        user.is_active = is_active
        
    db.commit()
    return {"message": "Usuario actualizado"}

@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db), current_admin: models.User = Depends(get_current_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Borrar perfil y datos relacionados 
    if user.profile: db.delete(user.profile)
    db.delete(user)
    db.commit()
    return {"message": "Usuario eliminado correctamente"}

@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}