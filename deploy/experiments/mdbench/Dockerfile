FROM python:3.9.23-slim-bookworm@sha256:7bffea15bcc3d7fb87cf10a027986203e4281e078fa2f5b234c30fca291f0834

ARG MDBENCH_REVISION=f81813e760325589737fe3311ac8199ecc64188a

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-sindy.lock /tmp/requirements-sindy.lock
RUN python -m pip install --upgrade pip==25.1.1 \
    && python -m pip install --requirement /tmp/requirements-sindy.lock \
    && python -m pip check

RUN git clone https://github.com/gryaklab/mdbench.git /opt/mdbench \
    && git -C /opt/mdbench checkout "${MDBENCH_REVISION}" \
    && test "$(git -C /opt/mdbench rev-parse HEAD)" = "${MDBENCH_REVISION}" \
    && rm -rf /opt/mdbench/.git

LABEL org.opencontainers.image.title="AutoResearch MDBench SINDy/PDE-FIND runtime" \
      org.opencontainers.image.source="https://github.com/gryaklab/mdbench" \
      org.opencontainers.image.revision="${MDBENCH_REVISION}"

WORKDIR /opt/mdbench

CMD ["python", "-m", "mdbench.evaluate_method", "--help"]
