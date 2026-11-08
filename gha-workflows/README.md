# Reusable DevSecOps workflows

This repository is a GitHub Actions catalog for .NET applications. It builds and scans containers on ephemeral ARC runners, signs releases, and promotes verified image digests into a GitOps repository. Argo CD handles Kubernetes deployment. No workflow receives a kubeconfig or Argo CD administrator token.

## Repository layout

- [.github/workflows/dotnet-ci.yml](.github/workflows/dotnet-ci.yml): reusable staged CI and signed image output.
- [.github/workflows/dotnet-cd.yml](.github/workflows/dotnet-cd.yml): environment-controlled GitOps promotion and staged deployment validation.
- [.github/actions/dotnet-setup/action.yml](.github/actions/dotnet-setup/action.yml), [quality](.github/actions/dotnet-quality/action.yml), [build](.github/actions/dotnet-build/action.yml), [test](.github/actions/dotnet-test/action.yml), and [publish](.github/actions/dotnet-publish/action.yml): independently reusable .NET stages. Quality owns dotnet code style, CSharpier formatting, and Roslyn analyzer checks.
- [Secret scan](.github/actions/secret-scan/action.yml), [SAST scan](.github/actions/sast-scan/action.yml), [IaC scan](.github/actions/iac-scan/action.yml), and [Hadolint](.github/actions/hadolint/action.yml): source, history, infrastructure, and Dockerfile gates.
- [Artifact SCA](.github/actions/sca-scan/action.yml): independent Trivy/Grype scans and CycloneDX SBOMs for published application output and Docker images.
- [Container scan](.github/actions/container-scan/action.yml): image-specific entry point to the shared Trivy/Grype implementation.
- [Shared security scan](.github/actions/security-scan/action.yml): owns Trivy/Grype policy, optional Snyk app/image/IaC gates, inventory, SARIF artifacts, and summaries. Public SCA and container actions delegate directly to it; IaC retains Checkov and delegates optional Snyk scanning. Check out the complete catalog at `.catalog` before using these integrations.
- [SBOM generator](.github/actions/sbom-generator/action.yml): independently reusable CycloneDX, SPDX JSON, and readable dependency inventories with selectable pinned Trivy or Syft; Trivy is the default.
- [Calculate version](.github/actions/calculate-version/action.yml): latest stable Nerdbank.GitVersioning (NBGV), committed root version manifest, and explicit release-track outputs.
- [Docker image build](.github/actions/docker-image-build/action.yml), [load](.github/actions/image-load/action.yml), [Docker image push](.github/actions/docker-image-push/action.yml), [image signer](.github/actions/image-signer/action.yml), and [verify](.github/actions/verify-image/action.yml): separate container lifecycle stages. CI does not start the candidate image; CD retains its required [HTTP smoke gate](.github/actions/http-smoke/action.yml) after reconciliation.
- [.github/actions/promote-gitops/action.yml](.github/actions/promote-gitops/action.yml): verify signatures and update one Kustomize image entry.
- [Argo wait](.github/actions/argocd-wait/action.yml), [HTTP smoke](.github/actions/http-smoke/action.yml), [k6](.github/actions/k6/action.yml), and [ZAP baseline](.github/actions/zap-baseline/action.yml): read-only reconciliation and deployed validation.
- [Sonar](.github/actions/sonar/action.yml) and [Dependency-Track](.github/actions/dependency-track/action.yml): explicitly enabled integrations. Optional Snyk scanning is implemented by the shared security scanner.
- [Pipeline evidence](.github/actions/pipeline-evidence/action.yml): central gate, summaries, and retained reports. Scanner actions own their SARIF uploads.

The catalog retains only actions used by the staged workflows, their nested composites, and shared script dependencies.

GitHub discovers reusable workflows only in `.github/workflows`. This catalog keeps composite actions in `.github/actions`; check out the whole catalog at `.catalog` so nested action and sibling-script references resolve.

## CI contract

