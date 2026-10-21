from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TopicBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=150)
    subject: str = Field(..., pattern=r"^(OS|DBMS)$")
    is_active: bool = True


class TopicCreate(TopicBase):
    pass


class TopicRead(TopicBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
