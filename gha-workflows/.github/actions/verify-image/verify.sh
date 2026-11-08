#!/usr/bin/env bash
set -euo pipefail

[[ "$COMMIT" =~ ^[a-f0-9]{40}$ ]]
SOURCE_REF="${SOURCE_REF:-refs/heads/main}"
release_number='(0|[1-9][0-9]*)'
tag_pattern="^refs/tags/v${release_number}\\.${release_number}\\.${release_number}(-rc\\.${release_number})?$"
[[ "$SOURCE_REF" == refs/heads/main || "$SOURCE_REF" =~ $tag_pattern ]]
registry="${REGISTRY:-ghcr.io}"
image_name="${IMAGE_NAME:-$REPOSITORY}"
registry="${registry,,}"
image_name="${image_name,,}"
[[ "$registry" =~ ^[a-z0-9][a-z0-9.-]*(:[0-9]+)?$ ]]
component='[a-z0-9]+(([._]|__|-+)[a-z0-9]+)*'
[[ "$image_name" =~ ^$component(/$component)*$ ]]
[[ "$IMAGE" == "$registry/$image_name@sha256:"* ]]
[[ "${IMAGE#*@sha256:}" =~ ^[a-f0-9]{64}$ ]]
claims=(--certificate-oidc-issuer https://token.actions.githubusercontent.com
  --certificate-identity "$IDENTITY"
  --certificate-github-workflow-repository "$REPOSITORY"
  --certificate-github-workflow-sha "$COMMIT"
  --certificate-github-workflow-ref "$SOURCE_REF"
  --certificate-github-workflow-trigger push)
cosign verify "${claims[@]}" "$IMAGE"
cosign verify-attestation --type cyclonedx "${claims[@]}" "$IMAGE" >/dev/null