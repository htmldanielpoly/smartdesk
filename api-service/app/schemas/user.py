from pydantic import BaseModel, EmailStr

from app.models.enums import Role


class UserOut(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: Role
    department: str | None = None


class RoleUpdate(BaseModel):
    role: Role
