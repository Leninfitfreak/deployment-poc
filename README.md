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

## Reusability

To adapt this POC to another project, update only:

- `config/projects.yaml`
- `config/app_mapping.yaml`
- `config/environments.yaml`
- `config/jira_field_mapping.yaml`

## Runtime Note

The intended cluster context is `k3d-leninkart-dev`, but live cluster access was unavailable during this implementation session because the local k3d / Docker runtime was not active. Repo-backed GitOps discovery was therefore treated as authoritative for the initial POC design.
