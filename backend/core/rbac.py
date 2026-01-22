import os
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.auth import get_current_active_user
from backend.core.database import get_db
from backend.models.db_models import OrgRole, Organization, OrganizationMember, User


ROLE_RANK: dict[str, int] = {
    "viewer": 10,
    "manager": 20,
    "logist": 30,
    "admin": 40,
    "owner": 50,
}


def _role_value(role: OrgRole | str | None) -> str:
    if role is None:
        return ""
    return (role.value if hasattr(role, "value") else str(role)).strip().lower()


def org_role_rank(role: OrgRole | str | None) -> int:
    return ROLE_RANK.get(_role_value(role), 0)


def default_org(db: Session) -> Organization:
    """Single-tenant fallback: используем org по умолчанию (создаётся на startup)."""
    name = os.getenv("DEFAULT_ORG_NAME", "Default")
    org = db.query(Organization).filter(Organization.name == name).first()
    if org:
        return org
    org = db.query(Organization).order_by(Organization.id.asc()).first()
    if not org:
        raise HTTPException(status_code=500, detail="Организация не инициализирована")
    return org


def get_user_org_role(db: Session, user: User) -> Optional[OrgRole]:
    org = default_org(db)
    m = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == org.id, OrganizationMember.user_id == user.id)
        .first()
    )
    if not m or not m.is_active:
        return None
    return m.role


def require_org_min(min_role: OrgRole):
    """Dependency: доступ только пользователям с ролью в org >= min_role."""

    async def _dep(
        current_user: User = Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ) -> User:
        role = get_user_org_role(db, current_user)
        if not role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Org access required")
        if org_role_rank(role) < org_role_rank(min_role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
        return current_user

    return _dep

