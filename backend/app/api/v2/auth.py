import re
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from app.tenancy.auth import COOKIE, check_origin, get_current_user, set_session_cookie
from app.tenancy.repository import tenant_repository

router = APIRouter(prefix="/api/v2/auth", tags=["V2 identity"])
hasher = PasswordHasher()
# Dummy verification reduces the timing difference between unknown emails and bad passwords.
dummy_hash = hasher.hash("not-an-account-password")


def normalize_email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Enter a valid email address.")
    return value


class Login(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)
    _email = field_validator("email")(normalize_email)


class Signup(Login):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Name is required.")
        return value.strip()


@router.post("/signup", status_code=201)
def signup(body: Signup, request: Request, response: Response):
    check_origin(request)
    # Check availability before expensive hashing; the unique constraint resolves races.
    if tenant_repository.find_user(email=body.email):
        raise HTTPException(409, "An account with this email already exists.")
    user = tenant_repository.create_user(body.email, body.name, hasher.hash(body.password))
    old = request.cookies.get(COOKIE)
    tenant_repository.logout(old)
    set_session_cookie(response, tenant_repository.new_session(user["id"]))
    return user


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    check_origin(request)
    user = tenant_repository.find_user(email=body.email)
    try:
        hasher.verify(user["password_hash"] if user and user["password_hash"] else dummy_hash, body.password)
    except (VerificationError, InvalidHashError):
        raise HTTPException(401, "Email or password does not match.") from None
    if not user or not user["password_hash"]:
        raise HTTPException(401, "Email or password does not match.")
    if hasher.check_needs_rehash(user["password_hash"]):
        with tenant_repository.transaction() as cur:
            tenant_repository.execute(cur, "UPDATE thread_users SET password_hash=%s WHERE id=%s", (hasher.hash(body.password), user["id"]))
    tenant_repository.logout(request.cookies.get(COOKIE))
    set_session_cookie(response, tenant_repository.new_session(user["id"]))
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


@router.get("/me")
def me(response: Response, user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    organizations = tenant_repository.organizations(user["user_id"])
    active = user["active_organization_id"]
    if not any(org["id"] == active for org in organizations):
        active = None
    return {"user": {"id": user["user_id"], "name": user["name"], "email": user["email"]},
            "active_organization_id": active, "organizations": organizations}


@router.post("/logout")
def logout(request: Request, response: Response):
    check_origin(request)
    tenant_repository.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie("thread_session", path="/")
    return {"authenticated": False}
