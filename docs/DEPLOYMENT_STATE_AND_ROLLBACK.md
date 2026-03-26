# Deployment State And Rollback

## State Tracking

The deployment POC now tracks the last known successful deployment per project/app/environment in:

- `config/deployment_state.yaml`

Tracked fields include:

- last deployed version
- last requested version
- last GitOps commit
- last Jira ticket
- last ArgoCD app
- last deployment timestamp
- last sync/health result
- previous known good version and commit

State is updated only after the orchestrator verifies the exact GitOps revision in ArgoCD with:

- `Sync = Synced`
- `Health = Healthy`
- `revision == pushed Git SHA`

## Locking

Logical deployment locks are tracked in:

- `config/deploy_locks.yaml`

Each lock is scoped by:

- project/app
- environment

Each lock stores:

- Jira ticket
- workflow run id
- requested version
- resolved version
- acquisition timestamp
- status

## Stale Lock Recovery

Lock timeout is controlled by:

- `config/deployment_policy.yaml`

Current field:

- `policy.lock_timeout_minutes`

If a lock remains `in_progress` beyond that timeout, the next run may replace it as stale.

If manual recovery is needed:

1. inspect `config/deploy_locks.yaml`
2. confirm the corresponding GitHub Actions run is no longer active
3. clear or release the stale lock through a normal Git commit to `deployment-poc/main`

Do not edit the cluster directly for lock recovery.

## Idempotency Rules

The hardened orchestrator now behaves as follows:

1. If the same app/environment/version is already deployed and ArgoCD is healthy on that exact GitOps revision, the run
   exits cleanly as `already_deployed` or `reconciled`.
2. If the same Jira ticket is rerun after a successful deployment, the run exits cleanly instead of creating another
   GitOps commit.
3. If a deployment for the same app/environment is already in progress, the run fails clearly because the lock cannot be
   acquired.

## Rollback Support

Rollback support is intentionally minimal and safe.

Current building blocks:

- previous known good state is stored in `config/deployment_state.yaml`
- GitOps value path is known for the target app/environment
- rollback can be performed by restoring the previous successful version and pushing a corrective GitOps commit

Supported rollback modes:

1. Manual rollback
   - `python -m src.orchestrator --jira-ticket <TICKET> --rollback-to-last-success`
2. Policy-gated automatic rollback
   - controlled by `policy.auto_rollback_enabled`
   - disabled by default
   - used only if a new GitOps revision is pushed but never reaches `Synced` and `Healthy`

Recommended rollback procedure for the current dev scope:

1. run the explicit rollback mode for the same Jira ticket or an equivalent app/environment-scoped ticket
2. confirm the rollback target from `config/deployment_state.yaml`
3. verify the rollback commit pushed to the GitOps repo
4. verify ArgoCD returns to `Synced` and `Healthy` on the exact rollback revision

This path is practical for the current frontend/dev deployment model because the GitOps value file controls a single
image tag.

## Test Mode

Set `TEST_MODE=true` to simulate:

- target resolution
- lock handling
- state tracking
- reporting

without pushing to the GitOps repo.
