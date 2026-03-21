from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL — blog + subscribers (single DB after MySQL migration)
    blog_db_host: str = "localhost"
    blog_db_port: int = 5433
    blog_db_user: str = "cloudista"
    blog_db_password: str = ""
    blog_db_name: str = "cloudista"

    # AWS / SES
    aws_region: str = "us-east-1"
    from_email: str = "noreply@cloudista.org"
    confirm_base_url: str = "https://cloudista.org/api/confirm"
    site_url: str = "https://cloudista.org"
    turnstile_secret: str = ""


settings = Settings()
