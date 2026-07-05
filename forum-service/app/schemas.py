from datetime import datetime

from pydantic import BaseModel, Field


class BoardOut(BaseModel):
    slug: str
    name: str
    category: str
    thread_count: int


class ThreadCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)


class ThreadModerate(BaseModel):
    """AGENT/ADMIN moderation flags. Omitted fields are left unchanged."""

    locked: bool | None = None
    pinned: bool | None = None


class ThreadOut(BaseModel):
    id: str
    board_slug: str
    title: str
    author_id: str
    author_role: str
    created_at: datetime
    last_post_at: datetime
    post_count: int
    locked: bool
    pinned: bool


class ThreadPage(BaseModel):
    """Paginated thread listing for a board."""

    items: list[ThreadOut]
    page: int
    page_size: int
    total: int


class PostCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class PostOut(BaseModel):
    id: str
    thread_id: str
    author_id: str
    author_role: str
    body: str
    deleted: bool
    created_at: datetime


class ThreadDetail(BaseModel):
    thread: ThreadOut
    posts: list[PostOut]
