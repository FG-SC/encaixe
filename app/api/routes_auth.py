"""Login by e-mail link (no passwords) and who is logged in."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlmodel import Session

from app.auth import (
    close_session,
    me_payload,
    optional_account,
    request_login,
    set_session_cookie,
    verify_login,
)
from app.db import get_session
from app.models import Account

router = APIRouter(prefix="/api", tags=["auth"])

SENT_TEXT = "Se o e-mail estiver certo, o link chega em instantes. Confira também o spam e as promoções."


class LoginRequestIn(BaseModel):
    email: str


@router.post("/auth/request")
def auth_request(body: LoginRequestIn, session: Session = Depends(get_session)) -> dict:
    request_login(session, body.email)
    return {"sent": True, "message": SENT_TEXT}


class VerifyIn(BaseModel):
    token: str
    accept_terms: bool = False


@router.post("/auth/verify")
def auth_verify(body: VerifyIn, response: Response, session: Session = Depends(get_session)) -> dict:
    account, token = verify_login(session, body.token, body.accept_terms)
    session.commit()
    set_session_cookie(response, token)
    return me_payload(session, account)


@router.post("/auth/logout")
def auth_logout(request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    close_session(session, request, response)
    session.commit()
    return {"ok": True}


@router.get("/me")
def me(account: Account | None = Depends(optional_account), session: Session = Depends(get_session)) -> dict:
    return me_payload(session, account)
