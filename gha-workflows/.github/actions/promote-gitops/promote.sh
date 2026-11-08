#!/usr/bin/env bash
set -euo pipefail

[[ "$REPO_URL" == https://* || "$REPO_URL" == http://* ]]
[[ "$MANIFEST_PATH" =~ ^[a-zA-Z0-9_./-]+$ && "$MANIFEST_PATH" != /* ]]
[[ "/$MANIFEST_PATH/" != *'/../'* ]]
git check-ref-format --branch "$BRANCH" >/dev/null

SOURCE_REF="${SOURCE_REF:-refs/heads/main}"
release_number='(0|[1-9][0-9]*)'
tag_pattern="^refs/tags/v${release_number}\\.${release_number}\\.${release_number}(-rc\\.${release_number})?$"
[[ "$SOURCE_REF" == refs/heads/main || "$SOURCE_REF" =~ $tag_pattern ]]
encoded_ref="$(jq -rn --arg ref "${SOURCE_REF#refs/}" '$ref | @uri')"
head_revision="$(curl --fail --silent --show-error \
  -H "Authorization: Bearer $GH_TOKEN" \
  "$GITHUB_API_URL/repos/$REPOSITORY/commits/$encoded_ref" | jq -er '.sha')"
[[ "$head_revision" =~ ^[a-f0-9]{40}$ ]]
if [[ "$head_revision" != "$COMMIT" ]]; then
  echo '::notice::Source ref no longer points to this application commit. Skipping stale promotion.'
  echo 'status=stale' >> "$GITHUB_OUTPUT"
  exit 0
fi

credential_helper='!f() { printf "username=%s\npassword=%s\n" "$GITOPS_USERNAME" "$GITOPS_TOKEN"; }; f'
export GIT_TERMINAL_PROMPT=0
directory="$GITHUB_WORKSPACE/.gitops"
git -c credential.helper= -c "credential.helper=$credential_helper" \
  clone --single-branch --branch "$BRANCH" -- "$REPO_URL" "$directory"
manifest="$(realpath "$directory/$MANIFEST_PATH")"
[[ "$manifest" == "$directory/"* && -f "$manifest" ]]
export IMAGE_REPO="${IMAGE%@*}" DIGEST="${IMAGE#*@}"

docker run --rm --user "$(id -u):$(id -g)" \
  -v "$directory:/work" -e IMAGE_KEY mikefarah/yq:4.47.2 \
  --exit-status '[.images[] | select(.name == strenv(IMAGE_KEY))] | length == 1' \
  "/work/$MANIFEST_PATH" >/dev/null
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$directory:/work" -e IMAGE_KEY -e IMAGE_REPO -e DIGEST mikefarah/yq:4.47.2 \
  -i '(.images[] | select(.name == strenv(IMAGE_KEY))) |= (.newName = strenv(IMAGE_REPO) | .digest = strenv(DIGEST) | del(.newTag))' \
  "/work/$MANIFEST_PATH"

git -C "$directory" config user.name 'DevSecOps promotion bot'
git -C "$directory" config user.email 'devsecops-bot@users.noreply.github.com'
git -C "$directory" add -- "$MANIFEST_PATH"
if git -C "$directory" diff --cached --quiet; then
  echo 'Desired digest already committed.'
  echo 'status=unchanged' >> "$GITHUB_OUTPUT"
  echo "revision=$(git -C "$directory" rev-parse HEAD)" >> "$GITHUB_OUTPUT"
  exit 0
fi
git -C "$directory" commit -m "Deploy simple-api from $COMMIT" -m "Image: $IMAGE"
git -C "$directory" -c credential.helper= -c "credential.helper=$credential_helper" \
  push origin "HEAD:refs/heads/$BRANCH"
echo 'status=promoted' >> "$GITHUB_OUTPUT"
echo "revision=$(git -C "$directory" rev-parse HEAD)" >> "$GITHUB_OUTPUT"