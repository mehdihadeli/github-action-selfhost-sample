# Architecture

`gha-workflows` separates application validation, release publication, desired-state changes, and cluster reconciliation. The two [reusable workflows](../.github/workflows) own their jobs directly; composite actions implement the individual operations.

Read [project overview](PROJECT_OVERVIEW.md) for onboarding, [pipelines](pipelines.md) for job contracts, and [GitOps](gitops.md) for deployment and recovery operations.

## System boundaries

| Boundary | Owns | Does not own |
| --- | --- | --- |
| Application repository | Source, lock files, tests, Dockerfile, version manifest, caller events and environment policy | Catalog implementation or cluster administration |
| Catalog repository | Reusable CI/CD, composite actions, validation scripts, and evidence policy | Application source or per-environment credentials |
| GitHub-hosted execution | PR/manual candidate work, designated source/gate jobs, and CodeQL | Access to local-only deployment endpoints |
| Configured runners | Main-push candidate work, eligible release publication, and deployment operations | An unrestricted trust boundary for arbitrary PR code |
| OCI registry | Immutable manifests, aliases, signatures, SBOM attestations, and provenance | Deployment approval or Kubernetes pull credentials |
| GitOps repository | Versioned Kustomize desired state and promotion/recovery commits | Application compilation or signature policy by itself |
| Argo CD | Pull, render, reconcile, and report application state | CI compilation or automatic reversal of a bad Git commit |
| Kubernetes | Run workloads and pull the selected image | Automatically inherit the workflow's registry login |

The companion lab places ARC and Argo CD in a k3d cluster and uses Gitea as the GitOps server. Their provisioning files live in the application sample, outside this catalog. The same delivery contracts can target another existing Kubernetes installation if the runner network, manifests, registry, and Argo Application are configured accordingly. No cloud provisioning workflow is included.

## Execution model

Both entry points use `workflow_call`; the application caller selects events. CI does not autonomously watch all consuming repositories. CD is invoked after a successful image release in the same application run and validates its source metadata against that run.

The workflows check out application history and the catalog separately. Source checkout disables persisted Git credentials; the catalog is checked out at `.catalog` using `catalog-ref`. Local action references and sibling scripts depend on that complete checkout.

Most CI jobs choose configured `runner` only for a push to `refs/heads/main`; otherwise they use `ubuntu-latest`. CodeQL, version calculation, and central gates remain hosted. The eligible `release` job always uses configured `runner`, including stable and RC tags. CD verification, deployment, reconciliation, smoke, optional scanners, and recovery also use configured runners; its preparation, validation gate, and summary use hosted runners.

This distinction matters for capacity and networking. A release tag still needs the configured release runner. A hosted gate can consume job metadata, but it cannot replace a runner that must reach private Gitea, Argo CD, or application endpoints.

## Candidate identity across jobs

The architecture preserves three different identifiers:

| Identifier | Meaning | Check |
| --- | --- | --- |
| Archive SHA-256 | Integrity of the transported image archive | [image-load](../.github/actions/image-load/action.yml) checks the downloaded archive |
| Docker image ID/config digest | Identity of the loaded local candidate | Reloaded candidate must match the build output |
| Registry manifest digest | Immutable published image reference | Publication checks remote configuration against the candidate and aliases against the same manifest |

[docker-image-build](../.github/actions/docker-image-build/action.yml) builds with `load: true` and `push: false`. Container scanning, image inventory generation, and release reload the candidate rather than rebuilding it. [docker-image-push](../.github/actions/docker-image-push/action.yml) pushes aliases for that loaded candidate, preserves OCI labels, and verifies the remote manifest/configuration relationship.

The result passed to CD is `<registry>/<image-name>@sha256:<digest>`. A version or short-SHA tag is a lookup alias, not deployment identity. The archive contract supports one platform. Multi-platform publication would need scanning and identity checks for every platform and is not implemented.

## Layered checks

| Layer | Checks | Decision boundary |
| --- | --- | --- |
| Source | .NET style/analyzers, Hadolint, Gitleaks, Semgrep, Trivy dependencies, Checkov, CodeQL | `pre-build-gate` blocks build/test |
| Application output | Locked build/tests, published-output Trivy and Grype, optional Snyk/Sonar | `security-gate` blocks release |
| Container | Exact candidate reload, Trivy and Grype, optional Snyk, CycloneDX/SPDX inventory | `security-gate` blocks release |
| Release | Remote digest/config verification, Cosign signing, SBOM attestation, GitHub provenance | CI returns `image` only after completion |
| Promotion | Exact repository/digest/source/signer verification and source freshness | Protected `deploy` job writes GitOps |
| Deployment | Exact Argo revision/image, Synced/Healthy, HTTP smoke, every enabled k6/ZAP check | `runtime` returns `validated=true` |

