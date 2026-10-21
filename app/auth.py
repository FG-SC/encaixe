"""Magic-link login and the access rules of every route (RULES.auth).

- A login link carries a random one-time token in the URL fragment (``/entrar#t=…``): fragments never reach the
  server, so the token stays out of logs and Referer headers. The page posts it back (``POST /api/auth/verify``):
  e-mail scanners that open links cannot spend it, and nobody can log someone else into their account.
- Only sha256 hashes of tokens are stored; there is no signing secret to keep or rotate.
- The session is an HttpOnly, SameSite=Lax cookie (Secure in production). Nothing that changes state is a GET,
  and JSON bodies need a CORS preflight the API never grants, so Lax is enough against CSRF.
- Expirations use ``clock.real_now()``: the demo clock never expires or extends a session.
- A profile id in a path that is not the logged account's answers 404, so ids cannot be probed.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlmodel import Session, func, select

from app import clock, mailer
from app.config import RULES, get_settings
from app.db import get_session
from app.jobs import company_name
from app.models import Account, AuthSession, Candidate, Job, LoginToken, Recruiter

COOKIE = "encaixe_session"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if len(value) > 254 or not _EMAIL.match(value):
        raise HTTPException(422, "e-mail inválido")
    return value


def account_by_email(session: Session, email: str) -> Account | None:
    return session.exec(select(Account).where(Account.email == email)).first()


# --------------------------------------------------------------------------- login link


def request_login(session: Session, email: str) -> None:
    """Send a one-time login link (rate-limited). Says nothing about whether the e-mail has an account."""
    email = normalize_email(email)
    settings = get_settings()
    if settings.allowed_emails and email not in settings.allowed_emails:
        raise HTTPException(403, "o Encaixe está em beta fechado: peça um convite")
    rules, now = RULES.auth, clock.real_now()
    recent = session.exec(
        select(LoginToken.created_at).where(
            LoginToken.email == email, LoginToken.created_at > now - timedelta(hours=1)
        )
    ).all()
    if any(t > now - timedelta(seconds=rules.min_seconds_between_links) for t in recent):
        raise HTTPException(429, "acabamos de enviar um link: confira sua caixa de entrada e o spam")
    if len(recent) >= rules.max_links_per_hour:
        raise HTTPException(429, "muitos pedidos de link para este e-mail: tente de novo em uma hora")
    today = session.exec(
        select(func.count()).select_from(LoginToken).where(LoginToken.created_at > now - timedelta(days=1))
    ).one()
    if today >= rules.max_links_per_day:
        raise HTTPException(429, "limite diário de e-mails atingido: tente de novo amanhã")
    token = secrets.token_urlsafe(32)
    session.add(
        LoginToken(
            token_hash=_hash(token),
            email=email,
            created_at=now,
            expires_at=now + timedelta(minutes=rules.login_link_minutes),
        )
    )
    session.commit()
    link = f"{settings.base_url}/entrar#t={token}"
    mailer.send(
        email,
        "Seu link de acesso ao Encaixe",
        f"Olá!\n\nPara entrar no Encaixe, abra o link abaixo (vale por {rules.login_link_minutes} minutos e só "
        f"uma vez):\n\n{link}\n\nSe você não pediu este acesso, ignore este e-mail.\n",
    )


def verify_login(session: Session, token: str, accept_terms: bool) -> tuple[Account, str]:
    """Spend a login link and open a session. New accounts (and new terms) need ``accept_terms``."""
    row = session.get(LoginToken, _hash(token or ""))
    now = clock.real_now()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise HTTPException(400, "link inválido ou expirado: peça um novo")
    account = account_by_email(session, row.email)
    needs_terms = account is None or account.terms_version != RULES.auth.terms_version
    if needs_terms and not accept_terms:
        raise HTTPException(409, "terms_required")  # the link is not spent: the page asks and posts again
    row.used_at = now
    session.add(row)
    if account is None:
        account = Account(email=row.email)
    if needs_terms:
        account.terms_version, account.terms_accepted_at = RULES.auth.terms_version, now
    session.add(account)
    session.flush()
    return account, open_session(session, account)


def open_session(session: Session, account: Account) -> str:
    token = secrets.token_urlsafe(32)
    now = clock.real_now()
    session.add(
        AuthSession(
            token_hash=_hash(token),
            account_id=account.id,  # type: ignore[arg-type]
            created_at=now,
            expires_at=now + timedelta(days=RULES.auth.session_days),
        )
    )
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=RULES.auth.session_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=get_settings().is_prod,
        path="/",
    )


def close_session(session: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        row = session.get(AuthSession, _hash(token))
        if row is not None:
            session.delete(row)
    response.delete_cookie(COOKIE, path="/")


def close_all_sessions(session: Session, account_id: int) -> None:
    for row in session.exec(select(AuthSession).where(AuthSession.account_id == account_id)).all():
        session.delete(row)


# --------------------------------------------------------------------------- dependencies


def optional_account(request: Request, session: Session = Depends(get_session)) -> Account | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    row = session.get(AuthSession, _hash(token))
    if row is None or row.expires_at <= clock.real_now():
        return None
    return session.get(Account, row.account_id)


def current_account(account: Account | None = Depends(optional_account)) -> Account:
    if account is None:
        raise HTTPException(401, "entre com seu e-mail para continuar")
    return account


def owned_candidate(
    candidate_id: int, account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> Candidate:
    cand = session.get(Candidate, candidate_id) if account.candidate_id == candidate_id else None
    if cand is None:
        raise HTTPException(404, "candidato não encontrado")
    return cand


def owned_recruiter(
    rid: int, account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> Recruiter:
    rec = session.get(Recruiter, rid) if account.recruiter_id == rid else None
    if rec is None:
        raise HTTPException(404, "recrutador não encontrado")
    return rec


def owned_job(jid: int, rec: Recruiter = Depends(owned_recruiter), session: Session = Depends(get_session)) -> Job:
    job = session.get(Job, jid)
    if job is None or job.owner_recruiter_id != rec.id:
        raise HTTPException(404, "vaga não encontrada para este recrutador")
    return job


def session_recruiter(account: Account = Depends(current_account), session: Session = Depends(get_session)) -> Recruiter:
    """The logged account's recruiter profile (routes without a recruiter id in the path)."""
    rec = session.get(Recruiter, account.recruiter_id) if account.recruiter_id is not None else None
    if rec is None:
        raise HTTPException(403, "crie seu perfil de recrutador primeiro")
    return rec


def dev_only() -> None:
    """Lists of every profile exist for the local demo only."""
    if get_settings().is_prod:
        raise HTTPException(404)


def me_payload(session: Session, account: Account | None) -> dict:
    settings = get_settings()
    out: dict = {"account": None, "dev": not settings.is_prod, "source_url": settings.source_url}
    if account is not None:
        rec = session.get(Recruiter, account.recruiter_id) if account.recruiter_id is not None else None
        out["account"] = {
            "email": account.email,
            "candidate_id": account.candidate_id,
            "recruiter_id": account.recruiter_id,
            "terms_version": account.terms_version,
            "recruiter": None
            if rec is None
            else {"id": rec.id, "name": rec.name, "company": company_name(session, rec.company_id)},
        }
    return out
