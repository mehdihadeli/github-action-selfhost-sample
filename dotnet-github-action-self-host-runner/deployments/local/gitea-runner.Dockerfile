FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS sdk

FROM docker.gitea.com/gitea/runner@sha256:8bcb489f9dd6be500de22bcaa8512ef57b81ae50315db8c7a1dc1b74978a76f4

RUN apk add --no-cache bash ca-certificates curl git icu-libs jq krb5-libs libgcc libstdc++ openssl python3 tzdata zlib

COPY --from=sdk /usr/share/dotnet /usr/share/dotnet
COPY gitea-runner.yaml /etc/gitea-runner.yaml

ENV DOTNET_ROOT=/usr/share/dotnet \
    PATH="/usr/share/dotnet:${PATH}" \
    DOTNET_CLI_TELEMETRY_OPTOUT=1