from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import hashlib
import os
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, EmailStr
from typing import Optional

from backend.core.database import get_db
from backend.core.auth import (
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_password_hash,
    get_user_by_username,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from backend.models.db_models import OrganizationInvite, OrganizationMember, OrgRole, User, UserRole
from backend.core.logger import get_logger

router = APIRouter(tags=["auth"])
log = get_logger("routes.auth")


class Token(BaseModel):
    access_token: str
    token_type: str


class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[UserRole] = UserRole.USER


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    orgRole: Optional[str] = None
    role: UserRole
    is_active: bool

    class Config:
        from_attributes = True


@router.post("/auth/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Вход в систему через OAuth2 form (для совместимости с Swagger).
    Возвращает JWT токен.
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value},
        expires_delta=access_token_expires
    )
    
    log.info(f"User {user.username} logged in")
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/auth/login/json", response_model=Token)
async def login_json(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Вход в систему через JSON (для фронтенда).
    Возвращает JWT токен.
    """
    user = authenticate_user(db, login_data.username, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value},
        expires_delta=access_token_expires
    )
    
    log.info(f"User {user.username} logged in")
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/auth/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Регистрация нового пользователя (опционально, можно отключить в продакшене).
    """
    # Проверяем, существует ли пользователь
    if get_user_by_username(db, user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Создаём нового пользователя
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        username=user_data.username,
        email=user_data.email,
        first_name=(user_data.first_name or None),
        last_name=(user_data.last_name or None),
        hashed_password=hashed_password,
        role=user_data.role or UserRole.USER,
        is_active=True
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    log.info(f"New user registered: {db_user.username}")
    return {
        "id": db_user.id,
        "username": db_user.username,
        "email": db_user.email,
        "firstName": getattr(db_user, "first_name", None),
        "lastName": getattr(db_user, "last_name", None),
        "orgRole": None,
        "role": db_user.role,
        "is_active": bool(db_user.is_active),
    }


@router.get("/auth/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Получение информации о текущем пользователе.
    """
    # org role (single-tenant default org)
    from backend.core.rbac import default_org

    org = default_org(db)
    m = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == org.id, OrganizationMember.user_id == current_user.id)
        .first()
    )
    org_role = (m.role.value if (m and hasattr(m.role, "value")) else (m.role if m else None))
    if m and not m.is_active:
        org_role = None

    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "firstName": getattr(current_user, "first_name", None),
        "lastName": getattr(current_user, "last_name", None),
        "orgRole": org_role,
        "role": current_user.role,
        "is_active": bool(current_user.is_active),
    }


class InviteAcceptRequest(BaseModel):
    token: str
    username: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


def _hash_invite_token(raw_token: str) -> str:
    salt = os.getenv("INVITE_TOKEN_SALT", "invite-salt-change-me")
    return hashlib.sha256((salt + "::" + (raw_token or "")).encode("utf-8")).hexdigest()


@router.post("/auth/invite/accept", response_model=Token)
async def accept_invite(
    payload: InviteAcceptRequest,
    db: Session = Depends(get_db),
):
    token = (payload.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token обязателен")

    token_hash = _hash_invite_token(token)
    inv = db.query(OrganizationInvite).filter(OrganizationInvite.token_hash == token_hash).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Инвайт не найден")
    if inv.revoked_at:
        raise HTTPException(status_code=400, detail="Инвайт отозван")
    if inv.accepted_at:
        raise HTTPException(status_code=400, detail="Инвайт уже использован")
    if inv.expires_at and inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Инвайт истёк")

    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username обязателен")
    if get_user_by_username(db, username):
        raise HTTPException(status_code=400, detail="Username already registered")
    if inv.email and db.query(User).filter(User.email == inv.email).first():
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    # создаём пользователя как USER (глобальная роль остаётся простой), роль в org задаётся membership
    hashed_password = get_password_hash(payload.password)
    first_name = (payload.first_name or "").strip() or None
    last_name = (payload.last_name or "").strip() or None
    user = User(
        username=username,
        email=inv.email,
        first_name=first_name,
        last_name=last_name,
        hashed_password=hashed_password,
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.flush()

    role = inv.role or OrgRole.MANAGER
    db.add(
        OrganizationMember(
            organization_id=inv.organization_id,
            user_id=user.id,
            role=role,
            is_active=True,
        )
    )

    inv.accepted_at = datetime.now(timezone.utc)
    inv.accepted_by_user_id = user.id
    db.add(inv)
    db.commit()

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
