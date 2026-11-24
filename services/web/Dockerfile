# Small official Python image.
FROM python:3.13-slim

# Do not write .pyc files; print logs straight away so `kubectl logs` shows them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first. This layer is cached and only rebuilt when
# requirements.txt changes, not on every code change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a normal user, not root.
RUN useradd --uid 10001 --no-create-home appuser
USER 10001

# The pipeline passes the Git commit here; see /api/whoami.
ARG VERSION=dev
ENV VERSION=$VERSION

EXPOSE 8080
# The app writes its own one-line request log, so uvicorn's is turned off.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
