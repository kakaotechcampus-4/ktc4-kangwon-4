from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel


class CreatedAtMixin(SQLModel):
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_type=DateTime,
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_type=DateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
        nullable=False,
    )
