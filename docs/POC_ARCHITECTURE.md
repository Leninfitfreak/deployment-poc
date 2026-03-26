# POC Architecture

## Purpose

`deployment-poc` provides a separate Jira-driven deployment orchestration layer for GitOps-managed platforms.

## LeninKart Integration

For the current LeninKart dev environment:

- Jira provides deployment intent
- `deployment-poc` resolves the target using config
- `leninkart-infra` remains the GitOps source of truth
- ArgoCD reconciles from `leninkart-infra` `dev`
- the `dev` namespace is the deployment namespace

## Core Flow

1. GitHub Actions `workflow_dispatch` receives `jira_ticket`
2. Jira API fetches the issue
3. ticket description metadata is parsed
4. validators confirm metadata completeness and allowed env
5. target resolver maps the request to repo/path/app/namespace
6. pre-checks confirm the target file exists and optionally inspect ArgoCD
7. GitOps repo manager updates the correct `values-dev.yaml`
8. commit and push trigger ArgoCD reconciliation
9. ArgoCD client optionally syncs/polls until `Synced` and `Healthy`
10. post-checks summarize the result

## Reusability

Project-specific behavior is externalized into:

- `config/projects.yaml`
- `config/app_mapping.yaml`
- `config/environments.yaml`
- `config/jira_field_mapping.yaml`

