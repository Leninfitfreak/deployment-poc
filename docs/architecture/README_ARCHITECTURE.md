# Architecture Diagrams

This folder contains the presentation-oriented architecture diagrams for the current LeninKart platform and deployment control plane.

## Files

- `leninkart-platform-architecture.puml`
- `leninkart-platform-architecture.drawio`
- `leninkart-platform-architecture.png`
- `deployment-flow.puml`
- `deployment-flow.drawio`
- `deployment-flow.png`


## Source Of Truth

The file ownership model is intentional:

- `*.puml` is the canonical architecture source of truth
- `*.drawio` is the editable presentation layer derived from the PlantUML structure
- `*.png` is the exported presentation asset used in the README and other showcase material

The draw.io versions should stay semantically aligned with the PlantUML diagrams. Layout, spacing, grouping polish, and label readability can improve in draw.io, but architecture meaning should not diverge there.

## Presentation Usage

The PNG files in this folder are the presentation-facing exports currently used in the GitHub README. They were refined for:

- clean layered grouping
- readable labels at GitHub scale
- balanced spacing for screenshots and social sharing
- a layout that remains faithful to the implemented system

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
