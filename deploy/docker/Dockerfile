FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml poetry.lock README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN mkdir -p /workspace/autoresearch-vault /workspace/runs /workspace/artifacts

WORKDIR /workspace

ENTRYPOINT ["autoresearch"]
CMD ["doctor"]
