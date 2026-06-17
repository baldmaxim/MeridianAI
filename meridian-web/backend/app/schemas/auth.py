"""Auth schemas."""

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None
    department: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminUserUpdate(BaseModel):
    """Частичное обновление пользователя админом. Все поля опциональны."""

    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    display_name: str | None
    department: str | None = None
    is_active: bool
    # Доступные роли страницы (ключи каталога) — заполняется в /auth/me.
    allowed_pages: list[str] = []
    # Набор роли "user" — для превью режима «смотреть как пользователь» (только admin).
    user_role_pages: list[str] | None = None

    model_config = {"from_attributes": True}