Call `mehdihadeli/gha-workflows/.github/workflows/dotnet-ci.yml@main` from an application workflow. Provide `project`, optionally `dockerfile`, `dotnet-version`, `runner`, and test inputs. When building a solution, also provide `publish-project` pointing to its application csproj. `iac-directory` points to a Kustomize overlay, defaulting to `deployments/gitops/environments/local`. The Dockerfile must produce an image serving HTTP on port 8080 with `/health` returning success.

`test-project` and `e2e-test-project` require committed dependency lock files. Empty inputs mean no corresponding suite is configured, not passing tests. Set `require-tests: true` to reject that state. A configured suite must produce nonzero TRX test counters. `test-platform` and `e2e-test-platform` support `vstest`, `mtp`, and `mtp-bridge`; native MTP requires SDK 10+ and the repository's MTP runner configuration in `global.json`. MTP projects need the TRX reporting extension. `collect-coverage` uses VSTest's XPlat collector and produces OpenCover/Cobertura; install the collector in the consumer test project. MTP coverage is not silently substituted with VSTest flags.

The caller must grant `contents: read`, `actions: read`, `security-events: write`, `packages: write`, `id-token: write`, and `attestations: write`. Jobs reduce permissions to what they need. CodeQL runs on GitHub-hosted runners and requires a public repository or the applicable GitHub Code Security entitlement for private repositories.

Pull requests and manual dispatches use hosted runners and never publish or promote. Main-branch CI pushes use `arc-devsecops`; tag CI uses hosted runners. Eligible main, stable-tag, and RC-tag pushes publish only after the security gate succeeds. Do not introduce `pull_request_target` execution of untrusted code on these runners. Limit the ARC runner group to approved repositories/workflows and protect both `main` and release tags.

### Release versioning

[calculate-version](.github/actions/calculate-version/action.yml) installs the latest stable NBGV into a temporary tool directory on every run. Keep the default .NET SDK `10.0.x` compatible with the current tool runtime. Check out the application with `fetch-depth: 0` and commit a root `version.json`, for example:

```json
{
  "$schema": "https://raw.githubusercontent.com/dotnet/Nerdbank.GitVersioning/main/src/NerdBank.GitVersioning/version.schema.json",
  "version": "1.0.0-preview.{height}",
  "publicReleaseRefSpec": [
    "^refs/heads/main$",
    "^refs/tags/v\\d+\\.\\d+\\.\\d+(?:-rc\\.\\d+)?$"
  ]
}
```

The action fails with this starter guidance when the manifest is missing; it never creates an uncommitted manifest during CI. Its outputs are `version`, `assembly_version`, `informational_version`, `docker_tag`, `environment`, and `commit`. Reusable CI exposes the same outputs and passes `docker_tag` into both Docker stages. These outputs do not rewrite project or assembly metadata.

| Source | Release track and version |
| --- | --- |
| `main` with positive preview height | `dev`; append UTC `YYDDD` and the workflow run number to the NBGV preview version |
| `main` with zero preview height or a stable version | `none`; build and scan, but do not publish |
| Matching stable tag such as `v1.0.0` | `production`; publish `1.0.0` and the `latest` alias |
| Matching RC tag such as `v1.1.0-rc.1` | `staging`; append UTC `YYDDD` and the run number; never publish `latest` |
| Pull request or another non-release ref | Version job skipped; candidate still builds and scans, with no release |

Before creating a stable or RC tag, commit the matching manifest version, such as `1.0.0` or `1.1.0-rc.1`. Tag/NBGV mismatches, unsupported release tags, and shallow history fail closed. The standalone action rejects unsupported refs; the reusable workflow skips versioning outside main or `v*` tags. Manual dispatch on main can calculate a version but never publishes. Release tracks are metadata: the sample still promotes into its existing `local` overlay, and production requires a stable release plus successful lower-environment validation and its explicit enable flag.

### Docker lifecycle

[docker-image-build](.github/actions/docker-image-build/action.yml) accepts `context`, `dockerfile`, `platforms`, `registry`, `image-name`, `registry-username`, optional `registry-token`, `docker-tag`, and `publish-latest`. Defaults are context `.`, Dockerfile `Dockerfile`, platform `linux/amd64`, registry `ghcr.io`, and the caller's repository as the image name. Registry values are hostnames, optionally with a port, not URLs; image names are registry-relative paths such as `team/api` or `team/api/service`.

