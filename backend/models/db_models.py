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
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# === B2B: Organizations / Memberships / Invites =================================

class OrgRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    LOGIST = "logist"
    MANAGER = "manager"
    VIEWER = "viewer"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    invites = relationship("OrganizationInvite", back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    role = Column(SQLEnum(OrgRole), default=OrgRole.MANAGER, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="members")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_members_org_user"),
    )


class OrganizationInvite(Base):
    __tablename__ = "organization_invites"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    email = Column(String(255), nullable=False, index=True)
    role = Column(SQLEnum(OrgRole), default=OrgRole.MANAGER, nullable=False)

    # store only hash of token for safety
    token_hash = Column(String(128), nullable=False, unique=True, index=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)

    accepted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    accepted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    accepted_by = relationship("User", foreign_keys=[accepted_by_user_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="invites")


class Factory(Base):
    __tablename__ = "factories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    contact = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
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
    is_active = Column(Boolean, nullable=False, default=True)
    
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
    # DEPRECATED (legacy): строковое условие веса из Google Sheet (any, >20, ≤10 ...)
    # Новый формат: weight_condition + weight_threshold
    weight_if = Column(String(50), nullable=False, default="any")
    # Новый формат веса: условие и порог (например: condition="le", threshold=20.0)
    weight_condition = Column(String(10), nullable=False, default="any")  # any | le | gt
    weight_threshold = Column(Float, nullable=True)  # null/0 => не используется
    min_distance = Column(Float, default=0.0)
    max_distance = Column(Float, default=0.0)
    base = Column(Float, nullable=False)  # Базовая цена
    per_km = Column(Float, default=0.0)  # За каждый км после достижения max_distance (если разрешено)
    # Ограничение по радиусу: если задано, транспорт нельзя использовать дальше этого расстояния
    radius_limit_km = Column(Float, nullable=True)
    # Координаты центра, от которого считается радиус (если задан radius_limit_km)
    radius_center_lat = Column(Float, nullable=True)
    radius_center_lon = Column(Float, nullable=True)
    # Разделение транспорта: доставка vs разгрузка (будет расширяться)
    service_type = Column(String(20), nullable=False, default="delivery")  # delivery | unloading
    # Новый “тег”: самозагрузка (Y/N)
    self_loading = Column(Boolean, nullable=False, default=False)
    # Возможность разгрузки: (legacy single) кран / манипулятор / нельзя
    unload_capability = Column(String(20), nullable=False, default="none")  # none | crane | manipulator
    # Возможность разгрузки (multi): список тегов (например ["crane","manipulator"])
    unload_tags = Column(JSON, nullable=True)
    # Возможность отключать тариф без удаления
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    # Контейнеровоз: связь с базовым транспортом, от которого берётся цена (например, шаланда)
    # Храним как (name, tag), потому что тарифные строки дублируются по диапазонам/весовым условиям.
    base_transport_name = Column(String(255), nullable=True)
    base_transport_tag = Column(String(50), nullable=True)

    # Аудит: кто создал / кто последний изменил
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    updated_by = relationship("User", foreign_keys=[updated_by_user_id])
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TariffChangeLog(Base):
    __tablename__ = "tariff_change_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Не FK: хотим сохранять id даже после удаления тарифа
    tariff_id = Column(Integer, nullable=True, index=True)
    tariff_name = Column(String(255), nullable=True, index=True)

    action = Column(String(20), nullable=False, index=True)  # create|update|delete
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("User")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


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
