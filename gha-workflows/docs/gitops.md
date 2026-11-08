# GitOps deployment and recovery

The delivery workflow writes a verified image digest to a separate desired-state repository. Argo CD pulls that repository and reconciles Kubernetes. GitHub Actions does not run `kubectl apply`, request an Argo administrator token, or call an imperative Argo rollback.

Read [architecture](architecture.md) for trust boundaries and [pipelines](pipelines.md) for the CI/CD job sequence.

## Prepare the target

Provision these resources before invoking [dotnet-cd.yml](../.github/workflows/dotnet-cd.yml):

1. An existing GitOps repository and branch containing a Kustomize overlay.
2. Exactly one image entry with the configured `image-key` in `manifest-path`.
3. An Argo CD single-source Application tracking that repository, branch, and overlay.
4. Destination namespace/workload permissions and any private-registry image pull secret.
5. A GitOps write identity scoped to the intended repository and an Argo read-only observation token.
6. Runner reachability to GitOps, registry, Argo API, and the application's health/API endpoints.
7. A GitHub environment with the required reviewer and deployment rules.

Defaults are branch `main`, manifest `environments/local/kustomization.yaml`, image key `simple-api`, GitHub environment `local`, and Argo Application `simple-api-local`. They are sample conventions, not automatic resource provisioning.

The companion sample initializes the GitOps repository from its deployment manifests and uses Gitea for GitOps only. Keep its bootstrap image placeholder out of an active Argo Application until a verified digest is committed. The catalog itself has no GitOps bases, cluster bootstrap, or Argo installation manifests.

## CI-to-CD handoff

| CD input/secret | Value and purpose |
| --- | --- |
| `image` | CI's completed immutable `image` output, passed unchanged |
| `source-revision` | Full application commit SHA, matching the caller's `github.sha` |
| `source-ref` | Exact caller `github.ref`: main or a strict stable/RC tag |
| `registry`, `image-name` | Same repository binding used by CI |
| `registry-username`, secret `registry-token` | Registry read credentials; GHCR can use the workflow token with package access |
| `repo-url`, `branch` | Desired-state repository and existing branch |
| `username`, secret `gitops-token` | GitOps bot credentials |
| `manifest-path`, `image-key` | Existing overlay file and unique image entry |
| `catalog-ref`, `signing-identity` | Catalog checkout and exact reusable signing workflow certificate identity |
| `environment` | GitHub approval boundary; does not automatically select a manifest or create an Argo Application |
| `version` | Optional display metadata, never used to reconstruct an image |

Invoke CD as a dependent job in the same application run after CI returns a non-empty signed image. CD preparation compares source metadata against that run and rejects mutable images, mismatched repositories, unsupported source refs, and invalid SHA/digest shapes.

For custom registries, supply explicit credentials. Registry strings are hostnames, optionally with a port, not URLs. Image names are registry-relative paths. Kubernetes pull authentication and Argo Git read authentication are provisioned separately from CI/CD secrets.

## Verification and promotion

The `verify` job checks the configured exact signer identity, GitHub OIDC issuer, caller repository, source commit/ref, push trigger, and signed CycloneDX attestation. The protected `deploy` job re-verifies through [promote-gitops](../.github/actions/promote-gitops/action.yml) at the write boundary.

The [promotion script](../.github/actions/promote-gitops/promote.sh) then resolves the actual application branch/tag commit through the GitHub commits API. If it no longer matches the candidate source SHA, promotion returns `stale` and does not write GitOps. Tags are resolved as tags, not as the current main tip.

Source: [`.github/actions/promote-gitops/promote.sh`](../.github/actions/promote-gitops/promote.sh)

```bash title=".github/actions/promote-gitops/promote.sh"
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$directory:/work" -e IMAGE_KEY mikefarah/yq:4.47.2 \
  --exit-status '[.images[] | select(.name == strenv(IMAGE_KEY))] | length == 1' \
  "/work/$MANIFEST_PATH" >/dev/null
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$directory:/work" -e IMAGE_KEY -e IMAGE_REPO -e DIGEST mikefarah/yq:4.47.2 \
  -i '(.images[] | select(.name == strenv(IMAGE_KEY))) |= (.newName = strenv(IMAGE_REPO) | .digest = strenv(DIGEST) | del(.newTag))' \
  "/work/$MANIFEST_PATH"
```

The first invocation requires exactly one existing entry. The second preserves its logical name, sets the verified repository and digest, and removes the mutable tag. No new image entry is invented when the expected key is missing.

The script commits only the selected manifest and pushes normally. If its desired state is already present, it returns the existing HEAD without a new commit. A concurrent writer can cause a non-fast-forward push failure; inspect and rerun rather than force-pushing. Workflow concurrency serializes the same application/environment but is not a global lock across GitOps writers.

## Promotion outputs

| Output/state | Meaning |
| --- | --- |
| `promotion-status: promoted` | New desired-state commit pushed |
| `promotion-status: unchanged` | Desired state already matches; current GitOps HEAD returned |
| `promotion-status: stale` | Source ref advanced/moved; no write and no revision |
| `gitops-revision` | Exact desired-state commit for reconciliation, empty when stale |
| `validated: true` | Exact reconciliation, smoke, and every enabled runtime check passed |
| `validated: false` | Promotion-only, stale, incomplete, or failed candidate validation |

