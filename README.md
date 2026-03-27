# Deployment POC

Reusable Jira-driven deployment automation proof of concept for GitOps-managed platforms.

## What This Repo Is

`deployment-poc` is a separate orchestration repository.

It is not:

- `project-validation`
- an application source repo
- the GitOps source of truth

It demonstrates:

Jira Ticket -> GitHub Actions -> metadata parsing -> target resolution -> GitOps update -> ArgoCD reconciliation -> result reporting

Important trigger note:

- creating a Jira ticket by itself does not start a deployment
- the current system starts only when `.github/workflows/deploy-from-jira.yml` is dispatched with a Jira ticket key
- there is currently no Jira webhook, Jira automation callback, scheduled poller, or background listener that auto-dispatches GitHub Actions on issue creation

It now also closes the feedback loop back into Jira by:

- discovering available Jira transitions at runtime
- posting concise progress comments at major deployment stages
- transitioning the deployment ticket by configured transition name candidates
- adding a deployment result comment for success, failure, and no-op outcomes

## LeninKart Alignment

This POC is aligned to the real LeninKart setup discovered from the workspace:

- GitOps repo: `leninkart-infra`
- active GitOps branch for dev: `dev`
- active namespace: `dev`
- root ArgoCD app: `leninkart-root`
- deployable targets:
  - `frontend`
  - `product-service`
  - `order-service`

Validated live multi-service deployment support is documented in
[docs/POC_MULTI_SERVICE_VALIDATION_REPORT.md](/D:/Projects/Services/deployment-poc/docs/POC_MULTI_SERVICE_VALIDATION_REPORT.md).

## How It Works

1. GitHub Actions accepts a Jira ticket number
2. Jira API fetches the issue
3. description metadata is parsed into structured deployment fields
4. validation rejects incomplete or unsupported requests
5. config-driven resolution maps the request to repo/path/app/namespace
6. the orchestrator updates the target GitOps values file
7. the change is committed and pushed
8. ArgoCD can be polled for `Synced` and `Healthy` if credentials are configured

If a Jira ticket omits `url`, the orchestrator falls back to the config-mapped environment URL for the resolved app.

If a Jira ticket uses a release alias instead of a literal image tag, the orchestrator can resolve that alias through
`config/app_mapping.yaml` for the target app and environment.

For LeninKart dev, the currently validated Jira-friendly aliases are:

- `frontend`
  - `v1 -> 23599212196`
  - `v2 -> 23599512080`
- `product-service`
  - `v1 -> 23599211809`
  - `v2 -> 23599512382`
- `order-service`
  - `v1 -> 23599211965`
  - `v2 -> 23599512459`

## Reusability

To adapt this POC to another project, update only:

- `config/global.yaml`
- `config/projects.yaml`
- `config/app_mapping.yaml`
- `config/environments.yaml`
- `config/jira_field_mapping.yaml`
- `config/deployment_policy.yaml`

The Jira feedback behavior is also config-driven through `config/global.yaml`, including:

- which progress stages post Jira comments
- success transition candidates
- failure transition candidates
- no-op transition candidates
- whether comments are posted for success, failure, and no-op outcomes

## Deployment Safety Layer

The POC now includes a minimal production-style safety layer:

- Git-tracked deployment state in `config/deployment_state.yaml`
- Git-tracked deployment locks in `config/deploy_locks.yaml`
- duplicate deployment prevention
- retry-safe reconciliation handling
- rollback-ready state history
- stale-lock detection based on lock age plus GitHub Actions run status
- safe auto-recovery for dead locks when policy allows it
- explicit manual unlock workflow: `.github/workflows/unlock-deployment-lock.yml`
- explicit rollback mode via `--rollback-to-last-success`
- policy-driven safety toggles in `config/deployment_policy.yaml`

## Safe Test Mode

Set `TEST_MODE=true` or pass `--test-mode` to simulate the deployment flow without pushing to the GitOps repo.

In test mode the orchestrator:

- parses and validates the Jira ticket
- resolves the deployment target
- updates the GitOps file only in the temporary clone
- skips the real push
- returns a simulated successful ArgoCD status for reporting

## Rollback Mode

For a safe manual rollback to the last known successful deployment state for the resolved app and environment:

```powershell
python -m src.orchestrator --jira-ticket SCRUM-6 --rollback-to-last-success
```

This mode:

- reads `config/deployment_state.yaml`
- resolves the last known successful version for the app and environment
- updates the GitOps values file back to that version
- waits for ArgoCD to report `Synced` and `Healthy` on the exact rollback commit

Automatic rollback remains policy-gated and disabled by default in `config/deployment_policy.yaml`.

## Runtime Note

The intended cluster context is `k3d-leninkart-dev`, but live cluster access was unavailable during this implementation session because the local k3d / Docker runtime was not active. Repo-backed GitOps discovery was therefore treated as authoritative for the initial POC design.

## Jira Feedback Automation

After the final deployment result is known, the orchestrator now performs a best-effort Jira feedback pass.

Behavior:

- progress comments are posted at meaningful deployment stages such as workflow start, target resolution, lock acquisition, GitOps push, ArgoCD verification, and completion
- `deployed`, `reconciled`, `rolled_back`, and other successful outcomes
  - try a configured success transition
  - add a success comment
- `already_deployed` and `rollback_skipped`
  - try the configured no-op transition policy
  - add a clear explanatory comment
- `failed`
  - try the configured failure transition policy
  - add a failure comment when the ticket was fetched successfully

Safety rules:

- progress comments are concise and stage-based to avoid noisy per-step spam
- transition ids are never hardcoded
- Jira transitions are resolved dynamically from the issue's live available transitions
- if no matching transition is available, the deployment result is still preserved and the workflow records a Jira warning
- if deployment succeeds but Jira feedback fails, the deployment remains successful and the Jira warning is reported separately

Reference:

- `docs/JIRA_STATUS_AND_COMMENT_AUTOMATION.md`
