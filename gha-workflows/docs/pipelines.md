# Pipelines

This guide documents the jobs owned by [reusable CI](../.github/workflows/dotnet-ci.yml) and [reusable CD](../.github/workflows/dotnet-cd.yml). Both expose `workflow_call`; application repositories configure triggers and invoke them. No standalone scheduled security, Terraform, or EOL workflow is included.

## Caller contract

CI requires `project`. Set `publish-project` when that input is a solution, configure test projects explicitly, and commit dependency lock files. Defaults include SDK `10.0.x`, Dockerfile `Dockerfile`, platform `linux/amd64`, registry `ghcr.io`, runner `arc-devsecops`, and IaC overlay `deployments/gitops/environments/local`.

The caller must allow the permissions requested by reusable jobs, including `contents: read`, `actions: read`, `pull-requests: read`, `security-events: write`, `packages: write`, `id-token: write`, and `attestations: write`. Jobs reduce their effective permissions. CodeQL requires a public repository or the applicable private-repository security entitlement.

Call the published workflows at `mehdihadeli/gha-workflows/.github/workflows/dotnet-ci.yml@<catalog-commit>` and `mehdihadeli/gha-workflows/.github/workflows/dotnet-cd.yml@<catalog-commit>`. Set `catalog-ref` to that same commit and configure the exact signing identity. The current `main` defaults are bootstrap settings, not immutable production references. For complete inputs and secret mappings, see the [README](../README.md).

## Event and runner policy

| Caller event/ref | Candidate validation | Version job | Publication | Runner selection |
| --- | --- | --- | --- | --- |
| Pull request outside main/`v*` refs | Yes | Skipped | Never | Hosted candidate jobs |
| Manual dispatch on main | Yes | Runs | Never | Hosted candidate jobs |
| Main push | Yes | Runs | Positive preview release only | Configured runner for most candidate jobs and release |
| Stable or RC `v*` tag push | Yes | Runs; strict tag validation | Matching release only | Hosted candidate jobs; configured release runner |
| Other refs | Yes when caller invokes CI | Skipped except `v*` refs | Never | Hosted candidate jobs |

CodeQL, pre-build/security gates, version calculation, and scorecard run hosted. CI does not execute a candidate-container startup smoke; deployed HTTP smoke belongs to CD. CD preparation restricts execution to eligible push refs and verifies exact caller SHA/ref. A manual CI invocation does not grant deployment authorization.

## CI stages

| Job ID | Depends on | Work and success condition |
| --- | --- | --- |
| `quality` | None | Locked restore, .NET code style, CSharpier, Roslyn/compiler checks, Hadolint |
| `secret-scan` | None | Gitleaks event-aware plus full checked-out history scan; no leaks |
| `sast-scan` | None | Semgrep configured security rules; no blocking findings |
| `sca-scan` | None | Trivy source dependencies and additional source secret/configuration checks |
| `iac-scan` | None | Checkov rendered workload, Dockerfile, caller workflows; optional Snyk IaC |
| `codeql` | None | Hosted C# security-extended analysis |
| `pre-build-gate` | All six jobs above | Every required result is `success` |
| `build-test` | `pre-build-gate` | Release build with analyzers/warnings as errors; configured unit/E2E suites and evidence |
| `sonar` | `build-test` | Optional scanner and server quality gate |
| `sca-scan-app` | `build-test` | Published application output, independent Trivy/Grype gates, optional Snyk/BOM ingestion |
| `calculate-version` | `build-test` | Main/`v*` refs only; full-history NBGV and tag consistency |
| `image-build` | `build-test`, `calculate-version` | Accept expected version-job skip on other refs; build/archive one platform without push |
| `container-security` | `image-build` | Reload exact archive; Trivy/Grype and optional Snyk Container |
| `supply-chain-security` | `image-build`, `container-security` | Reload same archive; generate CycloneDX, SPDX JSON, and dependency table |
| `security-gate` | All prior stages | Reject any required failure, cancellation, or unexpected skip |
| `release` | `security-gate`, `image-build`, `calculate-version` | Eligible push only; reload, push without rebuild, verify remote identity, sign, attest, create provenance |
| `devsecops-scorecard` | All stages including release | Always report actual results and retain pipeline evidence |

Source jobs run independently in parallel. After build/test, Sonar, application scanning, and version calculation can proceed independently. Container scanning precedes image SBOM generation. The final gate includes versioning only on relevant refs and Sonar only when enabled; required stages cannot be made optional by being skipped unexpectedly.

Source: [`.github/workflows/dotnet-ci.yml`](../.github/workflows/dotnet-ci.yml)

```yaml title=".github/workflows/dotnet-ci.yml"
  release:
    name: Image Publication, Signing & Attestation
    needs: [security-gate, image-build, calculate-version]
    if: github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')) && needs.calculate-version.outputs.environment != 'none'
    runs-on: ${{ inputs.runner }}
    timeout-minutes: 20
    permissions:
      contents: read
      packages: write
      id-token: write
      attestations: write
    outputs:
      image: ${{ steps.complete.outputs.image }}
```

The release job requires the gate and candidate/version outputs, checks the original event/ref, and uses the configured runner. Its `image` output is assigned only after publication, signing, attestation, and provenance complete.

## Version and image contract

[calculate-version](../.github/actions/calculate-version/action.yml) installs latest stable NBGV in a temporary directory. Commit root `version.json` and check out full history; missing manifests, shallow history, unsupported tags, and version/tag mismatches fail rather than creating a manifest at runtime.

