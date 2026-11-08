# Roadmap

This roadmap separates implemented automation, installation-specific rollout checks, and proposed extensions. It is not a release schedule or a claim that every integration has passed in a live environment. Proposed items have no committed dates or owners.

See [project overview](PROJECT_OVERVIEW.md), [architecture](architecture.md), [pipelines](pipelines.md), and [GitOps](gitops.md) for current behavior. Workflow and action source remains authoritative.

## Implemented baseline

| Area | Present implementation | Boundary |
| --- | --- | --- |
| Reuse | Two `workflow_call` entry points and complete catalog checkout | Consumer supplies events, application, and configuration |
| .NET quality/tests | Locked restore, formatting/style/analyzers, warnings as errors, configured unit/E2E suites and TRX checks | Empty suites are unconfigured; coverage depends on consumer platform/support |
| Source security | Gitleaks, Semgrep, Trivy dependencies, rendered Checkov, hosted CodeQL, pre-build gate | Security entitlement and scanner availability still matter |
| Artifact security | Application/image Trivy and Grype, optional Snyk, central required-job gate | Scanner databases/rules are updateable; reports do not certify compliance |
| Release versioning | Full-history NBGV, preview/stable/RC tracks, strict tag consistency | NBGV installs latest stable; caller owns version manifest/tags |
| Container identity | Single-platform archive/config checks and publication without rebuild | Multi-platform index release is unsupported |
| Supply chain | Trivy/Syft inventories, Cosign signature/CycloneDX attestation, exact verification, GitHub provenance | No SLSA certification or cluster admission policy |
| GitOps | Freshness check, one-entry digest mutation, ordinary Git push, environment boundary | Consumer provisions repository, credentials, reviewers, and Argo Application |
| Deployed checks | Exact revision/image observation, HTTP smoke, optional k6/passive ZAP | Validation defaults off; private endpoint reachability is installation-specific |
| Recovery | Opt-in guarded prior-digest restore, exact recovery sync/smoke, optional Slack failure notice | Does not overwrite newer GitOps work or clear original failure |
| Evidence | Actual per-action outcomes, central gates/scorecard, retained test/security/runtime artifacts | Artifact retention is bounded; registry retention is external |
| Documentation | Overview, architecture, pipelines, GitOps, and this roadmap | Keep contracts synchronized with source changes |

These capabilities are present in repository code. Their presence is not proof of a completed production rollout, successful live OIDC release, or independently verified isolation of a runner installation.

## Priority 1: publish and validate the existing path

Complete these checks before treating a consuming installation as ready for production. Capture run links and artifacts rather than marking items complete from code inspection alone.

| Work | Acceptance evidence |
| --- | --- |
| Publish catalog and pin consumers | Caller workflow reference and `catalog-ref` use the same immutable commit; exact certificate identity confirmed |
| Exercise real releases | Successful preview, RC, and stable push runs; non-release/manual/PR runs produce no published release |
| Validate registry handoff | Remote manifest/config matches scanned candidate; aliases share digest; custom-registry auth tested if used |
| Validate live signing | Cosign signature, CycloneDX attestation, source claims, exact identity, and provenance verified against actual registry artifacts |
| Complete scanner execution | Source/application/image scanners and database retrieval complete on intended runners, including failure evidence |
| Exercise deployment | Exact GitOps commit/digest observed by Argo; health/API checks and every enabled runtime check pass |
| Exercise negative paths | Stale source, wrong signer/source/repository, failed required job, unexpected skip, and GitOps push conflict cannot authorize deployment |
| Exercise guarded recovery | Authorized failed deployment restores verified prior digest; newer HEAD is preserved; failure remains visible after recovery |
| Validate approvals | Required reviewers, prevention of self-review, branch/tag protection, and separate production credentials verified in GitHub |
| Validate runner restrictions | Approved repository/workflow access, required tools, endpoint routing, and exclusion of privileged untrusted PR execution |

