from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    username: str
    is_active: bool

    class Config:
        from_attributes = True
