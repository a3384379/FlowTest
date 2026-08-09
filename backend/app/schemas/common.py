from pydantic import BaseModel, Field


class Page[ItemT](BaseModel):
    items: list[ItemT]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
