from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL — blog + subscribers (single DB after MySQL migration)
    blog_db_host: str = "localhost"
    blog_db_port: int = 5433
    blog_db_user: str = "cloudista"
    blog_db_password: str  # required — no default; ValidationError at startup if missing
    blog_db_name: str = "cloudista"

    # AWS / SES
    aws_region: str = "us-east-1"
    from_email: str = "noreply@cloudista.org"
    confirm_base_url: str = "https://cloudista.org/api/confirm"
    site_url: str = "https://cloudista.org"
    turnstile_secret: str = ""
    ses_topic_arn: str = ""  # optional: SNS TopicArn allowlist for /api/ses-webhook
    admin_key: str = ""  # optional: protects POST /api/blog/posts/{slug}/revisions/{id}/restore

    @field_validator("blog_db_password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("BLOG_DB_PASSWORD must not be empty")
        return v


settings = Settings()
