# Jira Status And Comment Automation

## Purpose

The deployment POC now writes deployment results back into Jira after the final deployment outcome is known.

This feedback layer is intentionally:

- config-driven
- transition-name based
- best-effort
- separate from the deployment decision itself

The deployment result is still determined by Jira parsing, GitOps update, and ArgoCD verification. Jira write-back is a
feedback step that runs afterward.

## Configuration

Jira feedback policy is defined in:

- `config/global.yaml`

Current keys:

- `jira_feedback.enabled`
- `jira_feedback.progress_comments.enabled`
- `jira_feedback.progress_comments.stages`
- `jira_feedback.transition_name_candidates.success`
- `jira_feedback.transition_name_candidates.failure`
- `jira_feedback.transition_name_candidates.already_deployed`
- `jira_feedback.transition_name_candidates.rollback_skipped`
- `jira_feedback.comment_on.success`
- `jira_feedback.comment_on.failure`
- `jira_feedback.comment_on.noop`
- `jira_feedback.require_transition_success`

These values are reusable and can be changed for another Jira workflow without changing the deployment logic.

## Progress Comments

The deployment POC now posts stage-wise progress comments while the workflow is still running.

Current configured stages:

- `workflow_triggered`
- `jira_validated`
- `target_resolved`
- `lock_acquired`
- `gitops_commit_pushed`
- `argocd_sync_started`
- `argocd_synced_healthy`
- `post_checks_completed`
- `completed`
- `failed`

These progress comments are intentionally short. They tell Jira users where the deployment is in the lifecycle without
duplicating the full final summary on every step.

Typical progress comment fields:

- stage name
- Jira ticket
- component
- environment
- requested or resolved version when known
- GitOps commit when available
- ArgoCD application when available
- workflow run URL
- short detail line

No-op flows such as `already_deployed` still post meaningful progress, but the GitOps stage explains that no new commit
was required and the workflow is verifying the current revision instead.

## How Transition Lookup Works

The orchestrator does not hardcode Jira transition ids.

Instead it:

1. fetches the issue
2. fetches the currently available transitions for that issue
3. compares the configured candidate names against:
   - transition name
   - target status name
4. uses the first matching transition

If the issue is already in a configured target status, the transition is skipped as already satisfied.

If no configured transition is available from the current state:

- the deployment result is preserved
- the Jira comment is still attempted
- a warning is written into the deployment report

## Outcome Policy

Current deployment outcomes are mapped as follows:

- `deployed`
- `reconciled`
- `rolled_back`
- `test_mode`
- `rollback_test_mode`
  - treated as success-style outcomes

- `already_deployed`
- `rollback_skipped`
  - treated as no-op outcomes

- `failed`
  - treated as failure-style outcomes

## Comment Format

Each Jira comment includes operator-friendly deployment context.

Progress comments:

- are stage markers while the workflow is still running
- are concise
- help operators follow the deployment lifecycle in near real time

Success comment fields:

- deployment result
- Jira ticket
- component
- environment
- requested version
- resolved deployable version
- GitOps commit SHA
- GitOps file
- ArgoCD application
- final Sync status
- final Health status
- observed revision
- workflow run URL
- timestamp

Failure comments include:

- deployment result
- Jira ticket
- component if known
- environment if known
- requested version if known
- deployment action
- workflow run URL if available
- error summary
- timestamp

No-op outcomes such as `already_deployed` and `rollback_skipped` add an explicit explanation so the operator can see
that the workflow was valid but no new deploy was needed.

## Failure Handling

Jira feedback failures are reported honestly.

Examples:

- deployment succeeded but Jira transition failed
- deployment succeeded but Jira comment failed
- deployment failed and the Jira issue could not be updated
- no valid transition exists from the current Jira status

Reporting fields now include:

- `jira_comment_added`
- `jira_transition_attempted`
- `jira_transition_result`
- `jira_transition_name_used`
- `jira_feedback_error`
- `available_transitions`
- `current_status`
- `final_status`

If deployment succeeded but Jira feedback failed, the deployment remains successful and the Jira feedback error is
reported separately.

## Adapting To Another Jira Workflow

To reuse this automation in another project:

1. keep Jira credentials in GitHub secrets
2. update the transition candidate names in `config/global.yaml`
3. test against one real ticket to confirm the target workflow states
4. keep transition ids dynamic

No code change should be needed when only the Jira workflow names differ.

## LeninKart Validation Notes

The current LeninKart Jira workflow was validated against real `SCRUM` tickets.

Observed live transitions from freshly created deployment tickets in `To Do`:

- `To Do`
- `In Progress`
- `In Review`
- `Done`

Chosen current policy:

- success-like outcomes prefer `Done`
- failure-like outcomes prefer `Failed`, `Blocked`, then fall back to `In Progress`
- no-op outcomes such as `already_deployed` and `rollback_skipped` prefer `Done`

Validated scenarios:

- live no-op deployment: `SCRUM-15`
  - workflow run: `23658796684`
  - progress comments were posted through the no-op path
  - Jira transitioned from `To Do` to `Done`
  - Jira comment posted successfully
- live successful deployment: `SCRUM-16`
  - workflow run: `23658905290`
  - progress comments were posted through GitOps push and ArgoCD verification
  - Jira transitioned from `To Do` to `Done`
  - Jira comment posted successfully
- live failure deployment: `SCRUM-18`
  - workflow run: `23659364568`
  - deployment failed during target resolution
  - progress stopped at failure and the `failed` stage comment was posted
  - Jira transitioned from `To Do` to `In Progress`
  - Jira failure comment posted successfully
- simulated transition-unavailable path
  - intentionally tested with unmatched candidate names against a fake Jira transition set
  - comment still succeeded
  - transition result was reported as `skipped_unavailable`
