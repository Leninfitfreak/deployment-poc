# POC Runbook

## Input

- Jira ticket key only

Example:

```text
SCRUM-5
```

## Expected Jira Description Format

```text
app: leninkart
component: product-service
env: dev
version: 23599211809
url: http://dev.leninkart.local/api/products
```

`component` is optional in the parser, but it is recommended for LeninKart because the live platform deploys per service.

## Required GitHub Secrets

- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `INFRA_PAT`
- `ARGOCD_SERVER` optional if ArgoCD verification is enabled
- `ARGOCD_AUTH_TOKEN` optional if ArgoCD verification is enabled

## Local CLI

```powershell
python -m src.orchestrator --jira-ticket SCRUM-5
```

