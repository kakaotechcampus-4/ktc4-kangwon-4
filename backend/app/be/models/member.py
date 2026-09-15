from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel


class Member(SQLModel, table=True):
    __tablename__ = "members"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    oauth_id: str = Field(max_length=255, unique=True, description="카카오 회원번호")
    nickname: str = Field(max_length=255, description="카카오 닉네임")
    refresh_token: str | None = Field(default=None, max_length=512)

    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now())
    )
