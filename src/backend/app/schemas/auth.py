from pydantic import BaseModel, EmailStr, Field, field_validator
import uuid


_MIN_PASSWORD_LENGTH = 10


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=_MIN_PASSWORD_LENGTH, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=60)
    # Optional — a valid code grants a free account immediately. Without one,
    # the account is created but gated (access_granted=False) until the user
    # completes a Stripe subscription checkout (POST /api/billing/checkout).
    promo_code: str | None = Field(None, max_length=50)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < _MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters")
        return v

    @field_validator("display_name")
    @classmethod
    def display_name_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Display name cannot be blank")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=_MIN_PASSWORD_LENGTH, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < _MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    display_name: str
    access_granted: bool = True


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    avatar_data: str | None
    access_granted: bool
    access_source: str | None
    # Computed, not stored — see app/api/deps.py::require_admin. Frontend
    # uses this only to decide whether to show the Feedback Inbox nav link;
    # the actual gate is enforced server-side on those routes regardless.
    is_admin: bool = False
    has_completed_tutorial: bool = False

    model_config = {"from_attributes": True}
