# Platform Discovery Summary

## Executive Summary

This discovery pass was completed before any POC implementation work.

The LeninKart deployment model is already strongly GitOps-oriented:

- `leninkart-infra` is the actual GitOps source of truth
- ArgoCD root application points at `leninkart-infra` `dev` branch
- the active development environment is represented by ArgoCD application manifests under `argocd/applications/dev`
- application deployment state is controlled primarily by Helm `values-dev.yaml` files in `leninkart-infra`

The new `deployment-poc` repository should therefore orchestrate deployment by:

1. resolving a Jira ticket to a target application and environment
2. mapping that target to the correct GitOps repo/path/app/namespace
3. updating the correct values file in `leninkart-infra`
4. committing and pushing to the correct branch
5. optionally nudging or verifying ArgoCD sync status

The POC must stay separate from `project-validation`, which remains the documentation/evidence system.

## Repositories and Roles

### `deployment-poc`

- status: cloned locally from `https://github.com/Leninfitfreak/deployment-poc.git`
- branch: `main`
- current state: empty repository
- intended role: the only repository that owns this Jira → GitHub Actions → GitOps → ArgoCD deployment POC

### `leninkart-infra`

- remote: `https://github.com/Leninfitfreak/leninkart-infra.git`
- active branch: `dev`
- actual role: GitOps source of truth for app deployment manifests, platform components, and observability manifests
- key importance: this is the repo the POC must understand most carefully

### `leninkart-frontend`

- remote: `https://github.com/Leninfitfreak/leninkart-frontend.git`
- active branch: `dev`
- role: application source repo
- current deployment behavior: existing GitHub Actions build/push image and update `leninkart-infra`

### `leninkart-product-service`

- remote: `https://github.com/Leninfitfreak/leninkart-product-service.git`
- active branch: `dev`
- role: application source repo
- current deployment behavior: existing GitHub Actions build/push image and update `leninkart-infra`

### `leninkart-order-service`

- remote: `https://github.com/Leninfitfreak/leninkart-order-service.git`
- active branch: `dev`
- role: application source repo
- current deployment behavior: existing GitHub Actions build/push image and update `leninkart-infra`

### `project-validation`

- remote: `https://github.com/Leninfitfreak/project-validation.git`
- active branch: `main`
- role: validation, screenshots, docs, MkDocs proof
- discovery conclusion: keep read-only for this POC except future documentation references

### `kafka-platform`

- remote: separate repo on `main`
- role: external messaging runtime
- discovery conclusion: read-only for this POC unless later deployment scope explicitly includes it

### `observability-stack`

- present locally as a read-only reference repo/folder
- discovery conclusion: not a deployment control plane for the active stack and should remain untouched for this POC

## Branch Model

Confirmed current branch roles:

- `leninkart-frontend` → `dev`
- `leninkart-product-service` → `dev`
- `leninkart-order-service` → `dev`
- `leninkart-infra` → `dev`
- `project-validation` → `main`
- `kafka-platform` → `main`
- `deployment-poc` → `main`

Discovery conclusion:

- development deployment automation must respect the `dev` branch in `leninkart-infra`
- the POC repo itself can remain on `main`

## Current GitOps / ArgoCD Model

### Root App

`leninkart-infra/argocd/leninkart-root.yaml` defines the root GitOps entrypoint:

- ArgoCD app name: `leninkart-root`
- repo URL: `https://github.com/Leninfitfreak/leninkart-infra.git`
- target revision: `dev`
- path: `argocd/applications/dev`
- sync policy:
  - automated
  - prune enabled
  - self-heal enabled

Discovery conclusion:

- for the active dev environment, ArgoCD already watches the `dev` branch of `leninkart-infra`
- this strongly favors a GitOps-first deployment method over ad hoc direct deployment

### Dev Applications

Important ArgoCD application manifests discovered in `leninkart-infra/argocd/applications/dev`:

- `frontend.yaml` → ArgoCD app `frontend-dev`
- `product-service.yaml` → ArgoCD app `dev-product-service`
- `order-service.yaml` → ArgoCD app `dev-order-service`
- `dev-ingress.yaml` → ArgoCD app `dev-ingress`
- observability apps:
  - `grafana-dev`
  - `prometheus-dev`
  - `loki-dev`
  - `promtail-dev`
  - `tempo-dev`
- platform apps:
  - `vault`
  - `vault-secretstore`
  - `vault-externalsecrets`
  - `postgres`
  - `external-secrets-operator`

For the application deployment POC, the primary safe target apps are:

- `frontend-dev`
- `dev-product-service`
- `dev-order-service`

## Dev Environment and Namespace Usage

### Namespace

`leninkart-infra/platform/namespaces/dev.yaml` confirms:

- namespace name: `dev`

All key discovered ArgoCD app destinations for the application tier point to:

- destination namespace: `dev`

### Ingress / Entry Path

`leninkart-infra/platform/ingress/dev/ingress.yaml` confirms:

