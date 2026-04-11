from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr

from app.api.deps import DbSession, get_current_user, issue_csrf_token
from app.auth.api_tokens import create_user_api_token, decode_scopes, revoke_user_api_token
from app.auth.csrf import clear_csrf_cookie
from app.auth.passwords import verify_password
from app.auth.sessions import create_user_session, revoke_session
from app.auth.users import get_user_by_email
from app.core.config import settings
from app.db.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    uuid: str
    email: EmailStr
    display_name: str | None
    is_admin: bool


class CsrfResponse(BaseModel):
    csrf_token: str


class ApiTokenCreateRequest(BaseModel):
    name: str
    scopes: list[str] | None = None


class ApiTokenCreateResponse(BaseModel):
    uuid: str
    name: str
    scopes: list[str]
    token: str


def user_response(user: User) -> UserResponse:
    return UserResponse(
        uuid=user.uuid,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_expire_days * 24 * 60 * 60,
        path="/",
    )


def authenticate_local_user(db: DbSession, email: str, password: str) -> User:
    if settings.auth_mode not in ("local", "mixed"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local auth is disabled")

    user = get_user_by_email(db, email)
    if user is None or user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return user


def create_login_session(
    db: DbSession,
    user: User,
    *,
    request: Request,
    response: Response,
) -> None:
    token, _ = create_user_session(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    set_session_cookie(response, token)


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession) -> UserResponse:
    user = authenticate_local_user(db, payload.email, payload.password)
    create_login_session(db, user, request=request, response=response)
    return user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbSession,
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> None:
    if session_token:
        revoke_session(db, session_token)
        db.commit()

    response.delete_cookie(settings.session_cookie_name, path="/")
    clear_csrf_cookie(response)


@router.get("/me", response_model=UserResponse)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return user_response(current_user)


@router.get("/csrf", response_model=CsrfResponse)
def csrf(response: Response) -> CsrfResponse:
    return CsrfResponse(csrf_token=issue_csrf_token(response))


@router.post("/api-tokens", response_model=ApiTokenCreateResponse, status_code=status.HTTP_201_CREATED)
def create_api_token(
    payload: ApiTokenCreateRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ApiTokenCreateResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token name is required")

    try:
        raw_token, api_token = create_user_api_token(
            db,
            current_user,
            name=name,
            scopes=payload.scopes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    return ApiTokenCreateResponse(
        uuid=api_token.uuid,
        name=api_token.name,
        scopes=decode_scopes(api_token.scopes),
        token=raw_token,
    )


@router.delete("/api-tokens/{token_uuid}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_token(
    token_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    if not revoke_user_api_token(db, current_user, token_uuid):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")

    db.commit()
