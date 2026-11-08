#!/usr/bin/env bash
set -euo pipefail

directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cluster=github-devsecops
context="k3d-$cluster"
arc_version=0.15.1
argocd_version=v3.6.1
previous_context="$(kubectl config current-context 2>/dev/null || true)"
trap 'if [[ -n "$previous_context" ]]; then kubectl config use-context "$previous_context" >/dev/null; fi' EXIT

for tool in docker k3d kubectl helm; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done

case "${1:-cluster}" in
  cluster)
    docker inspect gitea >/dev/null
    if ! k3d cluster list --no-headers | awk '{print $1}' | grep -qx "$cluster"; then
      k3d cluster create "$cluster" --servers 1 --agents 1 \
        --api-port 127.0.0.1:6550 --port '8081:80@loadbalancer' --wait
    fi
    for namespace in arc-systems arc-runners argocd gitops-system simple-api; do
      kubectl --context "$context" create namespace "$namespace" --dry-run=client -o yaml \
        | kubectl --context "$context" apply -f -
    done
    kubectl --context "$context" label namespace arc-runners pod-security.kubernetes.io/enforce=privileged --overwrite
    kubectl --context "$context" label namespace simple-api pod-security.kubernetes.io/enforce=restricted --overwrite
    network="k3d-$cluster"
    address="$(docker inspect --format "{{with index .NetworkSettings.Networks \"$network\"}}{{.IPAddress}}{{end}}" gitea)"
    if [[ -z "$address" ]]; then
      docker network connect "$network" gitea
      address="$(docker inspect --format "{{with index .NetworkSettings.Networks \"$network\"}}{{.IPAddress}}{{end}}" gitea)"
    fi
    [[ "$address" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
    kubectl --context "$context" apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: gitea
  namespace: gitops-system
spec:
  ports:
    - name: http
      port: 3000
      targetPort: 3000
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: gitea-external
  namespace: gitops-system
  labels:
    kubernetes.io/service-name: gitea
addressType: IPv4
ports:
  - name: http
    protocol: TCP
    port: 3000
endpoints:
  - addresses: ["$address"]
    conditions:
      ready: true
EOF
    helm upgrade --install arc \
      oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller \
      --kube-context "$context" --namespace arc-systems --version "$arc_version" \
      --set serviceAccount.name=arc-controller --wait --timeout 5m
    kubectl --context "$context" apply --server-side -n argocd \
      -f "https://raw.githubusercontent.com/argoproj/argo-cd/$argocd_version/manifests/install.yaml"
    kubectl --context "$context" wait --for=condition=Available deployment --all -n argocd --timeout=15m
    kubectl --context "$context" rollout status statefulset/argocd-application-controller -n argocd --timeout=15m
    echo 'Cluster ready. Create arc-github-auth Secret, then run bootstrap.sh runners.'
    ;;
  runners)
    : "${GITHUB_CONFIG_URL:?Set GITHUB_CONFIG_URL to your GitHub application repository or organization URL.}"
    [[ "$GITHUB_CONFIG_URL" == https://github.com/* ]]
    kubectl --context "$context" get secret arc-github-auth -n arc-runners >/dev/null
    docker build --file "$directory/runner.Dockerfile" --tag devsecops-runner:2.338.2 "$directory"
    k3d image import devsecops-runner:2.338.2 --cluster "$cluster"
    helm upgrade --install arc-devsecops \
      oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
      --kube-context "$context" --namespace arc-runners --version "$arc_version" \
      --values "$directory/arc-values.yaml" --set-string githubConfigUrl="$GITHUB_CONFIG_URL" \
      --wait --timeout 5m
    echo 'Run the ARC runner smoke workflow in GitHub to verify registration and DinD.'
    ;;
  application)
    kubectl --context "$context" apply -f "$directory/../argocd/project.yaml"
    kubectl --context "$context" apply -f "$directory/../argocd/application.yaml"
    echo 'Argo CD now reconciles the GitOps repository. Check sync and health before calling deployment complete.'
    ;;
  *)
    echo 'Usage: bootstrap.sh cluster|runners|application' >&2
    exit 1
    ;;
esac