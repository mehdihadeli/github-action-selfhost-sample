FROM docker:28.5.1-cli AS docker-cli
FROM ghcr.io/actions/actions-runner:2.338.2
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git jq python3 unzip libicu74 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/hostedtoolcache \
    && chown runner:runner /opt/hostedtoolcache
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
ENV RUNNER_TOOL_CACHE=/opt/hostedtoolcache
USER runner