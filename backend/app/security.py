"""JWT authentication + role-based access control (spec section 20).

Roles: ADMIN, FINANCE, PROCUREMENT, VIEWER. Enforced via FastAPI dependencies
so each router declares the minimum role it needs instead of checking manually.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ROLE_RANK = {UserRole.VIEWER: 0, UserRole.PROCUREMENT: 1, UserRole.FINANCE: 1, UserRole.ADMIN: 2}

# Calling bcrypt directly (no passlib) - passlib is unmaintained and probes a
# bcrypt internal (__about__.__version__) that current bcrypt releases no
# longer have, breaking every hash/verify call. bcrypt itself has a hard
# 72-byte input limit, so the password is truncated to that before hashing;
# this matches passlib's own default behavior for the bcrypt backend.


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))


def create_access_token(user: User) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user.user_id, "role": user.role.value, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    if not token:
        raise credentials_error
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
    except JWTError:
        raise credentials_error
    user = db.query(User).filter(User.user_id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise credentials_error
    return user


def require_role(minimum: UserRole):
    def _check(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum] and user.role != UserRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user
    return _check


require_viewer = require_role(UserRole.VIEWER)
require_procurement = require_role(UserRole.PROCUREMENT)
require_admin = require_role(UserRole.ADMIN)
