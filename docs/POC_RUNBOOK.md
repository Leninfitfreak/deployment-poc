# POC Runbook

## Input

- Jira ticket key only

Important:

- manual Jira ticket creation alone does not trigger deployment automatically
- the current production-poc entrypoint is still manual GitHub Actions dispatch:
  - `.github/workflows/deploy-from-jira.yml`
- a Jira ticket must be passed into that workflow as the `jira_ticket` input before any deployment progress can appear back on the issue

Example:

```text
SCRUM-5
```

For repeated validation of the hardened flow, a second ticket can be created through the self-hosted GitHub Actions
workflow:

- `.github/workflows/create-jira-test-ticket.yml`

## Expected Jira Description Format

```text
app: leninkart
component: product-service
env: dev
version: 23599211809
url: http://dev.leninkart.local/api/products
```

`component` is optional in the parser, but it is recommended for LeninKart because the live platform deploys per service.

`version` can be either:

- a literal deployable image tag
- a Jira-friendly release alias that is resolved through `config/app_mapping.yaml`

Currently validated LeninKart dev aliases:

- `frontend`
  - `v1 -> 23599212196`
  - `v2 -> 23599512080`
- `product-service`
  - `v1 -> 23599211809`
  - `v2 -> 23599512382`
- `order-service`
  - `v1 -> 23599211965`
  - `v2 -> 23599512459`

## Required GitHub Secrets

- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `INFRA_PAT`
- `ARGOCD_SERVER` optional if ArgoCD verification is enabled
- `ARGOCD_AUTH_TOKEN` optional if ArgoCD verification is enabled

## Config Files

- `config/global.yaml`
- `config/projects.yaml`
- `config/app_mapping.yaml`
- `config/environments.yaml`
- `config/jira_field_mapping.yaml`
- `config/deployment_policy.yaml`
- `config/deployment_state.yaml`
- `config/deploy_locks.yaml`

These files are the only supported place for project, environment, runner, repo, and version alias changes.

## Jira Status And Comment Automation

After the final deployment result is known, the orchestrator performs a best-effort Jira feedback step.

Configured in:

- `config/global.yaml`

Current policy shape:

- `jira_feedback.progress_comments.enabled`
- `jira_feedback.progress_comments.stages`
- `jira_feedback.transition_name_candidates.success`
- `jira_feedback.transition_name_candidates.failure`
- `jira_feedback.transition_name_candidates.already_deployed`
- `jira_feedback.transition_name_candidates.rollback_skipped`
- `jira_feedback.comment_on.success`
- `jira_feedback.comment_on.failure`
- `jira_feedback.comment_on.noop`

Important behavior:

1. the system posts concise progress comments at major stage boundaries while the workflow is still running
2. the system discovers live available transitions for the Jira issue before attempting a final status change
3. transitions are matched by configured names or target status names, never by hardcoded transition ids
4. if the ticket is already in the desired target status, transition is skipped cleanly
5. if no configured transition is available from the current state, the system still attempts the Jira comment and records a warning
6. if deployment succeeded but Jira feedback failed, the deployment remains successful and the Jira feedback issue is reported separately

Comment content includes:

- stage progress markers such as `workflow_triggered`, `target_resolved`, `gitops_commit_pushed`, and `argocd_synced_healthy`
- deployment result
- Jira ticket
- component
- environment
- requested version
- resolved version
- GitOps commit
- ArgoCD app
- final Sync and Health status
- workflow run URL
- timestamp

## Locking And State

The hardened orchestrator writes:

- successful deployment state to `config/deployment_state.yaml`
- logical deployment locks to `config/deploy_locks.yaml`

Those files are Git-tracked and updated by the workflow itself.

If a deployment is already in progress for the same app/environment, the next run fails clearly instead of racing.

If a run is repeated after success, the orchestrator uses the saved state plus live ArgoCD verification to skip or
reconcile safely.

This rerun-safe behavior is now proven for:

- `frontend` via `SCRUM-8`
- `product-service` via rerun of `SCRUM-9`
- `order-service` via rerun of `SCRUM-11`

## Self-Hosted Runner Expectations

