from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr


class HealthOut(BaseModel):
    status: Literal["ok"]
    db: Literal["ok", "unavailable"]
    db_error: str | None = None


class MessageOut(BaseModel):
    message: str


class SubscribeIn(BaseModel):
    email: EmailStr
    source: str = "coming_soon"
    cf_turnstile_token: str | None = None


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