Local regression tests and mocks support these checks but cannot replace live certificate, registry, approval, network, or reconciliation evidence. Do not weaken TLS, signer identity, or required-job policy to make an environment pass.

## Priority 2: strengthen maintenance and repeatability

| Proposed work | Reason | Acceptance criterion |
| --- | --- | --- |
| Catalog release/version policy | Consumers need a reviewed upgrade path | Published immutable references, changelog, and contract migration notes |
| Automated contract checks | Inputs, local references, outputs, and gates can drift | CI rejects missing local actions, incompatible forwarding, and unexpected gate changes |
| Tool upgrade review | Mutable actions/latest-stable tools reduce reproducibility | Explicit review/recording of resolved versions while preserving intentionally requested update behavior |
| Container digest pinning | Version tags can be republished | Reviewed digests and a maintainable update process for tool images |
| Runner image qualification | Runner updates can break tools or isolation assumptions | Repeatable tool/network checks against the intended runner image |
| Recovery and verification regression coverage | Security guards must remain fail-closed | Deterministic negative/positive cases covering repository, source, prior-image, and concurrent-writer rules |
| Retention policy | Default artifact lifetime may be too short for incident review | Documented retention/export policy for reports, inventories, signatures, and deployment evidence |

No new policy switch should silently redefine a required gate as optional. Update source, evidence, consumer guidance, and focused regressions together.

## Priority 3: add deployment-path enforcement

These are proposals, not existing catalog features:

- Admission verification of image signatures and attestations, including denial tests for unsigned/wrong-identity images introduced outside CI.
- More explicit GitOps writer boundaries and review policy for changes that bypass automated promotion.
- Production deployment examples with separate overlays, Applications, endpoint/TLS configuration, and least-privilege credentials.
- Broader authenticated/API DAST using authorized identities and documented coverage, while retaining passive baseline semantics separately.
- Scheduled rescanning of already published/deployed digests with deduplicated findings and an agreed response policy.
- License and EOL policy based on actual inventories, reviewed exceptions, and separately reported gate outcomes.

Acceptance should show bypass attempts being denied or detected, not merely a new tool being installed. Admission and GitOps policies belong to the deployment platform and must be integrated without giving delivery jobs cluster administrator access.

## Later extensions

| Proposal | Prerequisite |
| --- | --- |
| Multi-platform image publication | Scan/attest every constituent platform and verify the final index relationship without unscanned rebuilds |
| Multi-source Argo CD observation | Define exact revision/image semantics per source and reject ambiguous state |
| Progressive delivery | Define canary signals, failure thresholds, desired-state ownership, and recovery semantics |
| Deployment telemetry integration | Consumer-owned metrics/logging endpoints, scoped access, and explicit success/failure criteria |
| Additional runtime notification channels | Preserve actual deployment failure and redact secrets; delivery failure must not be hidden by notification success |

Cloud provisioning modules, a full monitoring stack, a docs website, and additional application language templates are not current deliverables. They would need separate scope decisions rather than being implied by the reference platform's feature list.

## Change acceptance rules

1. Preserve the scanned-candidate-to-published-digest relationship.
2. Keep exact registry, signer, issuer, caller, source, and trigger checks; do not replace them with wildcard trust.
3. Distinguish promotion, deployment validation, recovery, skipped work, and disabled integrations in outputs/evidence.
4. Keep GitOps writes auditable and refuse to overwrite newer work.
5. Keep consumer secrets scoped and out of summaries/repository content.
6. Add focused validation for new behavior and record what remains unverified live.
7. Synchronize [README](../README.md) and these guides with contract changes.

## Design reference

The [reference roadmap](https://github.com/abhishekpanda0620/devsecops-platform-template/blob/main/docs/ROADMAP.md) inspired the division into foundation, security, release, GitOps, and operational work. This roadmap uses the actual .NET/ARC/Argo catalog baseline and does not copy the reference's cloud modules, observability stack, dates, or completion claims.