An unchanged digest can still undergo exact-revision deployment validation. A stale build cannot. A pushed Git commit alone does not establish that Kubernetes has deployed it.

## Exact deployment validation

`validate-deployment` defaults to false. Enable it with `argocd-server`, `argocd-application`, secret `argocd-token`, and `application-url`. Give the observer `applications,get` only for the intended project/Application; it does not need sync, update, or cluster administrator privileges.

[argocd-wait](../.github/actions/argocd-wait/wait.py) requires the exact promoted GitOps revision, Synced and Healthy state, and the expected immutable image in the Application summary. A previous healthy deployment cannot satisfy the check. Multi-source Applications are outside this observer contract.

TLS verification remains enabled. Use `argocd-ca-file` for trusted private CAs. `argocd-allow-http: true` is an isolated-lab exception, not a production recommendation. An unreachable private endpoint needs runner network configuration, not disabled certificate verification.

After reconciliation, [HTTP smoke](../.github/actions/http-smoke/action.yml) checks health HTTP 200 and a non-empty JSON API response. Defaults are `/health`, `/weatherforecast`, and JSON kind `array`; configure these for the actual application.

Optional k6 requires a bounded caller-owned script with thresholds. Optional ZAP performs passive baseline scanning against an authorized target and blocks on WARN, FAIL, or errors. It does not replace authenticated/API-complete testing. Both options, and rollback, are rejected when deployment validation is disabled.

## Environment promotion

GitHub approval controls the desired-state write job. Argo then reconciles the approved Git commit; approval does not require disabling Argo automated sync. Declaring `environment: production` does not create required reviewers. Configure reviewers and prevent self-review in GitHub settings.

The companion caller maps main releases to development and stable/RC tags to staging. Its selectors default to `local`, preserving the existing lab rather than claiming separate provisioned environments. Provision overlays, Applications, endpoints, and credentials before changing those selectors.

The sample's production call is disabled by default. It requires a stable `production` release and successful lower-environment `validated: true`, then reuses the same CI image digest through a separately protected production environment. An RC does not qualify. The catalog's version output does not enforce this caller policy by itself.

Use distinct manifests, Applications, scoped credentials, and reviewer rules for production. Rebuilding for production would invalidate the scanned-candidate handoff and is not part of this flow.

## Guarded recovery

`enable-rollback` defaults to false and requires deployment validation. The recovery job runs only after a new promotion and a failed sync, smoke, enabled runtime check, or validation gate. It does not run after cancellation, failed promotion, unchanged desired state, or stale source.

The [rollback script](../.github/actions/promote-gitops/rollback.sh) requires:

1. GitOps HEAD is still the failed promotion revision. A newer commit is preserved.
2. The failed promotion has exactly one parent and changed only the configured manifest.
3. The previous image entry contains an immutable digest in the configured repository.
4. The previous digest passes exact signer, GitHub issuer, caller repository, push-trigger signature checks and CycloneDX attestation verification.
5. Restoration can be pushed as a new ordinary Git commit, without force.

The prior image belongs to an earlier source commit, so its verification does not incorrectly require the failed candidate's SHA/ref. Recovery restores the selected manifest from the parent commit, then observes the exact recovery revision and restored image and runs HTTP smoke.

| Recovery output | Meaning |
| --- | --- |
| `rolled-back` | Restoration, exact recovery reconciliation, and smoke succeeded |
| `reverted` | Restoration commit exists, but recovery validation did not complete successfully |
| `superseded` | Newer GitOps work was preserved; recovery did not overwrite it |
| `not-run` | Recovery did not execute |
| `rollback-revision` | Recovery commit when one was pushed |

Inspect the rollback job result as well as its output if a guard or verification fails. Recovery never clears the original workflow failure or changes the failed candidate's `validated: false`.

Argo self-healing returns live resources to Git desired state. It does not undo a bad Git commit. The catalog creates a recovery commit rather than using `argocd app rollback`; Argo's automated-sync documentation also excludes imperative rollback while automated sync is enabled.

## Failure notification and incident checks

Optional secret `slack-webhook-url` sends a failure notice after recovery finishes. It includes environment, digest, recovery state, and run link, without credentials. Notification failure is non-blocking and does not replace the deployment failure.

| Failure | Investigation |
| --- | --- |
| Verification rejected | Digest/repository, certificate identity/issuer, signed source claims, CycloneDX predicate |
| Promotion stale | Current source branch/tag SHA versus the candidate commit |
| Git push rejected | New GitOps commits and target branch protections; no force push |
| Argo timeout | Exact expected revision/image, repository access, render errors, workload events, pull credentials |
| Synced but unhealthy | Readiness/liveness, resource limits, startup failures, and application logs |
| Healthy but smoke fails | Runner routing, ingress, health/API paths, response type and non-empty body |
| Recovery superseded | Newer desired-state commit; coordinate with its owner |
| Recovery only reverted | Recovery commit and failed reconciliation/smoke evidence |

Retain reconciliation, runtime, recovery, and summary artifacts with the source SHA, candidate digest, promotion revision, and recovery revision. Do not retry by substituting a mutable tag or widening signer trust.

## References

- [Argo CD automated sync and rollback semantics](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [Argo CD RBAC](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
- [Catalog GitOps contract](../README.md)
- [Design reference GitOps guide](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/gitops.md)
