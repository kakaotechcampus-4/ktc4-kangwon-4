from pydantic import BaseModel


class LoginRequest(BaseModel):
    code: str
