from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    Text,
    Enum as SQLEnum,
    UniqueConstraint,
    Index,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime
import enum
from backend.core.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Factory(Base):
    __tablename__ = "factories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    contact = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    products = relationship("Product", back_populates="factory", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    products = relationship("Product", back_populates="category_rel")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    # DEPRECATED: хранится для обратной совместимости/отладки.
    # Источник правды: category_id -> categories.id
    category = Column(String(255), nullable=True, index=True)
    subtype = Column(String(255), nullable=False, index=True)
    weight_per_item = Column(Float, default=0.0)
    special_threshold = Column(Float, default=0.0)
    max_per_trip = Column(Float, default=0.0)
    price = Column(Float, nullable=False)
    
    # Связь с заводом
    factory_id = Column(Integer, ForeignKey("factories.id"), nullable=False)
    factory = relationship("Factory", back_populates="products")

    # Связь с категорией (нормализовано)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    category_rel = relationship("Category", back_populates="products")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # Уникальность на уровне каталога товара в рамках завода:
        # в одной категории у одного завода один subtype встречается один раз.
        UniqueConstraint("factory_id", "category_id", "subtype", name="uq_products_factory_category_subtype"),
        Index("ix_products_category_id_subtype", "category_id", "subtype"),
        {"comment": "Товары с привязкой к заводам и категориям"},
    )


class Tariff(Base):
    __tablename__ = "tariffs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # Название транспорта
    capacity = Column(Float, nullable=False)  # Грузоподъёмность (тонны)
    tag = Column(String(50), nullable=False, index=True)  # manipulator / long_haul / special
    weight_if = Column(String(50), nullable=False, default="any")  # any, >20, ≤10 и т.д.
    min_distance = Column(Float, default=0.0)
    max_distance = Column(Float, default=0.0)
    base = Column(Float, nullable=False)  # Базовая цена
    per_km = Column(Float, default=0.0)  # За каждый км
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OrderStatus(str, enum.Enum):
    CONFIRMED_AUTO = "confirmed_auto"
    REJECTED_FOR_MANUAL = "rejected_for_manual"
    CONFIRMED_MANUAL = "confirmed_manual"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(SQLEnum(OrderStatus), nullable=False, index=True)

    # Снимок входного запроса /quote и рассчитанных вариантов (чтобы видеть историю как было)
    request_payload = Column(JSON, nullable=False)
    variants_snapshot = Column(JSON, nullable=True)
    selected_variant = Column(Integer, nullable=True)
    selected_variant_snapshot = Column(JSON, nullable=True)

    needs_logistics_check = Column(Boolean, default=False, nullable=False)
    warning_text = Column(String(255), nullable=True)

    # Ручное подтверждение логистом/админом
    manual_payload = Column(JSON, nullable=True)
    manual_transport_name = Column(String(255), nullable=True)
    manual_notes = Column(Text, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by = relationship("User")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    events = relationship("OrderEvent", back_populates="order", cascade="all, delete-orphan")


class OrderEvent(Base):
    __tablename__ = "order_events"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    payload = Column(JSON, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("User")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="events")
