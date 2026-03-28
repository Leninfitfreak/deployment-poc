# Architecture Diagrams

This folder contains the presentation-oriented architecture diagrams for the current LeninKart platform and deployment control plane.

## Files

- `leninkart-platform-architecture.puml`
- `leninkart-platform-architecture.png`
- `deployment-flow.puml`
- `deployment-flow.png`
- `leninkart-platform-architecture-linkedin.drawio`
- `leninkart-platform-architecture-linkedin.png`
- `deployment-flow-linkedin.drawio`
- `deployment-flow-linkedin.png`
- `assets/*.svg`


## Variants

The diagram set now has two presentation tracks:

- `leninkart-platform-architecture.png` and `deployment-flow.png`
  - the normal technical documentation baseline used by the README
- `*-linkedin.drawio` and `*-linkedin.png`
  - larger, icon-based presentation variants for GitHub showcase and LinkedIn use

PlantUML remains the canonical source of truth for architecture meaning. The LinkedIn variants are presentation-only derivatives and should stay semantically aligned with the PlantUML files.


The LinkedIn variants use a small local icon asset set under `docs/architecture/assets/` for real vendor-style technology logos where appropriate. Internal LeninKart-specific components that do not have an official icon stay as neutral service cards instead of placeholder bubbles.


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
