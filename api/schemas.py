from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class HealthOut(BaseModel):
    status: Literal["ok"]
    db: Literal["ok", "unavailable"]
    db_error: str | None = None


class MessageOut(BaseModel):
    message: str


class SubscribeSource(str, Enum):
    """Known subscription sources. Constrains the `source` field to prevent
    arbitrary strings from being stored in the database."""
    COMING_SOON = "coming_soon"
    BLOG = "blog"
    LANDING_PAGE = "landing_page"
    FOOTER = "footer"


class SubscribeIn(BaseModel):
    email: EmailStr
    source: SubscribeSource = SubscribeSource.COMING_SOON
    cf_turnstile_token: str | None = Field(default=None, max_length=2048)


class PostSummary(BaseModel):
    id: int
    uuid: str
    title: str
    slug: str
    excerpt: str | None
    image_url: str | None
    author: str
    published_at: datetime | None


class PostDetail(PostSummary):
    content_html: str
    image_credit: str | None
    tags: list[str] = []
    categories: list[str] = []


class TagOut(BaseModel):
    id: int
    name: str
    slug: str


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    parent_id: int | None


class PostList(BaseModel):
    posts: list[PostSummary]
    total: int
    page: int
    pages: int
    per_page: int


class PostRevisionOut(BaseModel):
    id: int
    title: str
    excerpt: str | None
    revised_at: datetime


class PreferencesIn(BaseModel):
    frequency: Literal["weekly", "immediate"]
