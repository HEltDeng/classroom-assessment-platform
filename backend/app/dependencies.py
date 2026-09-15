from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import MemberRole, OrganizationMember, OrganizationStatus, User
from .security import decode_access_token


bearer = HTTPBearer(auto_error=False)


def user_from_token(db: Session, token: str | None) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or missing")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    return user_from_token(db, credentials.credentials if credentials else None)


def get_current_membership(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    organization_header_id: str | None = Header(default=None, alias="X-Organization-Id"),
) -> tuple[User, OrganizationMember]:
    query = select(OrganizationMember).where(
        OrganizationMember.user_id == user.id,
        OrganizationMember.organization.has(status=OrganizationStatus.ACTIVE),
    )
    if organization_header_id:
        query = query.where(OrganizationMember.organization_id == organization_header_id)
    membership = db.scalar(query.order_by(OrganizationMember.created_at))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active organization membership")
    return user, membership


def require_admin(context: tuple[User, OrganizationMember] = Depends(get_current_membership)) -> tuple[User, OrganizationMember]:
    user, membership = context
    if membership.role not in {MemberRole.OWNER, MemberRole.ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient organization role")
    return context
