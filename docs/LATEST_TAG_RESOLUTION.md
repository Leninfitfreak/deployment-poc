# Latest Tag Resolution

## Purpose

LeninKart service repositories now publish the latest built image tags into a shared metadata file so Jira tickets do not need a manual Docker Hub tag lookup for normal dev deployments.

The model is intentionally split:

- service repo CI builds, tests, pushes images, and publishes tag metadata
- `deployment-poc` reads Jira, resolves the version, updates GitOps, and verifies ArgoCD
- `leninkart-infra` remains the GitOps source of truth
- ArgoCD remains the reconciler, not the deployment decision maker

## Metadata Source

Shared latest-tag metadata lives in:

- `config/latest_tags.yaml`

Current shape:

```yaml
services:
  frontend:
    dev:
      latest: "23599512080"
      image: "leninfitfreak/frontend"
      updated_at: "2026-03-28T00:00:00Z"
      source_repo: "Leninfitfreak/leninkart-frontend"
      source_branch: "dev"
```

The same structure is used for:

- `frontend`
- `product-service`
- `order-service`

And is environment-aware so `dev`, `staging`, and `prod` can be extended cleanly.

## Service CI Responsibilities

Each service repo CI workflow now does only the following:

1. build the service image
2. run its normal quality checks
3. push the Docker image
4. publish the latest built tag into `deployment-poc/config/latest_tags.yaml`

Service repo CI must not:

- update `leninkart-infra`
- change `values-dev.yaml`
- deploy directly

## Deployment-Poc Responsibilities

`deployment-poc` remains the only GitOps writer.

It is responsible for:

1. reading the Jira request
2. resolving the target app/environment
3. resolving the requested version to an exact image tag
4. updating the GitOps values file in `leninkart-infra`
5. waiting for ArgoCD to report the exact pushed revision as `Synced` and `Healthy`
6. publishing Jira progress and final feedback

## Version Resolution Order

The current resolution order is:

1. `latest` or `latest-dev`
   - resolved from `config/latest_tags.yaml`
2. configured aliases such as `v1`, `v2`
   - resolved from `config/app_mapping.yaml`
3. any other value
   - treated as an explicit exact image tag

Examples:

- `version: latest`
- `version: latest-dev`
- `version: v1`
- `version: v2`
- `version: 23599512382`

## Jira Examples

### Latest dev deployment

```text
app: leninkart
component: product-service
env: dev
version: latest-dev
url: http://dev.leninkart.local/api/products
```

### Generic latest deployment

```text
app: leninkart
component: order-service
env: dev
version: latest
url: http://dev.leninkart.local/api/orders
```

### Exact tag deployment

```text
app: leninkart
component: frontend
env: dev
version: 23599512080
url: http://dev.leninkart.local/
```

### Alias-based deployment

```text
app: leninkart
component: product-service
env: dev
version: v2
url: http://dev.leninkart.local/api/products
```

## Workflow Ownership Summary

- `leninkart-frontend`: build/push + publish latest tag metadata
- `leninkart-product-service`: build/push + publish latest tag metadata
- `leninkart-order-service`: build/push + publish latest tag metadata
- `deployment-poc`: resolve version + update GitOps + verify ArgoCD
- `leninkart-infra`: desired-state source of truth
- ArgoCD: reconcile Git to cluster state

## Important Note About Secrets

The service CI workflows use the shared cross-repo PAT secret `PAT_TOKEN` to push metadata updates into `deployment-poc`.

This keeps service CI metadata publishing and deployment-poc GitOps writes aligned on one explicitly named secret.