The production-style LeninKart POC is designed to run on the existing local self-hosted runner:

- name: `leninkart-runner`
- labels:
  - `self-hosted`
  - `Windows`
  - `X64`
  - `leninkart`
  - `local`
  - `dev`

Because ArgoCD runs inside the local k3d cluster, the workflow must run on this self-hosted runner instead of a
GitHub-hosted runner.

## ArgoCD Automation Setup

The `github-actions` ArgoCD automation account is created through GitOps in `leninkart-infra`, not through a manual cluster edit.

Git-managed source:

- `argocd/applications/dev/argocd-config.yaml`
- `platform/argocd-config/argocd-cm.yaml`

The ConfigMap adds:

```yaml
data:
  accounts.github-actions: apiKey, login
```

ArgoCD picks up that repo change through the existing app-of-apps model and reconciles the live `argocd-cm` in namespace `argocd`.

Token generation flow:

1. Port-forward ArgoCD locally:
   `kubectl port-forward -n argocd svc/argocd-server 8085:443`
2. Confirm the account is present in the live ConfigMap:
   `kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.accounts\.github-actions}'`
3. Log in with an ArgoCD admin-capable account:
   `argocd login 127.0.0.1:8085 --insecure --username <admin-user> --password <admin-password>`
4. Confirm the account is visible to the API:
   `argocd account list`
5. Generate an API token for the automation account:
   `argocd account generate-token --account github-actions`
6. Store the generated token in the `deployment-poc` GitHub repository secret:
   `ARGOCD_AUTH_TOKEN`

Related workflow secrets:

- `ARGOCD_SERVER`
- `ARGOCD_AUTH_TOKEN`
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`

The token must never be committed to Git or embedded in repo config.

## Local CLI

```powershell
python -m src.orchestrator --jira-ticket SCRUM-5
```

Safe simulation:

```powershell
$env:TEST_MODE="true"
python -m src.orchestrator --jira-ticket SCRUM-5
```

## Rollback

Rollback support is intentionally conservative and now has an explicit CLI path.

Manual rollback:

```powershell
python -m src.orchestrator --jira-ticket SCRUM-6 --rollback-to-last-success
```

The orchestrator will:

1. parse the Jira ticket normally
2. resolve the target app/environment normally
3. load the last known successful deployment state from `config/deployment_state.yaml`
4. push a corrective GitOps commit back to that stored version
5. verify ArgoCD reaches `Synced` and `Healthy` on the exact rollback revision

Automatic rollback is available only when enabled in `config/deployment_policy.yaml`.

Reference:

- `docs/DEPLOYMENT_STATE_AND_ROLLBACK.md`
- `docs/STALE_LOCK_RECOVERY.md`
- `docs/JIRA_STATUS_AND_COMMENT_AUTOMATION.md`

## Local Smoke Check Note

If the Jira or config URL uses a local hostname such as `dev.leninkart.local`, direct DNS resolution may depend on the
machine hosts-file setup. The LeninKart ingress is still reachable locally through `127.0.0.1` with the original host
header when a runner-side smoke check is needed.

## Manual Unlock Workflow

If a deployment dies before releasing its lock, use the dedicated workflow:

- `.github/workflows/unlock-deployment-lock.yml`

Inputs:

- `component`
- `env`
- `confirm_unlock`
- `reason`

Recommended operator flow:

1. run the workflow once with `confirm_unlock=false`
2. inspect the printed lock details, run id, run URL, age, and stale classification
3. rerun with `confirm_unlock=true` only if the lock is clearly dead

The workflow writes:

- `artifacts/unlock-result.json`
- `artifacts/unlock-result.md`

Reference:

- [STALE_LOCK_RECOVERY.md](/D:/Projects/Services/deployment-poc/docs/STALE_LOCK_RECOVERY.md)

## Multi-Service Validation Reference

Live multi-service validation evidence is recorded in:

- [POC_MULTI_SERVICE_VALIDATION_REPORT.md](/D:/Projects/Services/deployment-poc/docs/POC_MULTI_SERVICE_VALIDATION_REPORT.md)
