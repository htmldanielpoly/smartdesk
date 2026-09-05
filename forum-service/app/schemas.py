from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, Field

# A single media URL: a path like "/media/<uuid>.png", never free-form text.
MediaUrl = Annotated[str, Field(max_length=500)]
# Cap on how many attachments one post/thread/message can carry.
MAX_MEDIA_URLS = 10

class BoardOut(BaseModel):
    slug: str
    name: str
    category: str
    thread_count: int

class ThreadCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)
    media_urls: list[MediaUrl] = Field(default_factory=list, max_length=MAX_MEDIA_URLS)
    is_anonymous: bool = Field(default=False)

class ThreadModerate(BaseModel):
    """AGENT/ADMIN moderation flags. Omitted fields are left unchanged."""
    locked: bool | None = None
    pinned: bool | None = None

class ThreadOut(BaseModel):
    id: str
    board_slug: str
    title: str
    # Made optional so the backend can omit them if is_anonymous is True
    author_id: str | None = None
    author_role: str | None = None
    is_anonymous: bool = False
    created_at: datetime
    last_post_at: datetime
    post_count: int
    locked: bool
    pinned: bool
    media_urls: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)

class ThreadPage(BaseModel):
    """Paginated thread listing for a board."""
    items: list[ThreadOut]
    page: int
    page_size: int
    total: int

class PostCreate(BaseModel):
    body: str = Field(default="", max_length=5000)
    media_urls: list[MediaUrl] = Field(default_factory=list, max_length=MAX_MEDIA_URLS)
    is_anonymous: bool = Field(default=False)

class PostOut(BaseModel):
    id: str
    thread_id: str
    # Made optional so the backend can omit them if is_anonymous is True
    author_id: str | None = None
    author_role: str | None = None
    is_anonymous: bool = False
    body: str
    media_urls: list[str] = Field(default_factory=list)
    deleted: bool
    created_at: datetime
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)

class ThreadDetail(BaseModel):
    thread: ThreadOut
    posts: list[PostOut]

# --- Direct Messages ---

class DirectMessageCreate(BaseModel):
    recipient_id: str
    content: str = Field(default="", max_length=2000)
    media_urls: list[MediaUrl] = Field(default_factory=list, max_length=MAX_MEDIA_URLS)

class DirectMessageOut(BaseModel):
    id: str
    sender_id: str
    recipient_id: str
    content: str
    media_urls: list[str]
    created_at: datetime
    is_read: bool