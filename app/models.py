from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from .database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    vendedora = "vendedora"


class LocationType(str, enum.Enum):
    deposito = "deposito"
    loja = "loja"


class MovementType(str, enum.Enum):
    entrada = "entrada"
    saida = "saida"
    transferencia = "transferencia"


class ReservationStatus(str, enum.Enum):
    ativa = "ativa"
    confirmada = "confirmada"
    cancelada = "cancelada"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.vendedora, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    movements = relationship("Movement", back_populates="user")
    reservations = relationship("Reservation", back_populates="salesperson")


class Location(Base):
    """Depósitos e Lojas (mostruários)"""
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    type = Column(Enum(LocationType), nullable=False)  # deposito ou loja
    address = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    stocks = relationship("Stock", back_populates="location")
    movements = relationship("Movement", back_populates="location", foreign_keys="Movement.location_id")
    reservations = relationship("Reservation", back_populates="location")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    unit = Column(String(20), default="un")
    min_stock = Column(Integer, default=5)
    cost_price = Column(Float, default=0.0)
    sale_price = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    stocks = relationship("Stock", back_populates="product")
    movements = relationship("Movement", back_populates="product")
    reservations = relationship("Reservation", back_populates="product")


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="stocks")
    location = relationship("Location", back_populates="stocks")


class Movement(Base):
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)  # origem (ou local da entrada/saída)
    destination_id = Column(Integer, ForeignKey("locations.id"), nullable=True)  # só em transferência
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(Enum(MovementType), nullable=False)
    quantity = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="movements")
    location = relationship("Location", back_populates="movements", foreign_keys=[location_id])
    destination = relationship("Location", foreign_keys=[destination_id])
    user = relationship("User", back_populates="movements")


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    salesperson_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    customer_name = Column(String(150), nullable=False)
    customer_phone = Column(String(30), nullable=True)
    status = Column(Enum(ReservationStatus), default=ReservationStatus.ativa)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    product = relationship("Product", back_populates="reservations")
    location = relationship("Location", back_populates="reservations")
    salesperson = relationship("User", back_populates="reservations")