Checkov evaluates the rendered Kustomize overlay, Dockerfile, and caller workflows. It does not treat privileged ARC provisioning templates as the application's workload scan. Application/image vulnerability checks enforce HIGH and CRITICAL findings even when no fix exists. Reusable CI uses enforced policy; standalone actions' explicit report-only modes do not provide release authorization.

## Signing trust

The [image verifier](../.github/actions/verify-image/verify.sh) accepts only the configured registry/image repository and an immutable digest. Verification requires the exact signing workflow identity and GitHub OIDC issuer, signed caller repository, source commit, exact accepted main/stable/RC ref, push trigger, and CycloneDX attestation.

The signing workflow identity and application source identity are separate. An exact reusable workflow identity alone does not bind an image to a particular consumer commit. Both checks are needed.

Catalog references currently default to `main`. Before production, publish the catalog and pin both the caller's workflow reference and `catalog-ref` to the same immutable catalog commit. Configure `signing-identity` in CI and CD to match the actual reusable signing workflow certificate. Older images retain their older certificate identity; changing catalog references does not re-sign them.

Most external actions are SHA-pinned. Gitleaks Action intentionally uses mutable `@v2`; NBGV and CSharpier intentionally install latest stable releases. Explicit container tool versions are not equivalent to image digest pins. Treat these exceptions as upgrade and reproducibility risks, not as universal pinning.

## Credential and network model

| Identity | Minimum intended access |
| --- | --- |
| CI release job | Registry push, GitHub OIDC token, and provenance permissions |
| CD verification/deployment | Registry read and application source metadata read |
| GitOps bot | Write to the configured desired-state repository/branch |
| CD Argo observer | `applications,get` for the intended project/Application |
| Argo CD | Read GitOps and reconcile approved resources in its destination |
| Kubernetes image pull | Separately provisioned read access for a private registry |
| ARC controller | GitHub runner registration, provisioned outside the workflows |

The catalog never accepts a kubeconfig or Argo CD administrator token. Deployment commits Git; observation reads the Argo API. Required reviewers and prevention of self-review must be configured in GitHub environments, not merely declared in workflow YAML.

Restrict ARC runner groups to approved repositories/workflows. Do not run untrusted PR code through `pull_request_target` on privileged runners. Ephemeral runners reduce persistence but do not make privileged Docker or network access safe for untrusted code. The lab is not evidence of multi-tenant isolation.

Keep TLS verification enabled. Runners need trusted private registry CAs; Argo observation accepts a trusted CA file. Plain HTTP observation is an explicit isolated-lab opt-in. Workflow registry login neither configures Argo Git credentials nor creates Kubernetes image pull secrets.

## Desired state and recovery

The [promotion script](../.github/actions/promote-gitops/promote.sh) resolves the actual application branch or tag commit, rejects stale builds without writing, changes one existing image entry, deletes `newTag`, and commits `newName` plus `digest`. Concurrent writers cause ordinary non-fast-forward failures; there is no force push.

Argo CD reconciles the new desired state. Its self-healing corrects live drift back to Git; it does not decide that an application version is bad and rewrite Git.

Opt-in [recovery](../.github/actions/promote-gitops/rollback.sh) validates the failed promotion commit and prior signed digest before creating a new desired-state commit. It refuses to overwrite newer GitOps work. Recovery must reconcile its own exact commit/image and pass smoke before reporting `rolled-back`. The original candidate remains failed and unvalidated.

## Evidence and limitations

[record-status](../.github/actions/record-status/action.yml) reports actual action outcomes; [pipeline-evidence](../.github/actions/pipeline-evidence/evidence.py) checks required job results and retains metadata. Scanner reports, tests, inventories, release identity, and deployment evidence answer different questions and should not be conflated. A generated SBOM is an inventory; a signature is a source assertion; a passing smoke check is bounded runtime evidence.

The catalog does not install admission signature enforcement, telemetry backends, runtime intrusion detection, license/EOL gates, scheduled rescanning, or progressive delivery. A privileged GitOps writer can bypass the CI promotion path unless external repository and admission policies prevent it. See [roadmap](ROADMAP.md) for proposed controls and operational validation criteria.

## References

- [GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
- [ARC getting started](https://docs.github.com/en/actions/tutorials/use-actions-runner-controller/get-started)
- [Argo CD automated sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [Design reference architecture](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/architecture.md)
