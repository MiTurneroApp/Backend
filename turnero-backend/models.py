from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_admin = Column(Boolean, default=False)
    subscription_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    profile = relationship("Profile", back_populates="owner", uselist=False)
    services = relationship("Service", back_populates="owner")
    appointments = relationship("Appointment", back_populates="owner")
    schedules = relationship("Schedule", back_populates="owner")
    monthly_history = relationship("MonthlyHistory", back_populates="owner")

class Profile(Base):
    __tablename__ = "profile"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    name = Column(String, default="Mi Barbería")
    slug = Column(String, unique=True, index=True)
    specialty = Column(String)
    bio = Column(String)
    avatar_url = Column(String)
    monthly_goal = Column(Integer, default=500000)
    appointment_interval = Column(Integer, default=30)
    
    owner = relationship("User", back_populates="profile")

class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    name = Column(String)
    price = Column(Integer)
    duration = Column(Integer)
    
    owner = relationship("User", back_populates="services")
    appointments = relationship("Appointment", back_populates="service")

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    service_id = Column(Integer, ForeignKey("services.id"))
    
    customer_name = Column(String)
    customer_email = Column(String)
    customer_phone = Column(String)
    date_time = Column(DateTime)
    price = Column(Integer)
    status = Column(String, default="pending")
    
    owner = relationship("User", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")

class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    day_of_week = Column(String)
    is_open = Column(Boolean, default=True)
    start_time = Column(String)
    end_time = Column(String)
    
    owner = relationship("User", back_populates="schedules")

class MonthlyHistory(Base):
    __tablename__ = "monthly_history"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    month_label = Column(String) # Ejemplo: "Febrero 2026"
    total_earnings = Column(Integer)
    total_appointments = Column(Integer)
    date_code = Column(String) # Ejemplo: "2026-02" para evitar duplicados
    
    owner = relationship("User", back_populates="monthly_history")