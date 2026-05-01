from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


class AuthUser(BaseModel):
    id: int
    name: str
    email: str


class AuthResponse(BaseModel):
    message: str
    user: AuthUser


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_code: str
    expires_in_minutes: int


class GenericMessageResponse(BaseModel):
    message: str
