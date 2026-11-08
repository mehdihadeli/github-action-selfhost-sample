# Project overview

`gha-workflows` is a reusable GitHub Actions catalog for .NET application delivery. It checks source code, builds and scans a single container candidate, publishes and signs its immutable digest, and updates a separate GitOps repository. Argo CD reconciles that repository into Kubernetes; the delivery workflow observes reconciliation and checks the deployed application.

This repository contains delivery automation, not an application or a cloud provisioning platform. The companion .NET sample supplies the application, Dockerfile, caller workflow, Kustomize manifests, and local k3d/ARC/Argo CD setup.

## Documentation map

| Guide | Use it to answer |
| --- | --- |
| [Architecture](architecture.md) | What runs where, and which identities can cross each trust boundary? |
| [Pipelines](pipelines.md) | Which jobs run, what blocks release, and what does the caller configure? |
| [GitOps](gitops.md) | How does a verified digest reach Kubernetes, and how does recovery work? |
| [Roadmap](ROADMAP.md) | What exists now, what still needs operational validation, and what is proposed? |
| [Catalog README](../README.md) | What are the detailed action contracts and consumer requirements? |

## Goals

- Reuse the same quality, security, release, and deployment policy across .NET repositories.
- Reject failed, cancelled, or unexpectedly skipped required checks before publication.
- Publish the candidate that was scanned, without rebuilding it at release time.
- Bind deployment to an image digest, source repository, commit, release ref, and exact signer identity.
- Give automation GitOps write access and scoped observation access rather than cluster administrator credentials.
- Retain actual outcomes and reports, including failures and explicitly disabled integrations.

## Repository layout

```text
gha-workflows/
  .github/
    workflows/
      dotnet-ci.yml
      dotnet-cd.yml
    actions/
      <action-name>/action.yml
      argocd-wait/wait.py
      calculate-version/calculate-version.sh
      pipeline-evidence/evidence.py
      promote-gitops/promote.sh
      promote-gitops/rollback.sh
      verify-image/verify.sh
  docs/
    PROJECT_OVERVIEW.md
    architecture.md
    pipelines.md
    gitops.md
    ROADMAP.md
  scripts/smoke-test.sh
  README.md
  LICENSE
```

GitHub discovers the reusable workflows under [`.github/workflows`](../.github/workflows). Composite actions live under [`.github/actions`](../.github/actions). Consumers must check out the complete catalog at `.catalog`: nested composites use `./.catalog/.github/actions/...`, and some actions call sibling scripts. Copying an individual action directory is not sufficient.

## Components and responsibilities

| Component | Responsibility | Implementation |
| --- | --- | --- |
| Reusable CI | Source gates, tests, candidate build, artifact scans, release, and evidence | [dotnet-ci.yml](../.github/workflows/dotnet-ci.yml) |
| Reusable CD | Source validation, image verification, environment approval, promotion, deployed checks, and recovery | [dotnet-cd.yml](../.github/workflows/dotnet-cd.yml) |
| .NET quality | Locked restore, code style, CSharpier, Roslyn analyzers, and warnings-as-errors build | [dotnet-quality](../.github/actions/dotnet-quality/action.yml) |
| Source security | Gitleaks history, Semgrep, Trivy dependencies, Checkov, and hosted CodeQL | [CI source jobs](../.github/workflows/dotnet-ci.yml) |
| Artifact security | Independent Trivy and Grype application/image checks; optional Snyk | [security-scan](../.github/actions/security-scan/action.yml) |
| Inventory | CycloneDX, SPDX JSON, and a readable dependency table using Trivy or Syft | [sbom-generator](../.github/actions/sbom-generator/action.yml) |
| Candidate transport | Archive checksum and Docker image ID checks between isolated jobs | [image-load](../.github/actions/image-load/action.yml) |
| Publication | Push the loaded candidate and verify remote aliases/configuration | [docker-image-push](../.github/actions/docker-image-push/action.yml) |
| Release identity | Cosign signature, signed SBOM attestation, and verification | [image-signer](../.github/actions/image-signer/action.yml) |
| Desired-state update | Verify the image and update exactly one existing Kustomize image entry | [promote-gitops](../.github/actions/promote-gitops/action.yml) |
| Reconciliation observer | Poll the exact GitOps revision, expected image, Synced, and Healthy state | [argocd-wait](../.github/actions/argocd-wait/action.yml) |
| Deployed checks | Required HTTP smoke when validation is enabled; optional k6 and passive ZAP | [HTTP smoke](../.github/actions/http-smoke/action.yml), [k6](../.github/actions/k6/action.yml), [ZAP](../.github/actions/zap-baseline/action.yml) |
| Evidence | Per-action status and central CI/CD reports based on actual results | [record-status](../.github/actions/record-status/action.yml), [pipeline-evidence](../.github/actions/pipeline-evidence/action.yml) |

