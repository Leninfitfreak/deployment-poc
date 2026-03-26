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
