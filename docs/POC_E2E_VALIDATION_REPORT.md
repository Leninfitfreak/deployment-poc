# POC E2E Validation Report

## Latest Validated Run

- Jira ticket: `SCRUM-6`
- Jira project: `SCRUM`
- Workflow: `.github/workflows/deploy-from-jira.yml`
- Workflow run: `#14`
- Run URL: `https://github.com/Leninfitfreak/deployment-poc/actions/runs/23611829756`
- Runner: `leninkart-runner`
- Runner labels:
  - `self-hosted`
  - `Windows`
  - `X64`
  - `leninkart`
  - `local`
  - `dev`
- Final verdict: `SUCCESS`

## Jira Metadata

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
- GitOps branch: `dev`
- Changed file: `applications/frontend/helm/values-dev.yaml`
- ArgoCD application: `frontend-dev`
- Requested version: `v2`
- Resolved deployable version: `23599512080`
- Resolved URL: `http://dev.leninkart.local`

## GitOps Result

- Deployment action: `reconciled`
- Existing GitOps commit verified in `leninkart-infra/dev`: `a5530ce5dccff30803b262516d8e66edc0022040`
- No duplicate GitOps commit was created on rerun
- Final GitOps image tag remained: `23599512080`

## ArgoCD Result

- Final sync status: `Synced`
- Final health status: `Healthy`
- Final synced revision: `a5530ce5dccff30803b262516d8e66edc0022040`
- Final deployed image: `leninfitfreak/frontend:23599512080`

Live verification:

```text
kubectl get application frontend-dev -n argocd -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision} {.status.operationState.phase}'
Synced Healthy a5530ce5dccff30803b262516d8e66edc0022040 Succeeded
```

```text
kubectl get deploy,pods -n dev -l app=frontend -o wide
deployment.apps/frontend   1/1   1   1   ...   leninfitfreak/frontend:23599512080
pod/frontend-5778479f6d-ht4ck   1/1   Running   ...
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

## Hardening Added

The latest validation includes the following hardening improvements:

1. Exact ArgoCD revision verification
   - success now requires:
     - `status.sync.status == Synced`
     - `status.health.status == Healthy`
     - `status.sync.revision == pushed GitOps commit SHA`

2. Duplicate deployment prevention
   - the orchestrator exits cleanly as `already_deployed` or `reconciled` instead of creating duplicate GitOps commits

3. Config-driven version resolution
   - Jira-friendly versions such as `v1` and `v2` resolve through `config/app_mapping.yaml`

4. Environment restriction
   - current deployment-poc instance allows only `dev` through `config/global.yaml`

5. Safe test mode
   - `TEST_MODE=true` simulates the GitOps and ArgoCD result without pushing

6. Local DNS fallback handling
   - local `.local` hostname failures degrade to `WARNING`, then retry via localhost with the correct host header

7. Git-tracked deployment state and locks
   - `config/deployment_state.yaml` records the last known successful deployment state
   - `config/deploy_locks.yaml` prevents overlapping deployments for the same app/environment

8. Explicit rollback path
   - `python -m src.orchestrator --jira-ticket <ticket> --rollback-to-last-success`
   - rollback reuses the stored last known successful version and exact ArgoCD revision verification

## Additional Validation Evidence

- Ticket creation workflow:
  - `.github/workflows/create-jira-test-ticket.yml`
  - created `SCRUM-6` successfully on the self-hosted runner
- Previous successful baseline:
  - `SCRUM-5`
  - proved the original working Jira -> GitHub Actions -> GitOps -> ArgoCD path

## Reusability Status

The POC remains reusable because:

- runner labels are centralized in workflow config
- project and environment scope are driven by:
  - `config/global.yaml`
  - `config/projects.yaml`
  - `config/app_mapping.yaml`
  - `config/environments.yaml`
  - `config/jira_field_mapping.yaml`
- secrets remain externalized in GitHub repository secrets
- no direct cluster mutation is used for deployments
- the orchestration logic remains separate from `project-validation`
