# Architecture Diagrams

This folder contains the presentation-oriented architecture diagrams for the current LeninKart platform and deployment control plane.

## Files

- `leninkart-platform-architecture.puml`
- `leninkart-platform-architecture.png`
- `deployment-flow.puml`
- `deployment-flow.png`

## Diagram Scope

The diagrams intentionally reflect the currently implemented setup:

- Jira request input
- manual GitHub Actions dispatch
- Windows self-hosted runner
- `deployment-poc` orchestration and safety layer
- `leninkart-infra/dev` as the GitOps source of truth
- ArgoCD and the local `k3d-leninkart-dev` cluster
- LeninKart application services
- Kafka and observability support
- `project-validation` as the proof layer

They do not depict unimplemented auto-trigger behavior from Jira.
