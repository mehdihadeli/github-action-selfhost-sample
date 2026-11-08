# .NET DevSecOps on ARC, k3d, and Argo CD

This sample runs GitHub Actions jobs on ephemeral Kubernetes runners managed by Actions Runner Controller (ARC). Reusable workflows in [mehdihadeli/gha-workflows](https://github.com/mehdihadeli/gha-workflows) build the .NET 10 application, scan it, publish a signed GHCR image, and commit its digest to Gitea. Argo CD reconciles that Git commit into Kubernetes.

ARC connects to GitHub, not Gitea Actions. Keep the application and catalog on GitHub; Gitea hosts local GitOps state. The previous Tekton instructions no longer apply. [deployments/repo.yaml](deployments/repo.yaml) is a legacy PaC manifest and is not used here.

## Prerequisites

- Git Bash on Windows, Docker Desktop, k3d, kubectl, Helm 3 or later, and .NET 10 SDK for local builds.
- A GitHub application repository and the published workflow catalog. The catalog remote is already configured; the application needs its own GitHub remote.
- GitHub App authentication for ARC, or a classic PAT for an isolated local trial.
- Gitea running as Docker container `gitea` at `http://localhost:3000`.
- Free ports 6550 (Kubernetes API), 8081 (application ingress), and enough resources for two Kubernetes nodes, Argo CD, and up to three runner pods. Each runner/DinD pair can use up to 4 CPU and 4 GiB. Reduce `maxRunners` for a smaller machine.

Run commands from this application's repository root. Bootstrap creates `github-devsecops`, leaves existing clusters untouched, uses explicit Kubernetes contexts, and restores the previous current context. Do not downgrade the .NET target framework.

## Application tests

[tests/SimpleApi.Tests](tests/SimpleApi.Tests) contains xUnit v3 app integration tests with Shouldly assertions. `WebApplicationFactory` runs the real application in an in-memory TestServer; no running API, container, cluster, or network port is needed.

```bash
dotnet restore tests/SimpleApi.Tests/SimpleApi.Tests.csproj --locked-mode
dotnet test tests/SimpleApi.Tests/SimpleApi.Tests.csproj --configuration Release --no-restore --logger trx --results-directory artifacts/tests/local
```

The suite checks the exact health response, five weather forecasts with bounded local dates, Celsius bounds, allowed summaries, and Fahrenheit conversion. It also checks the Development OpenAPI schema, OpenAPI absence in Production and Staging, unknown routes, and unsupported weather requests. Date assertions allow midnight to fall during a request without fixing the clock or changing application behavior; random forecasts are checked against their contract rather than a fixed sequence.

The test project pins xUnit v3 `3.2.2` for compatibility with the caller's VSTest mode on .NET 10. Commit [tests/SimpleApi.Tests/packages.lock.json](tests/SimpleApi.Tests/packages.lock.json) alongside the project so CI's locked restore uses the same dependencies. TRX evidence is retained by CI; coverage collection remains disabled.

## 1. Seed GitOps state in Gitea

Follow [deployments/gitea-setup/README.md](deployments/gitea-setup/README.md) to create `admin/simple-api-gitops` and populate it with the contents of [deployments/gitops](deployments/gitops). Its repository root must contain `base/` and `environments/`, without a `deployments/gitops` wrapper.

The initial [Kustomization](deployments/gitops/environments/local/kustomization.yaml) uses an unpublished `bootstrap` tag. Do not create the Argo CD Application until CI replaces it with a verified digest.

## 2. Install local controllers

Source: [deployments/local/bootstrap.sh](deployments/local/bootstrap.sh)

```bash
bash deployments/local/bootstrap.sh cluster
```

This installs ARC chart `0.15.1` and Argo CD `v3.6.1` into separate namespaces. It attaches Gitea to the dedicated k3d network and creates a Service/EndpointSlice for this internal clone URL:

```text
http://gitea.gitops-system.svc.cluster.local:3000/admin/simple-api-gitops.git
```

Runners and Argo CD use that same address. Rerun the `cluster` phase if Gitea is recreated so its container IP is refreshed. No data volumes are removed.

The application namespace enforces restricted pod security. ARC's [DinD template](deployments/local/arc-values.yaml) uses a privileged Docker sidecar with ephemeral workspace/socket volumes, not the host Docker socket. This is an isolated-lab compromise, not a production security boundary. Do not assign untrusted PR code to these runners. Kubernetes container mode is a different execution model and cannot directly replace this Docker-based pipeline.

## 3. Authenticate ARC and register runners

Create a GitHub App following [ARC authentication documentation](https://docs.github.com/en/actions/how-tos/manage-runners/use-actions-runner-controller/authenticate-to-the-api), install it on your application repository, and store its private key outside Git. Create the Secret directly in your terminal:

```bash
kubectl --context k3d-github-devsecops -n arc-runners create secret generic arc-github-auth \
  --from-literal=github_app_id='<APP_ID>' \
  --from-literal=github_app_installation_id='<INSTALLATION_ID>' \
  --from-file=github_app_private_key='/secure/path/github-app.pem'
```

For a short repository-level trial, store a classic PAT in a protected file outside the repository and create the same Secret with `--from-file=github_token='/secure/path/github-pat.txt'` instead. Use the required repository scope; check official guidance for organization registration. Never put token values in Helm values, Git, chat, or shell history.

```bash
export GITHUB_CONFIG_URL=https://github.com/mehdihadeli/dotnet-github-action-self-host-runner
bash deployments/local/bootstrap.sh runners
```

Change the URL to your actual application repository. Bootstrap builds [deployments/local/runner.Dockerfile](deployments/local/runner.Dockerfile), imports it into k3d, and installs `arc-devsecops`. The runner includes Git, curl, jq, Python, Docker CLI, and .NET runtime dependencies; CI installs the SDK per job.

Run **ARC runner smoke** manually in GitHub, then inspect:

```bash
kubectl --context k3d-github-devsecops get pods -n arc-systems
kubectl --context k3d-github-devsecops get pods -n arc-runners
helm --kube-context k3d-github-devsecops list -A
```

`runs-on: arc-devsecops` must match `runnerScaleSetName`. Zero idle runners is expected because `minRunners` is zero. The listener remains running; GitHub jobs create ephemeral runner pods.

## 4. Configure GitHub

Publish the catalog changes before running [the application caller](.github/workflows/ci-cd.yml). These are separate Git repositories; workflows must be inside `.github/workflows` in each published repository.

Create these application repository settings:

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `GITOPS_REPO_URL` | `http://gitea.gitops-system.svc.cluster.local:3000/admin/simple-api-gitops.git` |
| Variable | `GITOPS_USERNAME` | Dedicated Gitea promotion bot username |
| Repository secret | `GITOPS_TOKEN` | Bot's repository write token |
| Environment | `local` | Restrict deployment branches to `main`; add reviewers where supported |

Keep `GITOPS_TOKEN` as a repository secret so the caller can pass it to `workflow_call`. An environment-only secret is not visible to the caller job. The called promotion job uses `local` for approval and deployment policy.

The sample expects a public GitHub repository for CodeQL; private repositories need the applicable GitHub Code Security entitlement. Require quality/security checks through branch protection. Restrict ARC runner-group repository/workflow access for organization runners.

Main-branch pushes use ARC. PRs and manual CI dispatches use hosted runners and cannot publish or promote. The caller supplies the app test project through `test-project` with `test-platform: vstest` and `require-tests: true`; container health is checked separately. Configured suites must produce nonzero TRX counters. Coverage is an explicit VSTest collector opt-in and remains disabled for this sample.

Optional repository variables and secrets are already wired in the caller:

| Variables | Repository secrets | Enables |
| --- | --- | --- |
| `ENABLE_SNYK=true` | `SNYK_TOKEN` | NuGet, IaC, and container policy scans |
| `ENABLE_SONAR=true`, `SONAR_PROJECT_KEY`, `SONAR_ORGANIZATION`, optional `SONAR_HOST_URL` | `SONAR_TOKEN` | Sonar analysis and server quality gate |
| `ENABLE_DEPENDENCY_TRACK=true`, `DEPENDENCY_TRACK_URL` | `DEPENDENCY_TRACK_API_KEY` | Asynchronous CycloneDX inventory ingestion, not another release vulnerability gate |
| `VALIDATE_DEPLOYMENT=true`, `ARGOCD_SERVER`, optional `ARGOCD_CA_FILE` | `ARGOCD_TOKEN` | Exact-revision reconciliation plus deployed HTTP/JSON smoke |
| `ENABLE_K6=true` | None | Bounded performance thresholds after reconciliation |
| `ENABLE_ZAP=true` | None | Passive baseline after reconciliation; warnings/errors block |

Unset flags mean explicitly disabled integrations, not successful scans. Enabled token-backed integrations fail if credentials are missing; fork PRs cannot access those secrets. Optional services are not installed by the local controller bootstrap.

## 5. Release and promote

Push catalog and application changes to their respective `main` branches. CI separates quality, source security, IaC, CodeQL, build/tests, application SCA, candidate image build, image SCA, central security gate, release, and evidence. Gitleaks scans Git history, Semgrep scans source, Hadolint checks Dockerfile warnings/errors, and Checkov scans the rendered local overlay, Dockerfile, and caller workflows. Published .NET output and the candidate image each receive independent Trivy/Grype HIGH+ scans and CycloneDX SBOMs.

The container is built once and checked through `/health`. Its archive checksum and Docker image ID are validated whenever another job loads it. Release requires all configured gates, pushes that loaded image without rebuilding, signs its registry digest and image SBOM, verifies both, and creates GitHub build provenance. The caller grants `attestations: write` for that final evidence step.

Promotion verifies the exact signer identity, caller repository, caller commit, and SBOM before updating `environments/local/kustomization.yaml` in Gitea. Inspect that commit: it must contain `digest: sha256:...` and no `newTag`. Evidence/SBOMs are retained for 30 days and the candidate archive for 7 days. kubectl is used only to render Kustomize locally for policy scanning; no workflow gets kubeconfig, cluster write credentials, or an Argo administrator token.

The source Deployment documents Checkov exceptions for Microsoft UID 1654 and the pre-promotion image placeholder. The caller explicitly disables only Docker's `HEALTHCHECK` requirement because the chiseled image has no shell/probe executable; Kubernetes startup, readiness, and liveness probes remain mandatory. Review these exceptions with the workload rather than disabling scanners.

Make the GHCR package public after the first push for this local sample. GitHub can default packages to private even for public repositories; private packages require a separately provisioned Kubernetes pull secret. Promotion replaces the example image repository name with the actual caller repository.

Catalog calls currently use `main` for bootstrap. Before production, pin both workflow calls and `catalog-ref` inputs to the same published SHA and update `signing-identity` to match the reusable CI workflow ref. See [catalog pinning guidance](https://github.com/mehdihadeli/gha-workflows#pinning-and-signer-identity). Do not broaden signer verification to arbitrary workflows.

## 6. Enable Argo CD reconciliation

After the verified digest is committed in Gitea:

```bash
bash deployments/local/bootstrap.sh application
kubectl --context k3d-github-devsecops get application simple-api-local -n argocd
kubectl --context k3d-github-devsecops rollout status deployment/simple-api -n simple-api --timeout=5m
curl --fail http://localhost:8081/health
curl --fail http://localhost:8081/weatherforecast
```

The [AppProject](deployments/argocd/project.yaml) permits only one source repository, one namespace, and the required workload kinds. The [Application](deployments/argocd/application.yaml) enables auto-sync, pruning, and self-healing. Workloads use non-root UID, read-only filesystem, dropped capabilities, probes, and ingress-only NetworkPolicy from Traefik.

Check both `Synced` and `Healthy`; a promotion commit alone does not prove deployment succeeded. Argo CD polls Git, so reconciliation is not necessarily immediate.

### Enable read-only pipeline validation

First complete the initial promotion and create the Application. Then apply the AppProject containing its `ci-observer` role and generate an expiring project-role token through Argo CD's project role UI or CLI. The role permits only `applications,get` for `simple-api/simple-api-local`; store the generated token directly as `ARGOCD_TOKEN`, never in chat or Git. It cannot sync, update Applications, or write Kubernetes resources.

Set `ARGOCD_SERVER` to a runner-reachable HTTPS endpoint, such as `https://argocd-server.argocd.svc` when using its matching internal certificate. Trust its public CA certificate through a repository-relative PEM file named by `ARGOCD_CA_FILE`, or use a certificate trusted by the runner. Do not disable certificate verification. The localhost UI port-forward is not reachable as localhost inside ARC pods.

Set `VALIDATE_DEPLOYMENT=true`. The caller's application URL is the cluster Traefik Service, not workstation `localhost:8081`. CD waits up to 15 minutes for the exact promoted GitOps revision, `Synced`, `Healthy`, and expected digest, then requires `/health` HTTP 200 and non-empty `/weatherforecast` JSON. A stale source build skips runtime validation; a no-op promotion waits for the existing GitOps HEAD. Disabled validation reports promotion-only and returns `validated: false`.

Enable k6 only after connectivity works. [deployments/validation/smoke-load.js](deployments/validation/smoke-load.js) uses 5 virtual users for 20 seconds and enforces failure-rate, p95 latency, and five-forecast checks. Enable ZAP only against a target you own or are authorized to assess. Its bounded passive baseline fails on warnings or errors and does not claim authenticated or comprehensive API DAST. Runtime reports are retained on failure.

### Optional production promotion

The `production` caller is disabled by default. Provision a separate `environments/production/kustomization.yaml` in the production GitOps repository, its Argo Application, and a protected `production` GitHub environment with reviewers and main-only deployment policy. Configure `PRODUCTION_GITOPS_REPO_URL`, `PRODUCTION_GITOPS_USERNAME`, `PRODUCTION_ARGOCD_SERVER`, `PRODUCTION_ARGOCD_APPLICATION`, `PRODUCTION_APPLICATION_URL`, optional `PRODUCTION_ARGOCD_CA_FILE`, and repository secrets `PRODUCTION_GITOPS_TOKEN`/`PRODUCTION_ARGOCD_TOKEN`.

Only then set `ENABLE_PRODUCTION=true`. It requires successful lower-environment `validated: true` and promotes the same CI digest without rebuilding, then runs production reconciliation and smoke. The sample does not create production infrastructure or automatically roll back bad Git commits.

For the UI, run this in a separate terminal and open `https://localhost:8082`:

```bash
kubectl --context k3d-github-devsecops -n argocd port-forward service/argocd-server 8082:443
```

Retrieve the initial administrator password directly in your terminal, change it, and do not share it in chat. Argo CD is not exposed through public ingress.

## Troubleshooting and limits

- Queued jobs: check GitHub URL, App installation, Secret keys, scale-set name, and runner-group permissions. Inspect listener/controller logs without printing Secrets.
- Docker unavailable: run **ARC runner smoke** and inspect the DinD startup probe.
- Gitea unreachable: rerun `bootstrap.sh cluster` and inspect `gitea-external` EndpointSlice in `gitops-system`.
- CodeQL denied: check repository entitlement and `security-events: write`.
- Security findings: fix them or review narrow, documented exceptions. HIGH/CRITICAL findings block release, including findings without available fixes.
- Signature failure: check reusable workflow ref, catalog pin, and caller commit. Never bypass verification.
- `ImagePullBackOff`: confirm digest and package visibility, or provision a scoped pull secret referenced through GitOps.
- Argo CD source denied: keep URL identical in variables, Application, and AppProject, including `.git` suffix.
- GitOps push rejected: review concurrent changes and rerun; promotion never force-pushes.

Rollback means reverting the GitOps digest commit to a previously verified image, not redeploying a mutable tag. Production also needs TLS, encrypted Secret storage, retained ARC logs, stronger runner isolation, and admission-time signature policy. CI verification does not prevent privileged GitOps writers from bypassing the pipeline.

## References

- [GitHub ARC tutorial](https://docs.github.com/en/actions/tutorials/use-actions-runner-controller/get-started)
- [ARC project](https://github.com/actions/actions-runner-controller)
- [Argo CD auto-sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [ASP.NET Core health checks](https://learn.microsoft.com/aspnet/core/host-and-deploy/health-checks?view=aspnetcore-10.0)