- `/` → `leninkart-frontend`
- `/auth` → `leninkart-product-service`
- `/api/products` → `leninkart-product-service`
- `/api/orders` → `leninkart-order-service`

Discovery conclusion:

- the POC must resolve `env: dev` to namespace `dev`
- any optional post-check URL validation for the current app tier should align with this dev ingress model

## Current Deployment State Control

The current deployment levers for the app tier are the Helm values files in `leninkart-infra`:

- frontend:
  - path: `applications/frontend/helm/values-dev.yaml`
  - ArgoCD app: `frontend-dev`
- product-service:
  - path: `applications/product-service/helm/values-dev.yaml`
  - ArgoCD app: `dev-product-service`
- order-service:
  - path: `applications/order-service/helm/values-dev.yaml`
  - ArgoCD app: `dev-order-service`

Discovered current state:

- these files contain image repository/tag values
- the image tags currently match GitHub Actions run IDs

Examples found:

- frontend tag in `values-dev.yaml`: `23599212196`
- product-service tag in `values-dev.yaml`: `23599211809`
- order-service tag in `values-dev.yaml`: `23599211965`

Discovery conclusion:

- the safest real deployment strategy is to update image tag state inside `leninkart-infra`
- this matches the existing platform behavior already used by the application repos’ CI/CD workflows

## Existing Application Repo Deployment Pattern

The app source repositories already implement a similar pattern:

- build and push image
- checkout `leninkart-infra`
- update the relevant `values-<env>.yaml`
- commit and push to the matching infra branch

This was confirmed in:

- `leninkart-frontend/.github/workflows/ci-cd.yaml`
- `leninkart-product-service/.github/workflows/ci-cd.yml`
- `leninkart-order-service/.github/workflows/ci-cd.yaml`

Discovery conclusion:

- the deployment POC should align with this model, not fight it
- for a Jira-driven deployment POC, the orchestrator can update the same GitOps files directly in `leninkart-infra`
- direct ArgoCD sync should be secondary, mostly for status verification or explicit reconcile requests

## k3d / Cluster / ArgoCD Runtime Discovery

### Confirmed Context

`kubectl config current-context` returned:

- `k3d-leninkart-dev`

This confirms the intended active cluster naming.

### Runtime Constraint Found

Live `kubectl` and `k3d` discovery were partially blocked during this session because:

- Kubernetes API endpoint `127.0.0.1:6550` was unreachable
- Docker / k3d runtime was not currently available from this workstation

Implications:

- repo-backed discovery is authoritative for design
- live ArgoCD/Kubernetes checks must be treated as runtime preconditions for actual execution
- the POC should support meaningful failure messaging when local cluster or ArgoCD access is unavailable

This is not a reason to abandon ArgoCD integration. It only means the client layer should be implemented with clean runtime failure handling.

## Safe Integration Points

These are the safe points for the POC to integrate with the real setup:

1. Jira issue fetch using existing GitHub secrets:
   - `JIRA_BASE_URL`
   - `JIRA_EMAIL`
   - `JIRA_API_TOKEN`
2. Config-driven mapping from Jira metadata to:
   - app
   - environment
   - GitOps repo
   - values file path
   - ArgoCD app
   - namespace
3. GitOps update in `leninkart-infra` on the `dev` branch
4. Optional ArgoCD verification / sync using an ArgoCD client layer
5. Optional post-check URL reachability for the resolved dev endpoint

## Non-Goals / Must-Not-Change Areas

The POC should not:

- use `project-validation` as a deployment engine
- modify unrelated application business logic
- redesign the current GitOps branch model
- directly mutate cluster resources as the primary deployment method
- touch `kafka-platform` unless later scope explicitly requires it
- touch `observability-stack` unless later scope explicitly requires it
- rely on hardcoded LeninKart-only values scattered through code

## Recommended Initial POC Scope

For the first working version, keep the deployment target set intentionally small:

- `frontend`
- `product-service`
- `order-service`

Environment scope:

- `dev` only

Target resolution should be driven by config files that map:

- Jira `app`
- Jira `env`
- GitOps repo
- file path
- ArgoCD app
- namespace

## Discovery-Driven Deployment Recommendation

Preferred deployment method for this POC:

1. workflow input receives Jira ticket key only
2. Jira API fetches issue and metadata
3. resolver maps issue metadata to:
   - target repo: `leninkart-infra`
   - target branch: `dev`
   - values file path
   - ArgoCD app name
   - namespace `dev`
4. orchestrator updates the correct `values-dev.yaml`
5. orchestrator commits and pushes to `leninkart-infra` `dev`
6. ArgoCD auto-reconciles from GitOps
7. ArgoCD client verifies `Synced` and `Healthy`

This is the cleanest match to the actual LeninKart architecture.

## What Must Happen Before Implementation

Before coding the orchestrator logic, the `deployment-poc` repo should be bootstrapped with:

- modular Python structure
- config-driven mappings
- docs
- GitHub Actions `workflow_dispatch` entrypoint

But the design must preserve the discovery conclusions above.
