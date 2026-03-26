# POC Test Cases

## Happy Path

1. valid Jira ticket exists
2. description contains valid deployment metadata
3. target app/env mapping resolves successfully
4. values file exists in `leninkart-infra`
5. orchestrator updates image tag and pushes to `dev`
6. ArgoCD reaches `Synced` and `Healthy`

## Failure Cases

- invalid Jira key
- Jira auth failure
- missing deployment metadata
- invalid URL
- unsupported environment
- unknown app or component
- missing target values file
- missing `INFRA_PAT`
- ArgoCD sync failure
- ArgoCD health timeout