| Source state | Track | Published tags |
| --- | --- | --- |
| Main with positive preview height | `dev` | Preview version plus UTC `YYDDD` and run number; branch/SHA aliases |
| Main with zero preview height or stable version | `none` | No publication |
| Matching `v1.0.0` with matching stable manifest | `production` | Stable version, SHA alias, explicit `latest` |
| Matching `v1.1.0-rc.1` with matching RC manifest | `staging` | RC plus UTC/run uniqueness, SHA alias; no `latest` |

CI outputs `version`, `assembly_version`, `informational_version`, `docker_tag`, `environment`, `commit`, and `image`. Version outputs do not rewrite assembly/project metadata. `commit` is short display metadata; CD's `source-revision` requires the full caller SHA, normally `github.sha`.

`image` is empty outside completed eligible releases and is otherwise an immutable registry digest. Pass it unchanged to CD with the same registry/image settings. A release track is metadata, not proof that a matching Kubernetes environment exists.

## Tests and scanner policy

Empty `test-project`/`e2e-test-project` means unconfigured, not passing. `require-tests: true` rejects having neither suite. Configured suites need lock files and nonzero TRX test counters. The action supports `vstest`, `mtp`, and `mtp-bridge`; native MTP needs SDK 10+, repository runner configuration, and the TRX reporting extension. Coverage collection uses the VSTest XPlat collector and requires consumer support; it does not silently substitute VSTest flags for MTP.

Reusable CI enforces scanner findings. Application/image Trivy and Grype block HIGH/CRITICAL vulnerabilities, including unfixed findings. Source SCA uses Trivy. Optional Snyk independently blocks HIGH+ findings. Sonar becomes required when enabled. Dependency-Track ingestion is not a completed asynchronous CVE gate.

Scanner exit status remains authoritative even if SARIF upload is unavailable. Fork PRs retain reports without privileged SARIF uploads. Token-backed optional integrations need an explicit fork policy; this catalog does not switch to privileged execution of fork code to obtain secrets.

## CD stages

| Job ID | Condition/dependency | Work |
| --- | --- | --- |
| `prepare` | Eligible push | Full source SHA/ref, exact digest/repository binding, runtime configuration |
| `verify` | `prepare` | Registry read login, exact signature/source/SBOM verification |
| `deploy` | `prepare`, `verify` | Protected environment; reverify, freshness check, update GitOps |
| `wait-sync` | Deploy revision exists, not stale, validation enabled | Observe exact revision/image, Synced, Healthy |
| `smoke-tests` | `wait-sync` | Health and non-empty configured JSON API response |
| `load` | `smoke-tests`, k6 enabled | Bounded caller scenario with thresholds |
| `dast` | `smoke-tests`, ZAP enabled | Passive authorized-target baseline; WARN/FAIL/error blocks |
| `runtime` | Deploy succeeded with a usable revision, validation enabled | Require sync, smoke, and every enabled scanner; emit `validated=true` |
| `rollback` | Opt-in; promoted candidate and failed deployed check; not cancelled | Guarded prior-digest restoration, recovery sync and smoke |
| `summary` | Always | Actual outcomes, deployment/recovery metadata, optional Slack failure notice |

k6 and ZAP run independently after smoke. CD's concurrency group is application repository plus target environment, with `cancel-in-progress: false`; active deployment work is not intentionally cancelled by a newer run. Other repositories or environments can still contend on the same GitOps branch, where normal Git conflict handling applies.

`validate-deployment` defaults to false. In that mode CD only promotes desired state, returns `validated: false`, and cannot enable k6, ZAP, or rollback. Validation requires Argo server, Application token, and application URL. See [GitOps](gitops.md) for outputs, recovery guards, and production requirements.

## Artifacts and interpretation

| Evidence | Retention | Interpretation |
| --- | --- | --- |
| Candidate image archive | 7 days | Transport for the scanned candidate, not a release by itself |
| Tests, security reports, inventories, pipeline evidence | 30 days | Actual configured checks, results, and source/run metadata |
| Reconciliation, smoke, load, DAST, recovery evidence | 30 days | Bounded deployment observations and outcomes |
| Registry signatures/attestations/provenance | Registry policy | Availability depends on registry retention and access policy |

Always-running summaries preserve failure/skipped/disabled distinctions. A successful summary upload does not mean its scanner passed. `GENERATED` describes completed inventory work, `VERIFIED` describes completed verification, and neither certifies compliance.

## Troubleshooting

| Symptom | First check |
| --- | --- |
| Build never starts | Six source-job results and pre-build gate evidence |
| Configured tests discover nothing | TRX counters, project/platform settings, reporting extension |
| Green scans but no image output | Event/ref, NBGV track, central gate, release job result |
| Release tag waits for a runner | Configured ARC/release runner capacity, not hosted candidate capacity |
| Candidate reload mismatch | Archive checksum/image-ID outputs and artifact selection; do not rebuild to bypass |
| Signature identity mismatch | Actual release certificate versus both CI/CD `signing-identity` inputs |
| Deployment succeeds but `validated` is false | Promotion-only configuration, stale result, or runtime gate failure |
| Optional integration fails | Enable flag, scoped secret, endpoint/configuration, and scanner result |

## References

- [Catalog contracts](../README.md)
- [GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
- [Design reference pipelines](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/pipelines.md)
