# Stale Lock Recovery

## Why Stale Locks Happen

The deployment lock is acquired before the GitOps update starts. If the workflow dies before the normal release step,
the lock can remain behind even though no deployment is still running.

Typical causes:

- self-hosted runner crash
- laptop shutdown
- workflow cancellation
- job failure before lock release
- network interruption during the workflow

## Current Gap That Was Closed

Before this hardening pass, the lock model only stored basic metadata and a timeout heuristic. That meant an
`in_progress` lock could block future deployments until an operator inspected the YAML manually.

The stale-lock layer now adds:

- richer lock metadata
- GitHub Actions run-state inspection
- safe stale-lock auto recovery
- a dedicated manual unlock workflow

## Lock Metadata

Each lock now records enough information to reason about liveness safely:

- app / component
- environment
- Jira ticket
- GitHub Actions run id
- GitHub Actions run URL
- GitHub actor
- runner name
- repository
- workflow name
- requested version
- resolved version
- acquired timestamp
- last-updated timestamp
- lock status

## Policy Controls

Configured in [deployment_policy.yaml](/D:/Projects/Services/deployment-poc/config/deployment_policy.yaml):

- `lock_timeout_minutes`
- `stale_lock_check_enabled`
- `auto_release_stale_locks`
- `allow_force_unlock`
- `unlock_requires_run_check`

## Auto Detection Logic

Before a new deployment acquires a lock, the orchestrator now inspects the existing lock and classifies it.

### Active Lock

The lock stays active when:

- status is `in_progress`
- and the associated GitHub Actions run is still `queued` or `in_progress`

Result:

- deployment is blocked
- no unlock happens

### Stale Auto-Recoverable Lock

The lock is auto-recoverable when:

- status is `in_progress`
- lock age exceeds `lock_timeout_minutes`
- the associated GitHub Actions run is no longer active
- policy allows automatic stale-lock recovery

Result:

1. the old lock is force-released through a Git commit
2. a fresh lock is acquired
3. the new deployment continues normally

### Manual Unlock Required

The lock is treated as manual-recovery-only when:

- it has exceeded the timeout
- but run-state confidence is insufficient
- and policy requires run verification

Result:

- deployment stops clearly
- operator is directed to the manual unlock workflow

## Manual Unlock Workflow

Workflow:

- [.github/workflows/unlock-deployment-lock.yml](/D:/Projects/Services/deployment-poc/.github/workflows/unlock-deployment-lock.yml)

Inputs:

- `component`
- `env`
- `confirm_unlock`
- `reason`

Safe usage:

1. run with `confirm_unlock=false`
2. review the printed lock details, run metadata, age, and stale classification
3. rerun with `confirm_unlock=true` only when the lock is clearly dead

The workflow produces:

- `artifacts/unlock-result.json`
- `artifacts/unlock-result.md`

## Validated Scenarios

### 1. Normal Successful Rerun

- Jira ticket: `SCRUM-8`
- Workflow run: [#26](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23657278217)
- Result:
  - lock acquired
  - deployment returned `already_deployed`
  - lock released normally

### 2. Simulated Interrupted Deployment With Auto Recovery

Simulation:

- committed a fake stale `frontend` lock in `config/deploy_locks.yaml`
- stale lock seed commit: `23e2e84`

Recovery proof:

- deployment run: [#29](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23657579004)
- stale classification: `stale_auto_recoverable`
- dead workflow run detected: `23655093827` with `status=completed`
- auto force-release commit: `00965a2d1a98a9ae1706cdea628a9f3320f62bcb`
- fresh acquire commit: `e27ff980380cded9444579769e7c6cbfd1115e2e`
- normal release commit: `66250e1922b79f26d699c440f2af0fbf734fdef7`
- final deployment result: `already_deployed`

### 3. Manual Unlock Workflow

Simulation:

- committed a fake stale `product-service` lock
- stale lock seed commit: `bdf90f0`

Manual inspection:

- unlock workflow run: [#1](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23657387831)
- `confirm_unlock=false`
- lock details printed successfully

Manual force release:

- unlock workflow run: [#2](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23657425075)
- `confirm_unlock=true`
- force-release commit: `feeb3ddf428c93c607331766d3b58510d666ec5d`

Post-unlock confirmation:

- deployment run: [#28](https://github.com/Leninfitfreak/deployment-poc/actions/runs/23657461629)
- product-service proceeded successfully after manual unlock

## Operational Guidance

- let normal deployments acquire and release locks automatically
- rely on auto recovery only for clearly dead stale locks
- use the manual unlock workflow when confidence is lower or when an operator wants an explicit audit trail
- never bypass the lock system with ad hoc cluster mutation

## Final Result

The deployment-poc can now recover safely from dead deployment locks without permanently blocking future deployments,
while still refusing to unlock active runs recklessly.
