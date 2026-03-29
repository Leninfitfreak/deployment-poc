# Deployment Control Plane

## Purpose

`deployment-poc` is the LeninKart deployment control plane. It turns a structured Jira deployment request into a verified GitOps deployment against `leninkart-infra`, then records and reports the outcome back to Jira.

It exists to keep deployment logic out of service repositories. Service CI publishes build outputs and latest-tag metadata. `deployment-poc` owns deployment decisions, safety checks, GitOps writes, ArgoCD verification, Jira lifecycle feedback, and rollback.

## Main Entry Point

The control-plane workflow entry is:
- `.github/workflows/deploy-from-jira.yml`

It is triggered by `workflow_dispatch` and accepts:
- `jira_ticket`
- `trigger_argocd_sync`
- `test_mode`
- `rollback_to_last_success`
- `argocd_timeout_seconds`

The job runs on the self-hosted Windows runner and calls:

```text
python -m src.orchestrator --jira-ticket <KEY> ...
```

## Core Modules

### `src/orchestrator.py`
- main execution coordinator
- loads configuration
- fetches and parses Jira issue metadata
- validates the target
- resolves version and GitOps location
- acquires deployment lock
- clones and updates GitOps repo when needed
- waits for ArgoCD reconciliation
- runs post-checks
- records deployment state
- posts Jira progress and final feedback
- performs automatic rollback on eligible failures
- writes deployment artifacts and markdown reports

### `src/target_resolver.py`
- maps Jira request metadata to a concrete deployment target
- resolves:
  - app key
  - environment
  - values path
  - ArgoCD application
  - namespace
  - URL
  - cluster context
- resolves version source and exact deployable version

### `src/gitops_repo.py`
- clones `leninkart-infra` with `PAT_TOKEN`
- reads current image tag from a values file
- updates the target image tag
- commits and pushes GitOps changes
- supports no-op commits cleanly by returning the current HEAD when no actual change exists

### `src/jira_feedback.py`
- posts stage-wise Jira progress comments
- applies final Jira comment and transition logic
- supports feedback modes:
  - `success`
  - `failure`
  - `already_deployed`
  - `rollback_skipped`
  - `rolled_back`
  - `rollback_failed`

### `src/state_manager.py`
- tracks deployment state in `config/deployment_state.yaml`
- tracks locks in `config/deploy_locks.yaml`
- performs stale-lock inspection and force-release when policy allows
- stores previous successful version information that rollback depends on

### `src/prechecks.py`
- verifies that the target values file exists
- optionally captures current ArgoCD status before deployment

### `src/postchecks.py`
- performs URL reachability validation after deployment
- tries a localhost + Host-header fallback for `.local` ingress URLs
- can fail the deployment even after control-plane reconciliation if the application endpoint is not healthy enough

### `src/reporting.py`
- writes `artifacts/deployment-result.json`
- writes `artifacts/deployment-result.md`
- includes lock, state, rollback, Jira progress, and Jira feedback sections

## Configuration

### `config/global.yaml`
Important settings:
- allowed environments
- runner labels
- Jira feedback enablement
- Jira progress stages
- Jira transition candidates
- latest-version aliases such as `latest` and `latest-dev`

### `config/deployment_policy.yaml`
Current active policy flags include:
- `lock_timeout_minutes`
- `stale_lock_check_enabled`
- `auto_release_stale_locks`
- `allow_force_unlock`
- `unlock_requires_run_check`
- `auto_rollback_enabled`
- `allow_duplicate_deployments`
- `url_fallback_warning_enabled`
- `manual_rollback_enabled`
- `retry_reconcile_without_redeploy`

### `config/projects.yaml`
Defines project-level GitOps ownership, for example:
- GitOps repo URL
- target branch by environment
- allowed apps
- default app per environment

### `config/app_mapping.yaml`
Defines app-level deployment mapping:
- aliases
- values path by environment
- version aliases
- ArgoCD app name by environment
- namespace by environment
- ingress URL by environment

### `config/latest_tags.yaml`
Shared metadata source for latest-tag resolution. Written by service CI, read by the control plane.

### `config/jira_field_mapping.yaml`
Maps free-form ticket description aliases to the normalized metadata keys the orchestrator expects.

## Internal Flow

### Step 1. Load config
`orchestrator.main()` loads:
- projects
- app mapping
- environments
- latest tags
- Jira field mapping
- global config
- deployment policy

