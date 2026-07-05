# Stage 1: compile llama-cpp-python (CPU build of llama.cpp) into a wheel so
# the final image needs no compiler toolchain.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-llm.txt .
RUN pip wheel --no-cache-dir -r requirements-llm.txt -w /wheels

# Stage 2: runtime image.
FROM python:3.12-slim

# libgomp1: OpenMP runtime used by llama.cpp.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir -r requirements.txt /wheels/*.whl \
    && rm -rf /wheels

COPY app ./app

# Model files are downloaded at startup into MODELS_DIR (mounted as a volume
# in docker-compose so they persist across container rebuilds).
ENV MODELS_DIR=/models

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
