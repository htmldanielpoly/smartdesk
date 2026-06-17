from pydantic import BaseModel, EmailStr, Field

from app.models.enums import Role


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    # Self-registration only ever creates regular users. Elevated roles are
    # granted by an admin via the admin endpoints.


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
