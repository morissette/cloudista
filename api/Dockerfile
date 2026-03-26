FROM python:3.12-slim

WORKDIR /app

# Install pipenv
RUN pip install --no-cache-dir pipenv

# Install dependencies from Pipfile.lock for reproducible builds.
# pipenv sync installs exactly what's in the lockfile without checking that
# the lock was generated on the same Python patch version as the image.
# (--system: install into system Python, no venv needed in Docker)
COPY Pipfile Pipfile.lock ./
RUN pipenv sync --system

COPY main.py email_template.py blog_routes.py config.py dependencies.py schemas.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
