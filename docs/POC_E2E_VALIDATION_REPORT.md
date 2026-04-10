# POC E2E Validation Report

## Executive Summary

The hardened Jira -> GitHub Actions -> self-hosted runner -> GitOps -> ArgoCD flow remains healthy after the new safety
layer was added.

Validated live on March 27, 2026:

1. Normal rerun / idempotency validation
   - ticket: `SCRUM-6`
   - workflow run: `#15`
   - result: `already_deployed`
   - no duplicate GitOps commit was created

2. Rollback path validation
   - ticket: `SCRUM-6`
   - workflow run: `#16`
   - result: `rollback_skipped`
   - rollback mode safely detected that the last known good version was already live
   - no GitOps rollback commit was required

3. Final regression validation after the last reporting/code polish
   - ticket: `SCRUM-6`
   - workflow run: `#17`
   - result: `already_deployed`
   - final branch head stayed healthy and idempotent

Both runs completed on the active self-hosted runner:

- runner: `leninkart-runner`
- labels:
  - `self-hosted`
  - `Windows`
  - `X64`
  - `leninkart`
  - `local`
  - `dev`

## Ticket Metadata

```text
app: leninkart
component: frontend
env: dev
version: v2
```

## Resolved Target

- Project: `leninkart`
- App: `frontend`
- Environment: `dev`
- Namespace: `dev`
- GitOps repo: `https://github.com/Leninfitfreak/leninkart-infra.git`
- GitOps branch: `main`
- Values file: `applications/frontend/helm/values-dev.yaml`
- ArgoCD application: `frontend-dev`
- Requested version: `v2`
- Resolved deployable version: `23599512080`
- Runtime URL: `http://dev.leninkart.local`

## Live Validation 1: Idempotent Rerun

- Workflow: `.github/workflows/deploy-from-jira.yml`
- Run number: `#15`
- Run URL: `https://github.com/Leninfitfreak/deployment-poc/actions/runs/23612282256`
- Deployment action: `already_deployed`
- Final verdict: `SUCCESS`

Result:

- current GitOps revision already pointed at the requested version
- ArgoCD already had `frontend-dev` at:
  - `Sync = Synced`
  - `Health = Healthy`
  - `Revision = a5530ce5dccff30803b262516d8e66edc0022040`
- the workflow exited cleanly without creating a new `leninkart-infra/main` commit

Tracked workflow-side safety results:

- lock acquire commit in `deployment-poc/main`: `432cf92`
- state update commit in `deployment-poc/main`: `581a6d3`
- lock release commit in `deployment-poc/main`: `a76bdd0`

## Live Validation 2: Rollback Mode

- Workflow: `.github/workflows/deploy-from-jira.yml`
- Run number: `#16`
- Run URL: `https://github.com/Leninfitfreak/deployment-poc/actions/runs/23612368575`
- Deployment action: `rollback_skipped`
- Final verdict: `SUCCESS`

Result:

- rollback mode resolved the last known successful deployment state from `config/deployment_state.yaml`
- the stored last good version was already live
- the workflow performed exact ArgoCD verification and exited safely without changing `leninkart-infra/main`

Tracked workflow-side safety results:

- lock acquire commit in `deployment-poc/main`: `d3c4c59`
- state update commit in `deployment-poc/main`: `f85d704`
- lock release commit in `deployment-poc/main`: `3f88f78`

Note:

- the rollback validation remained GitOps-safe because it did not mutate the cluster directly
- it also remained production-safe because it did not push a needless revert when the known good revision was already active

## Current Deployment State

Git-tracked state now records the last known successful deployment for `leninkart/frontend` in `dev`:

- last version: `23599512080`
- last requested version: `v2`
- last GitOps commit: `a5530ce5dccff30803b262516d8e66edc0022040`
- last ticket: `SCRUM-6`
- last action: `already_deployed`
- last sync status: `Synced`
- last health status: `Healthy`

Git-tracked lock state shows the latest run was released cleanly:

- latest lock run id: `23612528816`
- status: `released`
- note: `already_deployed`

## ArgoCD Verification

Live cluster verification after the hardening runs:

```text
kubectl get application frontend-dev -n argocd -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision} {.status.operationState.phase}'
Synced Healthy a5530ce5dccff30803b262516d8e66edc0022040 Succeeded
```

The GitOps repo head stayed unchanged through both safety validations:

```text
leninkart-infra/main = a5530ce5dccff30803b262516d8e66edc0022040
```

## URL Post-Check

- Direct URL check to `http://dev.leninkart.local`: `WARNING`
  - runner DNS could not resolve `dev.leninkart.local`
- Local fallback check: `PASS`
  - request: `GET http://127.0.0.1/`
  - header: `Host: dev.leninkart.local`
  - status: `200`

This warning does not invalidate the deployment because the application, service, and ingress-backed localhost route
were all reachable from the runner machine.

## Hardening Coverage Confirmed

Validated in the working flow:

1. Deployment state tracking
   - `config/deployment_state.yaml` is updated only after verified success

2. Deployment locking
   - `config/deploy_locks.yaml` is acquired and released by the workflow itself

3. Stronger idempotency
   - same ticket and same live version exit cleanly as `already_deployed`

4. Retry-safe orchestration
   - reruns reuse the live GitOps and ArgoCD state instead of creating duplicate deployment commits

5. Rollback support
   - explicit rollback mode exists
   - rollback mode safely no-ops when the last known good revision is already live

6. Exact ArgoCD revision verification
   - success still requires:
     - `status.sync.status == Synced`
     - `status.health.status == Healthy`
     - `status.sync.revision == expected GitOps SHA`

7. Final branch-head regression check
   - workflow run `#17` executed from commit `67bd0e9`
   - result stayed `already_deployed`
   - no new `leninkart-infra/main` commit was created

## Reusability Status

The POC remains reusable because:

- project and environment details remain config-driven
- deployment state and lock files are generic by project/app/environment key
- rollback behavior is controlled by `config/deployment_policy.yaml`
- secrets remain externalized
- the orchestration logic remains separate from `project-validation`