Both Docker actions use the pinned [Docker metadata action](https://github.com/docker/metadata-action) to generate the calculated-version tag with highest priority, branch tags when applicable, and a short-SHA alias. Automatic latest generation is disabled; only an explicit production setting adds `latest`. Build feeds these tags and OCI labels into `docker/build-push-action` with `load: true` and `push: false`, then archives the primary candidate with its config digest and archive checksum.

[docker-image-push](.github/actions/docker-image-push/action.yml) accepts the same registry, image-name, credentials, version, and latest settings plus the loaded candidate's `tag`. Supply identical metadata inputs to build and push. It logs in, tags and pushes that exact candidate without rebuilding or modifying its OCI labels, checks every remote alias resolves to the same manifest digest, and matches the immutable manifest's config digest to the scanned Docker image ID. Signing and CD receive `<registry>/<image-name>@sha256:<digest>`, not a mutable alias.

Reusable CI exposes `build-context`, `platforms`, `registry`, `image-name`, and `registry-username`; CD receives the same registry/image/login inputs. Both accept the optional `registry-token` secret. GHCR defaults to `github.token`; other registries require an explicit token and compatible username. Give CI read/push permission and CD only the registry read permission it needs. Optional build login receives the supplied registry token only for push events, not PR/manual builds. The sample maps `vars.CONTAINER_REGISTRY`, `vars.CONTAINER_IMAGE`, `vars.REGISTRY_USERNAME`, and `secrets.REGISTRY_TOKEN` into these contracts.

The archive/config-digest contract supports one platform per candidate and rejects comma-separated platform lists. Publishing a multi-platform index would require building and scanning every constituent platform first; this workflow does not rebuild unscanned platforms during publication. Registry connections keep TLS verification enabled; configure trusted private CAs in runners rather than bypassing verification.

### CI stages

| Stage | Required behavior |
| --- | --- |
| `quality` | Locked restore, dotnet code style, CSharpier formatting, Roslyn analyzer and compiler warnings/errors, Hadolint warnings/errors |
| `secret-scan` | Gitleaks Git history and retained SARIF |
| `sast-scan` | Semgrep security rules and retained SARIF |
| `sca-scan` | Trivy source dependency audit; retains additional source secret/configuration checks |
| `iac-scan` | Checkov on rendered workload overlay, Dockerfile, and caller workflows; optional Snyk IaC |
| `codeql` | Hosted C# security-extended analysis |
| `pre-build-gate` | Quality and all five pre-build scanner jobs must succeed before build/test starts |
| `build-test` | Release analyzers/warnings as errors, configured unit and E2E suites, test evidence |
| `sonar` | Optional analysis and server quality gate; disabled job is recorded as skipped |
| `sca-scan-app` | Publish application, CycloneDX BOM, independent Trivy/Grype gates, optional Snyk and BOM ingestion |
| `calculate-version` | Full-history NBGV calculation for main/release tags, strict tag matching, release-track outputs |
| `image-build` | Metadata tags/OCI labels, single-platform build without push, archive checksum and Docker image ID |
| `container-security` | After image build, reload exact archive and run container-scan: independent Trivy/Grype gates and optional Snyk Container |
| `supply-chain-security` | Reload the same scanned archive and retain CycloneDX and SPDX image inventories for attestation |
| `security-gate` | Every required stage must succeed; failure, cancellation, or unexpected skip blocks release |
| `release` | Reload same archive, push without rebuilding, Cosign sign/SBOM attest/verify, GitHub provenance |
| `devsecops-scorecard` | Always retain actual stage outcomes, test/scanner configuration, source commit, run identity, and release digest |

Source audits run independently in parallel and block build/test through `pre-build-gate`. Published-application scanning and container build follow build/test; container scanning follows image build. SBOM generation follows container scanning. Signing and SBOM attestation execute only in `release`, after the central security gate succeeds and an immutable registry digest is available. SBOM generation alone does not claim signing or attestation success.

HIGH and CRITICAL vulnerability findings fail both application/image SCA scanners, including vulnerabilities without fixes; source SCA uses Trivy only. Checkov and Semgrep findings fail their own gates. Evidence and SBOMs are retained for 30 days; the large candidate archive is retained for 7 days. The reusable CI explicitly enforces findings and never uses `continue-on-error` or blanket soft-fail behavior. SARIF upload availability does not replace scanner exit status; fork PRs retain artifacts without attempting privileged SARIF uploads.

The pinned [Checkov GitHub action](https://github.com/bridgecrewio/checkov-action) scans each IaC target with CLI and SARIF output. Kustomize is rendered first so namespaces and image overrides are evaluated together; separate action steps scan the rendered workload, Dockerfile, and GitHub workflows, even if another scan finds violations. Directory mode runs one action step with the configured frameworks. Privileged ARC bootstrap templates are outside this workload scan. The sample documents two Deployment-specific exceptions: Microsoft UID 1654 and its unpublished source-overlay image placeholder. `require-docker-healthcheck: false` excepts only `CKV_DOCKER_2` for the shell-less chiseled runtime; Kubernetes probe checks remain enforced. Keep the default `true` for ordinary Docker images. These exceptions are not admission-time signature enforcement.

## Security action contracts

The action paths match the categories in the [reference action catalog](https://github.com/rahulmotvani0-sketch/devsecops-secure-cicd-template/tree/main/.github/actions). Inputs use this repository's hyphenated naming convention rather than the reference's underscore names.

Every catalog action ends with a `Record ... Status` step using the Bash-only [record-status](.github/actions/record-status/action.yml) action. It writes an emoji heading, tool, configured details, and actual step outcomes to `GITHUB_STEP_SUMMARY`. Completion labels such as `GENERATED` or `VERIFIED` require the operation steps to succeed; failures, cancellation, disabled operations, and report-only scans remain distinct. Step outputs and secrets are never rendered. All catalog actions require the complete catalog checkout at `.catalog` for this shared summary step. The CI scorecard also writes a tool/target/policy table directly from actual job outcomes, without fixed PASS, compliance, or SLSA claims.

| Action | Configuration and evidence |
| --- | --- |
| [secret-scan](.github/actions/secret-scan/action.yml) | Gitleaks Action v2 for enforced Git scans plus full-history validation; optional `config-path`, `gitleaks-license`, `scan-mode: git` or `dir`, `fail-on-leak`, redacted SARIF, artifact, and actual scanner outcomes |
| [sast-scan](.github/actions/sast-scan/action.yml) | `rules` accepts whitespace/newline-separated rulesets or local files; defaults include auto, security-audit, CI, and OWASP rules; findings fail; retained SARIF and outcome |
| [iac-scan](.github/actions/iac-scan/action.yml) | `mode: kustomize` preserves workload/Dockerfile/workflow checks; `mode: directory` accepts `frameworks`, including Terraform; optional `config-file`, `soft-fail`, `enable-snyk`, `snyk-token`, SARIF, and outcome |
| [sca-scan](.github/actions/sca-scan/action.yml) | `type`, `target`, `scope`, `severity`, `exit-code`, `scanners`, `skip-dirs`, `trivyignores`, and `enable-grype`; optional `enable-snyk`, `snyk-target`, `snyk-token`, and `dockerfile`; CycloneDX, SARIF, and per-scanner outcomes |
| [container-scan](.github/actions/container-scan/action.yml) | `image-ref`, `severity`, `exit-code`, `trivyignores`, and `enable-grype` forwarded to shared image SCA; optional `enable-snyk`, `snyk-token`, `dockerfile`, and `artifact-name`. CI names the shared artifact `image-security-evidence` without a duplicate workflow upload; standalone default remains `sca-image`, with 30-day retention and missing-file errors. |
| [sbom-generator](.github/actions/sbom-generator/action.yml) | `generator: trivy` (default) or `syft`, `type`, `target`, `scope`, and `output-directory`; exposes unchanged CycloneDX, SPDX JSON, and tab-separated dependency-table paths and retains all three |
| [image-signer](.github/actions/image-signer/action.yml) | `image-ref`, `registry`, `image-name`, exact `signing-identity`, `source-revision`, `source-ref`, `enable-attestation`, `sbom-path`, and `attestation-type`; validates predicate format before signing and retains verification results |

Scanner actions expose `upload-sarif`, defaulting to true. Direct consumers need `security-events: write` and code-scanning availability, or must disable upload. Fork callers must disable it. Reports remain artifacts even when upload is disabled or the scanner fails. Both `sca-scan` and `container-scan` require the complete catalog checked out at `.catalog` and call `security-scan` directly. SCA forwards every existing input unchanged; the container wrapper fixes type and scope to image. Existing Trivy/Grype defaults, tool versions, severity enforcement, ignore handling, artifact names, and upload behavior remain the same.

Snyk is centralized in `security-scan` and defaults to disabled through `enable-snyk: false`. Application scans keep `target` pointed at published files and set `snyk-target` to the application csproj so Snyk can find its restored NuGet assets. Image scans reuse `image-ref` and pass `dockerfile`. IaC scans pass the original IaC directory with `type: iac`, `scope: iac`, `enable-trivy: false`, and `enable-grype: false`; Checkov rendering and checks remain in `iac-scan`. Enabled Snyk scans require `snyk-token`, retain `snyk-{scope}.sarif`, optionally upload it, and enforce HIGH+ findings independently of `exit-code` or Checkov's `soft-fail`. Setup and scan outcomes are reported separately. The CI workflow enables Snyk through each public scanner action rather than calling it separately.

Direct shared scans can override `artifact-name` when multiple scans use the same scope in one workflow run.

Secret scanning follows the reference's marketplace-action approach using [Gitleaks Action v2](https://github.com/gitleaks/gitleaks-action/tree/v2) and Gitleaks 8.30.1. The requested `@v2` action reference is a mutable tag, not a commit pin; the scanner binary version remains fixed. Enforced Git scans first run the action's event-aware scan, then scan full checked-out history with the installed binary and retain the redacted report under the existing artifact path. Check out complete history with `fetch-depth: 0`. Directory scans and explicit report-only scans retain the pinned Docker CLI path because the marketplace action does not expose those controls. No blanket `continue-on-error` or fixed PASS summary is used. Vendor comments, artifact upload, and summaries are disabled; this catalog owns evidence and actual outcomes. The retained evidence step is not a duplicate: the vendor produces `results.sarif`, while the full-history and compatibility scans produce `artifacts/security/gitleaks.sarif`, which this catalog uploads as `secret-scan`.

Organization-owned repositories must supply a marketplace license through the action input or reusable CI secret `gitleaks-license`, for example by mapping it from the caller's `secrets.GITLEAKS_LICENSE`; personal repositories do not require it. Marketplace scans require GitHub API access and `pull-requests: read` for PR commit lookup; CI grants read-only permission and does not enable comments. Gitleaks Action v2 declares the Node 20 runtime; ensure the runner supports this action version. No insecure runtime opt-out is configured. Directory/report-only compatibility scans still require Docker but do not invoke the licensed marketplace action.

Standalone secret/IaC/SCA actions offer explicit report-only modes through `fail-on-leak: false`, `soft-fail: true`, and `exit-code: 0`. These are not security gates; summaries disclose the policy and scanner outcomes. Reusable CI hardcodes enforced settings and enables Grype for application/image scans. Grype gates at the lowest requested severity and every higher severity, even if Trivy receives a non-contiguous severity list. Scanner/runtime errors are not suppressed.

`sca-scan` defaults to `type: fs`, `target: .`, and `scope: app`; `repo` targets are local checked-out directories. Source CI uses `scope: source` and retains Trivy's additional secret/misconfiguration checks.

SBOM generation defaults to Trivy v0.76.2 and accepts `generator: syft` to use the pinned `anchore/syft:v1.57.0` container, without an unpinned installer. Syft generates both JSON formats in one invocation, using `dir:` for application output or `docker:` for the already loaded candidate; it does not pull a replacement candidate from a registry. Filesystem input is mounted read-only, with a separate writable output directory. Docker is required for the Syft branch. Invalid generator names fail before generation.

Set reusable CI input `sbom-generator: syft` to select Syft for the image inventory job; its job name and scorecard identify the selected tool. The separate inventories generated within `sca-scan` still use Trivy. Both standalone generators preserve output names, paths, artifact retention, and the shared tab-separated table derived from CycloneDX components. The table is an inventory, not a vulnerability report; successful summaries require the selected generator and table steps to succeed.

`image-signer` supports both `cyclonedx` and `spdxjson`, but GitOps promotion still requires a CycloneDX attestation, so reusable CI explicitly selects CycloneDX. Disabling attestation is only for standalone signature-only use. Signer verification binds the digest to the configured registry/image repository and signed claims to the caller repository, source commit, exact main/stable/RC ref, push event, workflow identity, and GitHub OIDC issuer; no wildcard identity or SLSA certification claim is introduced.

## GitOps contract

The CI workflow exposes `image` as `<registry>/<image-name>@sha256:<digest>`, defaulting to `ghcr.io/<application-repository>@sha256:<digest>`. Call `mehdihadeli/gha-workflows/.github/workflows/dotnet-cd.yml@main` in a dependent job from the same application run. Supply `image`, `source-revision`, `source-ref: ${{ github.ref }}`, `repo-url`, `username`, and the `gitops-token` secret. When overriding the registry or image name, pass the same values and registry read credentials to CD. Both templates own their jobs directly; no intermediate reusable workflow is required.

Promotion verifies the exact certificate identity and GitHub OIDC issuer, checks signed GitHub certificate claims for the caller repository, commit, source ref, and push event, and verifies the CycloneDX attestation. Only main and strict stable/RC refs are accepted; image references must match the configured registry/image repository exactly. Promotion resolves the actual source branch or tag through GitHub's commits API and skips the build if that ref no longer points to its source commit. It updates exactly one existing image entry, removes its mutable tag, and commits its digest. The GitOps bot needs repository write access, not cluster access. Concurrent GitOps writers cause a normal non-fast-forward failure; rerun after review rather than force-pushing.

The default manifest path is `environments/local/kustomization.yaml`, the image entry name is `simple-api`, and the tracked branch is `main`. The promotion workflow supports `environment`, `branch`, `manifest-path`, and `image-key` for other applications. Use a separate protected environment and narrowly scoped bot for each production target.

### CD stages

| Stage | Required behavior |
| --- | --- |
| `prepare` | Validate caller source commit/ref, immutable image binding, and required runtime configuration before approval |
| `verify` | Registry login, exact signer/source verification, signed CycloneDX attestation, and verified image output |
| `deploy` | Environment-specific deployment name, protected environment approval, re-verification at the write boundary, freshness check, and GitOps digest update |
| `wait-sync` | When enabled, observe exact desired-state revision, expected image, Synced, and Healthy |
| `smoke-tests` | After reconciliation, check deployed health and API response |
| `load` | Optional bounded k6 scenario after smoke |
| `dast` | Optional passive ZAP baseline after smoke |
| `runtime` | Require reconciliation, smoke, and every enabled runtime scanner before returning validated=true |
| `rollback` | Opt-in recovery after failed deployment checks, with prior-image verification and exact recovery reconciliation/smoke |
| `summary` | Always retain actual results, display deployment/recovery metadata, and optionally notify Slack on failure |

Promotion returns `gitops-revision`, `promotion-status` (`promoted`, `unchanged`, or `stale`), and `validated`. A no-op returns the existing GitOps HEAD; a stale application commit returns no revision and never runs runtime checks.

The stage structure follows the reference CD workflow, but remains a reusable `workflow_call` invoked after CI. It does not reconstruct an image from a tag, use wildcard certificate identities, simulate Argo sync, or directly mutate the Kubernetes cluster. Optional `version` is display metadata only. Main pushes target development and stable/RC tags target staging in the sample caller; `DEVELOPMENT_ENVIRONMENT` and `STAGING_ENVIRONMENT` default to `local` to retain the existing lab. Manifest and Application names follow the selected environment unless `GITOPS_MANIFEST_PATH` or `ARGOCD_APPLICATION` overrides them; `APPLICATION_URL` overrides the lab URL. Provision matching overlays, Argo Applications, and runtime endpoints before selecting another environment.

`validate-deployment: false` is explicitly promotion-only and returns `validated: false`. Enable it with an Argo CD API URL, single-source Application name, scoped `argocd-token`, and application URL. The observer needs only `applications,get` on that project/Application, not sync, update, admin, or Kubernetes permission. Argo polling requires the exact promoted revision, `Synced`, `Healthy`, and expected immutable image in its summary. Old healthy state cannot satisfy the gate. TLS verification stays enabled; `argocd-ca-file` supplies a trusted private CA. HTTP requires explicit `argocd-allow-http` and is for isolated labs only.

After reconciliation, HTTP smoke requires health HTTP 200 and a non-empty JSON API response of the configured kind. Optional k6 uses a caller-owned bounded scenario and rejects missing thresholds. Optional ZAP performs a passive baseline against an authorized target and fails on WARN, FAIL, or scanner error. It is not authenticated/API-complete DAST. Runtime artifacts and CD summaries are retained even on failure. Enabling k6/ZAP without deployment validation is an invalid configuration.

The application example has a disabled-by-default `deploy-prod` call. It requires a stable-tag `production` release and lower-environment `validated: true`, reuses the same CI digest, and passes through the protected `production` environment. Configure required reviewers and prevent self-review in GitHub; declaring `environment` alone does not create approval rules. Provision its separate GitOps overlay, Application, URLs, and scoped credentials before enabling it. Production receives the same sync and runtime validation as lower environments.

Enable `enable-rollback` only with `validate-deployment: true`; the sample exposes `ENABLE_ROLLBACK` for lower environments and `ENABLE_PRODUCTION_ROLLBACK` separately. Recovery runs after failed sync, smoke, or enabled runtime checks, never after cancellation, failed promotion, stale source, or an unchanged digest. It restores only the manifest changed by the failed promotion and refuses recovery if GitOps HEAD has advanced, the commit is a merge or changes other files, or the previous image is mutable. The prior digest must match the configured image repository and pass signature and CycloneDX attestation verification under the exact signer, GitHub issuer, caller repository, and push trigger. Its source is an earlier build, so recovery does not incorrectly bind that image to the failed build's SHA/ref.

Recovery pushes a new normal Git commit, without force-pushing or calling `argocd app rollback`. It applies the same protected environment rules, then observes the exact recovery commit and restored image and runs smoke checks. `rollback-status` is `rolled-back` only after those checks pass; `reverted` means desired state was restored but recovery validation did not complete, `superseded` means a newer GitOps commit was preserved, and `not-run` means recovery did not run. `rollback-revision` identifies the recovery commit. Recovery never changes the failed candidate's `validated: false` or clears the original workflow failure. Argo self-healing restores Git desired state; it does not automatically undo a bad Git commit.

Pass optional secret `slack-webhook-url` (sample secret `SLACK_WEBHOOK_URL`) for failure notification after recovery finishes. The webhook must be a Slack HTTPS incoming-webhook URL. Notifications include environment, digest, actual recovery status, and run link, not credentials. A notification failure is non-blocking and does not replace deployment failures. Without this secret, no notification is sent.

For private GHCR packages, the workflow token needs package access and Kubernetes needs a separately provisioned pull secret. Other private registries also need an appropriate Kubernetes pull secret; CI/CD registry credentials do not configure cluster authentication. The sample defaults to a public GHCR package and public GitOps read access so neither cluster pulls nor Argo CD require an administrator credential.

## Pinning and signer identity

External actions are pinned to commit SHAs except the explicitly requested Gitleaks `@v2` reference. NBGV and CSharpier intentionally install the latest stable tool on each run; these tool versions are not pinned. Catalog references use `main` for the initial local setup because this implementation has not been published yet. Before production use, publish the catalog and replace the workflow `uses: ...@main` references and their `catalog-ref: main` inputs with the same immutable catalog SHA. GitHub does not allow expressions in a reusable workflow's `uses` field.

Update `signing-identity` in both templates' calls to the exact CI reusable workflow identity, for example `https://github.com/mehdihadeli/gha-workflows/.github/workflows/dotnet-ci.yml@<catalog-SHA>` when called by SHA. Inspect a release certificate and confirm this identity before rollout; do not replace it with an unrestricted regular expression. The signing identity follows the reusable workflow, while signed GitHub certificate claims bind it to the caller's repository and commit. Previously signed images retain their original certificate identity; promoting those images requires explicitly supplying their original exact signer identity.

Container tools and ARC charts use explicit versions. For production, resolve container image tags to digests too, review upgrades, and add cluster admission verification if signatures must be enforced against every deployment path. CI verification alone does not prevent a privileged GitOps writer from editing manifests directly.

## Optional integrations

| Integration | Inputs and secret | Meaning |
| --- | --- | --- |
| Snyk | `enable-snyk`; secret `snyk-token` | Pinned CLI scans NuGet assets, IaC, and candidate image; HIGH+ blocks |
| Sonar | `enable-sonar`, `sonar-project-key`, `sonar-host-url`, optional organization; secret `sonar-token` | Pinned .NET scanner; server quality gate must succeed |
| Dependency-Track | `enable-dependency-track`, `dependency-track-url`; secret `dependency-track-api-key` | CycloneDX ingestion/inventory; accepted asynchronous upload is not another CVE gate |

Disabled tools are explicit configuration states. Enabled integrations with missing credentials or configuration fail. Fork PRs cannot access repository secrets, so enabling a token-backed scanner requires an intentional fork policy; this workflow does not execute fork code with privileged credentials. SonarCloud requires an organization; self-managed Sonar must support scanner 12.1.0. Use TLS and scoped service tokens outside the isolated lab. Local controllers do not install these optional services.

## Design references and limits

The supplied .NET CI/CD attachments and [DevSecOps platform template](https://github.com/abhishekpanda0620/devsecops-platform-template) informed stage ordering, separate source/application/image scans, explicit gates, evidence, and environment promotion. Its [architecture](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/architecture.md), [GitOps](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/gitops.md), [pipeline](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/pipelines.md), and [security](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/security.md) documents were reviewed. This implementation keeps Argo CD/k3d/ARC, not direct Azure/Flux deployment, simulated waits, wildcard signer identities, or simulated rollback.

License/EOL enforcement, authenticated DAST, cluster admission verification, monitoring, and multi-source Argo applications are not claimed by these workflows. GitHub provenance is evidence, not a claim of SLSA certification. Scanner rules/databases remain updateable even when scanner binaries are version-pinned.

Run focused version regressions with `python3 -m unittest discover -s .github/actions/calculate-version -p 'test_*.py' -v` and reconciliation regressions with `python3 -m unittest discover -s .github/actions/argocd-wait -p test_wait.py -v`.

Run guarded rollback regressions with `python3 -m unittest discover -s .github/actions/promote-gitops -p test_rollback.py -v`. They use real temporary Git repositories with isolated registry-tool mocks; they do not push to the configured deployment repository.

## Documentation

- [Project overview](docs/PROJECT_OVERVIEW.md): scope, components, and consumer responsibilities.
- [Architecture](docs/architecture.md): execution boundaries, candidate identity, and signing trust.
- [Pipelines](docs/pipelines.md): job dependencies, release policy, inputs, and evidence.
- [GitOps](docs/gitops.md): target setup, digest promotion, exact reconciliation, and guarded recovery.
- [Roadmap](docs/ROADMAP.md): implemented baseline, rollout checks, and proposed extensions.

- [GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
- [ARC getting started](https://docs.github.com/en/actions/tutorials/use-actions-runner-controller/get-started)
- [ARC runner scale-set values](https://github.com/actions/actions-runner-controller/blob/master/charts/gha-runner-scale-set/values.yaml)
- [Argo CD automated sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
