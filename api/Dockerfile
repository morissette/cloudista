FROM python:3.11-slim

WORKDIR /app

# Install pipenv
RUN pip install --no-cache-dir pipenv

# Install dependencies from Pipfile on the target platform
# (--system: install into system Python, no venv needed in Docker)
# (--skip-lock: use Pipfile directly, avoids cross-platform lock hash mismatch)
COPY Pipfile Pipfile.lock ./
RUN pipenv install --system --skip-lock

COPY main.py email_template.py blog_routes.py config.py dependencies.py schemas.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
