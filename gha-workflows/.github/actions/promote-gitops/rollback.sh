#!/usr/bin/env bash
set -euo pipefail

[[ "$REPO_URL" == https://* || "$REPO_URL" == http://* ]]
[[ "$PROMOTION_REVISION" =~ ^[a-f0-9]{40}$ ]]
[[ "$MANIFEST_PATH" =~ ^[a-zA-Z0-9_./-]+$ && "$MANIFEST_PATH" != /* ]]
[[ "/$MANIFEST_PATH/" != *'/../'* ]]
git check-ref-format --branch "$BRANCH" >/dev/null

credential_helper='!f() { printf "username=%s\npassword=%s\n" "$GITOPS_USERNAME" "$GITOPS_TOKEN"; }; f'
export GIT_TERMINAL_PROMPT=0
directory="$GITHUB_WORKSPACE/.gitops"
git -c credential.helper= -c "credential.helper=$credential_helper" \
  clone --single-branch --branch "$BRANCH" -- "$REPO_URL" "$directory"
head_revision="$(git -C "$directory" rev-parse HEAD)"
if [[ "$head_revision" != "$PROMOTION_REVISION" ]]; then
  echo '::notice::GitOps HEAD changed after promotion. Refusing to roll back a newer commit.'
  echo 'status=superseded' >> "$GITHUB_OUTPUT"
  exit 0
fi

read -r revision parent extra <<< "$(git -C "$directory" rev-list --parents -n 1 HEAD)"
[[ "$revision" == "$PROMOTION_REVISION" && -n "$parent" && -z "$extra" ]]
changed_paths="$(git -C "$directory" diff-tree --no-commit-id --name-only -r HEAD)"
[[ "$changed_paths" == "$MANIFEST_PATH" ]]
manifest="$(realpath "$directory/$MANIFEST_PATH")"
[[ "$manifest" == "$directory/"* && -f "$manifest" && ! -L "$directory/$MANIFEST_PATH" ]]
git -C "$directory" cat-file -e "$parent:$MANIFEST_PATH"

read_image() {
  docker run --rm -i -e IMAGE_KEY mikefarah/yq:4.47.2 --exit-status -o=json \
    '[.images[] | select(.name == strenv(IMAGE_KEY))] | select(length == 1) | .[0]' - \
    | jq -er 'select(.newTag == null) | (.newName // .name) + "@" + .digest'
}
current_image="$(read_image < "$manifest")"
[[ "$current_image" == "$IMAGE" ]]
previous_image="$(git -C "$directory" show "$parent:$MANIFEST_PATH" | read_image)"
registry="${REGISTRY,,}"
image_name="${IMAGE_NAME,,}"
[[ "$previous_image" == "$registry/$image_name@sha256:"* ]]
[[ "${previous_image#*@sha256:}" =~ ^[a-f0-9]{64}$ ]]

claims=(--certificate-oidc-issuer https://token.actions.githubusercontent.com
  --certificate-identity "$IDENTITY"
  --certificate-github-workflow-repository "$REPOSITORY"
  --certificate-github-workflow-trigger push)
cosign verify "${claims[@]}" "$previous_image"
cosign verify-attestation --type cyclonedx "${claims[@]}" "$previous_image" >/dev/null

git -C "$directory" restore --source="$parent" -- "$MANIFEST_PATH"
git -C "$directory" config user.name 'DevSecOps promotion bot'
git -C "$directory" config user.email 'devsecops-bot@users.noreply.github.com'
git -C "$directory" add -- "$MANIFEST_PATH"
git -C "$directory" commit -m "Roll back $IMAGE_KEY after failed deployment" \
  -m "Failed promotion: $PROMOTION_REVISION" -m "Restored image: $previous_image"
git -C "$directory" -c credential.helper= -c "credential.helper=$credential_helper" \
  push origin "HEAD:refs/heads/$BRANCH"
echo 'status=reverted' >> "$GITHUB_OUTPUT"
echo "revision=$(git -C "$directory" rev-parse HEAD)" >> "$GITHUB_OUTPUT"
echo "image=$previous_image" >> "$GITHUB_OUTPUT"