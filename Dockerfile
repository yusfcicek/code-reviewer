# The review agent, as a deployable artefact.
#
# Two stages. The first resolves the lock file and installs into a virtual
# environment; the second carries that environment, the package and nothing
# else — no compiler, no `uv`, no source tree, no `.git`. What ends up in the
# image is what runs (Level 19, decision D-6).
#
# Tags are pinned by digest-bearing version rather than `latest`: an image that
# rebuilds differently next Tuesday is not a deployable artefact.

# ---------- build ----------
FROM python:3.12-slim-bookworm AS build

# `uv` is copied from its own published image rather than installed with pip,
# so the build stage needs no network beyond the two registries.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /src

# The lock file first, so a change to the source does not invalidate the
# dependency layer. `--no-dev` leaves the test and lint tooling out of the
# image; `--extra serve` adds the WSGI server the container runs under.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra serve

COPY code_reviewer/ ./code_reviewer/
RUN uv sync --frozen --no-dev --extra serve

# ---------- runtime ----------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="ai-code-review" \
      org.opencontainers.image.description="Enterprise AI Code Review Agent" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/yusfcicek/code-reviewer"

# A `git` binary, because the analyzers and the safe-search tool shell out to
# `grep` and the workspace may be a checkout. Nothing else is added: every
# package here is an attack surface acquired for a running review.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

# A user that is not root, with a home it can write to. The manifests also set
# `runAsNonRoot`, which refuses to start a container whose USER is numeric-less
# — so this is an id rather than only a name.
RUN groupadd --gid 10001 review \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin review

COPY --from=build --chown=10001:10001 /src/.venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REVIEW_HOST=0.0.0.0 \
    REVIEW_PORT=8080

# The workspace the agent is confined to. Mounted at run time; created here so
# the read-only root filesystem the manifests ask for still has somewhere the
# process can be pointed at.
RUN mkdir -p /workspace && chown 10001:10001 /workspace
WORKDIR /workspace

USER 10001:10001

EXPOSE 8080

# `wsgiref` serves one request at a time, which is fine for a laptop and not
# for a deployment. The application is a plain WSGI callable precisely so the
# server is a deployment choice (ADR 0020).
#
# One worker: the queue is in memory, and a second worker process would not
# share it. Threads inside the process are what Level 17 added.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "8", \
     "--timeout", "600", \
     "--graceful-timeout", "25", \
     "--access-logfile", "-", \
     "code_reviewer.serve:create_app()"]
