# Gitea for local GitOps

Gitea stores Kubernetes desired state for Argo CD. It does not run GitHub workflows and needs neither a Tekton webhook nor a Gitea Actions runner.

## Run Gitea

The existing [docker-compose.yaml](docker-compose.yaml) names the container `gitea` and persists its data in `gitea-data`. From this directory:

```bash
docker compose up -d
```

Open `http://localhost:3000` with your existing local administrator account. Never commit administrator credentials or use its password for CI. HTTP and a weak administrator password are acceptable only in an isolated disposable lab; use TLS and a strong password outside it.

## Seed the repository

Create an empty public repository `admin/simple-api-gitops` with default branch `main`. Public reads avoid an Argo CD repository credential in this sample. Private repositories require a separate read-only Argo CD repository Secret, not the promotion bot's write token.

Clone it into a separate folder outside this sample, copy the contents of [../gitops](../gitops) to its root, then commit and push on `main`. Its root must contain:

```text
base/
  deployment.yaml
  service.yaml
  network-policy.yaml
  kustomization.yaml
environments/
  local/
    ingress.yaml
    kustomization.yaml
```

Use `http://localhost:3000/admin/simple-api-gitops.git` from the host. In Kubernetes, use `http://gitea.gitops-system.svc.cluster.local:3000/admin/simple-api-gitops.git`. Bootstrap attaches Gitea to the dedicated k3d network and creates the internal Service/EndpointSlice. No webhook allow-list change is needed.

## Create a promotion bot

Create a non-administrator user, grant write access only to `admin/simple-api-gitops`, and issue a token with your Gitea version's repository-write scope. Restrict token access to this repository where supported. Store it directly in GitHub as the application's repository secret `GITOPS_TOKEN`; store the bot username as `GITOPS_USERNAME`.

Keep the supplied local administrator account for initial setup only. Protect GitOps writes where possible: CI verification cannot stop privileged users from editing manifests directly.

Continue with [application setup](../../README.md).
