# Build from the parent workspace: both repositories are explicit inputs.
FROM mcr.microsoft.com/dotnet/runtime:8.0-bookworm-slim AS dotnet
FROM eclipse-temurin:25-jre-jammy AS java
FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libicu72 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dotnet /usr/share/dotnet /usr/share/dotnet
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV DOTNET_ROOT=/usr/share/dotnet JAVA_HOME=/opt/java/openjdk PATH="/opt/java/openjdk/bin:/usr/share/dotnet:${PATH}" PYTHONUNBUFFERED=1
COPY document-processor/pyproject.toml document-processor/README.md /build/document-processor/
COPY document-processor/src /build/document-processor/src
RUN pip install --no-cache-dir /build/document-processor && rm -rf /build
COPY Jobtology-DB/services/document-parser/server.py Jobtology-DB/services/document-parser/worker.py /app/
ARG PARSER_REVISION
ENV PARSER_REVISION=${PARSER_REVISION}
USER 501:501
WORKDIR /app
CMD ["python", "server.py"]
