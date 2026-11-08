#!/usr/bin/env bash
set -euo pipefail

cd "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must identify the application checkout}"

if [[ ! -f version.json ]]; then
  echo '::error::Missing root version.json. Add and commit this manifest before running release versioning:' >&2
  printf '%s\n' '{' \
    '  "$schema": "https://raw.githubusercontent.com/dotnet/Nerdbank.GitVersioning/main/src/NerdBank.GitVersioning/version.schema.json",' \
    '  "version": "1.0.0-preview.{height}",' \
    '  "publicReleaseRefSpec": [' \
    '    "^refs/heads/main$",' \
    '    "^refs/tags/v\\d+\\.\\d+\\.\\d+(?:-rc\\.\\d+)?$"' \
    '  ]' \
    '}'
  exit 1
fi

if ! jq -e 'type == "object" and (.version | type == "string" and length > 0)' version.json >/dev/null; then
  echo '::error::version.json must contain valid JSON with a nonempty version string.' >&2
  exit 1
fi

if [[ "${1:-}" == --validate-manifest ]]; then
  exit 0
fi
[[ $# -eq 0 ]]

output_file="${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set by GitHub Actions}"
release_ref="${GITHUB_REF:?GITHUB_REF must be set by GitHub Actions}"
if [[ "$(git rev-parse --is-shallow-repository)" != false ]]; then
  echo '::error::NBGV requires full Git history. Configure actions/checkout with fetch-depth: 0.' >&2
  exit 1
fi

nbgv="${NBGV:-nbgv}"
nbgv_version="$("$nbgv" get-version -v SemVer2)"
assembly_version="$("$nbgv" get-version -v AssemblyVersion)"
[[ "$nbgv_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]
[[ "$assembly_version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+){0,2}$ ]]
version="${nbgv_version%%+*}"
commit="$(git rev-parse --short HEAD)"
[[ "$commit" =~ ^[a-f0-9]{7,40}$ ]]

release_number='(0|[1-9][0-9]*)'
tag_pattern="^refs/tags/v${release_number}\\.${release_number}\\.${release_number}(-rc\\.${release_number})?$"
if [[ "$release_ref" =~ $tag_pattern ]]; then
  version="${release_ref#refs/tags/v}"
  nbgv_tag_version="${nbgv_version%%+*}"
  nbgv_tag_version="${nbgv_tag_version%%.g*}"
  if [[ "$version" != "$nbgv_tag_version" ]]; then
    echo "::error::Release tag $version does not match NBGV version $nbgv_tag_version (calculated: $nbgv_version)." >&2
    exit 1
  fi
  if [[ "$version" == *-rc.* ]]; then
    revision="${GITHUB_RUN_NUMBER:?GITHUB_RUN_NUMBER must be set for RC releases}"
    [[ "$revision" =~ ^[1-9][0-9]*$ ]]
    version="$version.$(date -u +%y%j).$revision"
    environment=staging
  else
    environment=production
  fi
elif [[ "$release_ref" == refs/heads/main ]]; then
  if [[ "$version" == *-preview.* ]]; then
    if [[ ! "$version" =~ ^([0-9]+\.[0-9]+\.[0-9]+-preview\.([0-9]+))(\.|$) ]]; then
      echo "::error::Unable to parse NBGV preview version: $nbgv_version." >&2
      exit 1
    fi
    preview_version="${BASH_REMATCH[1]}"
    preview_height="${BASH_REMATCH[2]}"
    if [[ "$preview_height" == 0 ]]; then
      environment=none
    else
      revision="${GITHUB_RUN_NUMBER:?GITHUB_RUN_NUMBER must be set for preview releases}"
      [[ "$revision" =~ ^[1-9][0-9]*$ ]]
      version="$preview_version.$(date -u +%y%j).$revision"
      environment=dev
    fi
  else
    environment=none
  fi
else
  echo "::error::Unsupported release ref: $release_ref." >&2
  exit 1
fi

informational_version="$version+$commit"
docker_tag="${version/+/-}"
[[ "$docker_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]
{
  echo "version=$version"
  echo "assembly_version=$assembly_version"
  echo "informational_version=$informational_version"
  echo "environment=$environment"
  echo "docker_tag=$docker_tag"
  echo "commit=$commit"
} >> "$output_file"

echo "Calculated SemVer2 version: $version"
echo "Target environment: $environment"