### Step 2. Fetch Jira issue
The orchestrator creates `JiraClient` using:
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`

It fetches the requested issue and creates a `JiraProgressReporter`.

### Step 3. Publish initial progress
The first stage posted is:
- `workflow_triggered`

### Step 4. Parse and validate metadata
The issue description is parsed into structured fields. Validation ensures that required metadata is present and that the target environment is allowed.

### Step 5. Resolve the deployment target
`resolve_target()` determines the concrete deployable target. This step produces:
- `project_key`
- `app_key`
- `environment`
- `requested_version`
- `resolved_version`
- `values_path`
- `argocd_app`
- `namespace`
- `url`
- `version_source`

### Step 6. Build supporting clients and state managers
The orchestrator creates:
- `GithubActionsClient`
- `DeploymentStateManager`
- `ArgoCdClient`

It also loads the previous successful deployment state for the target app/environment.

### Step 7. Acquire deployment lock
`DeploymentStateManager.acquire_lock()`:
- pulls the latest control-plane repo state
- inspects current lock state
- evaluates whether an existing lock is active, stale, auto-recoverable, or manually blocked
- force-releases stale locks when allowed by policy
- records the new lock in `config/deploy_locks.yaml`
- commits and pushes the lock change to `deployment-poc/main`

### Step 8. Clone and inspect GitOps
`GitOpsRepoManager` clones the target GitOps repo and branch. The orchestrator reads:
- current image tag in the target values file
- current Git revision
- current precheck state

### Step 9. Decide deployment action
The control plane compares the current tag with the desired version.

Possible behaviors:
- if the current tag already matches the desired version:
  - verify current ArgoCD state
  - return `already_deployed`, `reconciled`, or `rollback_skipped`
- if the tag differs:
  - update the values file
  - create and push a GitOps commit
  - wait for ArgoCD reconciliation

### Step 10. Wait for ArgoCD
When ArgoCD is configured, the orchestrator:
- optionally triggers a sync
- waits for `Synced` and `Healthy`
- checks the expected revision when a new GitOps commit was pushed

### Step 11. Run post-checks
After control-plane reconciliation, `run_postchecks()` validates the target URL. This catches cases where the GitOps and ArgoCD layers look healthy but the application endpoint is not actually usable.

### Step 12. Mark success and release lock
On success, the orchestrator:
- sets `target['effective_version']`
- records deployment success in `config/deployment_state.yaml`
- releases the lock through `config/deploy_locks.yaml`
- posts `completed`
- applies final Jira success/no-op feedback
- writes deployment artifacts

## Version Resolution

`target_resolver._resolve_version()` uses this real order:

1. **latest-tag aliases**
   - aliases come from `config/global.yaml`
   - `latest` and `latest-dev` currently map through `config/latest_tags.yaml`
2. **app mapping aliases**
   - for example `v1` and `v2`
   - configured per app and environment in `config/app_mapping.yaml`
3. **explicit tag**
   - everything else is used as-is

The resolved target stores not just the final version, but also the source of resolution. That metadata is later surfaced in Jira comments and reports.

## Locking, Idempotency, and Stale Locks

### Lock scope
Locks are scoped by:
- `project_key/app_key`
- `environment`

This prevents overlapping deploys of the same app and environment while allowing unrelated targets to proceed independently.

### Idempotency
The orchestrator avoids needless churn in these cases:
- same version already live and healthy
- same Jira ticket re-run after a successful deployment
- rollback request when the last successful version is already active

### Stale-lock recovery
The state manager uses both time and GitHub Actions run state:
- if a lock exceeds timeout, it checks whether the recorded workflow run is still active
- if the run is not active and policy allows, the lock is force-released
- if confidence is insufficient and policy demands verification, the deployment stops safely instead of unlocking blindly

## Automatic Rollback

### Eligibility
Automatic rollback is attempted only when:
- `auto_rollback_enabled` is true
- the run is not in `test_mode`
- this is not already a manual rollback flow
- a previous stable version exists
- the previous stable version differs from the failed attempted version

### Execution
`attempt_automatic_rollback()`:
1. publishes `rollback_started`
2. updates the same values file back to the previous stable version
3. commits and pushes a rollback GitOps commit
4. forces ArgoCD sync when configured
5. waits for ArgoCD to reconcile the rollback commit
6. publishes `rollback_completed` or `rollback_failed`

### Result semantics
If rollback succeeds:
- workflow return code is still failure-oriented
- deployment action becomes `auto_rolled_back`
- outcome remains `failure`
- state is updated to the restored live version
- Jira receives rollback-aware final feedback

This is deliberate. A failed deployment is not re-labeled as a normal success just because recovery succeeded.

## Jira Lifecycle

### Progress comments
`JiraProgressReporter` builds structured stage comments that may include:
- ticket key
- component
- environment
- requested version
- resolved version
- version source
- ArgoCD application
- GitOps commit
- detail text
- workflow run URL
- timestamp

### Final feedback
`apply_final_jira_feedback()`:
- determines feedback mode from action and outcome
- resolves the best available Jira transition by name
- adds the final summary comment
- records whether policy was satisfied

Transition candidates are configured by mode in `config/global.yaml`.

## Artifacts

Each deployment run produces:
- `artifacts/deployment-result.json`
- `artifacts/deployment-result.md`

These include:
- Jira ticket
- target
- deployment action
- outcome
- GitOps commit
- changed file
- ArgoCD status
- lock result
- state result
- rollback result
- post-check result
- Jira progress summary
- Jira feedback summary

## Summary

The control plane is intentionally opinionated:
- CI publishes images and metadata
- CD resolves intent and writes GitOps
- ArgoCD reconciles GitOps to the cluster
- validation proves the result
- Jira remains the human-facing request and feedback surface
- rollback restores GitOps truth rather than bypassing it

That separation is the core reason the LeninKart platform remains explainable, reproducible, and safe to debug.