## Delivery walkthrough

1. The application repository calls reusable CI for its configured events. Pull requests and manual runs build and scan without publishing.
2. Source quality and security jobs run in parallel. A pre-build gate requires them all to succeed.
3. CI builds and tests the .NET application, scans published output, and calculates release metadata for eligible refs.
4. CI builds one platform into a local candidate archive, reloads it for image scanning, and generates inventories from the same candidate.
5. The central security gate checks every required result. Eligible pushes then publish the loaded candidate, verify the registry digest, sign it, attest its CycloneDX SBOM, and generate GitHub provenance.
6. The caller passes CI's immutable `image` output and source metadata to reusable CD.
7. CD verifies the release, obtains configured environment approval, re-verifies at the write boundary, checks source freshness, and commits the digest to GitOps.
8. Argo CD pulls desired state and deploys it. When deployment validation is enabled, CD observes the exact revision/image and runs smoke plus every enabled runtime check.
9. A failed deployed check can trigger opt-in guarded recovery. Successful recovery does not turn the failed candidate into a validated release.

## What the consumer supplies

| Consumer-owned resource | Requirement |
| --- | --- |
| Application | .NET project or solution, publish project when needed, committed NuGet lock files, configured test projects |
| Container | Dockerfile, one target platform, and a registry/image repository |
| Version history | Root `version.json`, full Git history, and matching stable/RC release tags |
| Workflow policy | Caller events, permissions, protected branches/tags, and immutable catalog references before production use |
| Runner infrastructure | Approved ARC runner group/scale set and required runner tools; hosted capacity for designated jobs |
| GitOps | Existing branch and Kustomize image entry, a scoped write token, and an Argo CD Application |
| Deployment observation | Reachable Argo CD and application URLs, read-only Application token, and trusted CAs where needed |
| Production | Separate overlay/Application/endpoint, protected environment reviewers, and an explicit promotion policy |

The companion sample uses a local k3d cluster, ARC runners, Argo CD, and Gitea for GitOps. Gitea does not host the GitHub Actions execution plane. These services belong to the sample deployment, not this catalog.

## Optional integrations

Snyk, Sonar, and Dependency-Track are disabled unless explicitly enabled. Enabled integrations require their configuration and secrets. Snyk HIGH+ findings and the Sonar server quality gate block release; an accepted Dependency-Track upload records inventory ingestion, not a completed asynchronous vulnerability assessment.

k6 and passive ZAP are optional deployed checks. Both require deployment validation, reachable authorized targets, and caller-owned configuration. Passive ZAP is not authenticated or API-complete DAST.

## Current limits

The catalog does not provision cloud infrastructure, install a monitoring stack, enforce image signatures at Kubernetes admission, or implement scheduled rescanning, license/EOL policy, multi-platform publication, or multi-source Argo CD observation. GitHub provenance and SBOMs are evidence, not SLSA certification or proof of compliance.

Implemented workflow logic is distinct from verified operation in a particular installation. A local test or mock cannot establish live registry/OIDC signing, environment approval, Argo reconciliation, or successful rollback. The [roadmap](ROADMAP.md) keeps those rollout checks separate from future features.

## Design reference

The documentation topics were inspired by the [DevSecOps platform template documentation](https://github.com/abhishekpanda0620/devsecops-platform-template/tree/main/docs). This guide describes this catalog's implementation and does not inherit the reference project's infrastructure, tooling, or production-readiness claims.
