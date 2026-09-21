from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ...db import get_db
from ...gmail import auth as gmail_auth
from ...models import User, UserRole
from ...security import create_access_token, hash_password, require_admin, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"access_token": create_access_token(user), "token_type": "bearer", "role": user.role.value}


@router.post("/users", dependencies=[Depends(require_admin)])
def create_user(email: str, name: str, password: str, role: UserRole = UserRole.VIEWER, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="User already exists")
    user = User(email=email, name=name, hashed_password=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": user.user_id, "email": user.email, "role": user.role.value}


@router.get("/gmail/authorize", dependencies=[Depends(require_admin)])
def gmail_authorize():
    """Returns the Google consent URL. No password is ever collected - the
    admin opens this URL in a browser and grants read-only Gmail access."""
    url, state = gmail_auth.get_authorization_url()
    return {"authorization_url": url, "state": state}


@router.get("/gmail/callback")
def gmail_callback(code: str, state: str, mailbox_email: str, db: Session = Depends(get_db)):
    record = gmail_auth.exchange_code_for_tokens(db, code, state, mailbox_email)
    return {"connected": True, "mailbox_email": record.mailbox_email}
