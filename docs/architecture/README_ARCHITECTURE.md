# Architecture Diagrams

This folder contains the corrected technical and presentation architecture diagrams for the current LeninKart platform.

## Source Of Truth

- `leninkart-platform-architecture.puml`
- `deployment-flow.puml`

PlantUML is the canonical technical source for architecture meaning.

## Presentation Assets

- `leninkart-platform-architecture-linkedin.drawio`
- `leninkart-platform-architecture-linkedin.png`
- `deployment-flow-linkedin.drawio`
- `deployment-flow-linkedin.png`

The draw.io files are editable presentation derivatives that stay aligned with the corrected PlantUML model.

## Corrected Runtime Boundaries

The current diagrams now reflect these verified implementation facts:

- ArgoCD runs inside the `k3d-leninkart-dev` Kubernetes cluster
- application workloads, Postgres, Vault, External Secrets, ingress, loadtest, and observability runtime are all in-cluster
- Kafka does not run inside Kubernetes; it runs separately via `kafka-platform/docker-compose.yml`
- `observability-stack/bootstrap` is an external generator that writes values into `leninkart-infra`; it is not an in-cluster runtime service
- `deployment-poc` runs in the self-hosted runner execution path, not as a runtime platform service
- `project-validation` is a read-only proof layer and does not drive deployment

## Diagram Intent

- `leninkart-platform-architecture.*` focuses on runtime and boundary correctness
- `deployment-flow.*` focuses on the Jira -> GitHub Actions -> runner -> GitOps -> ArgoCD control path

The diagrams intentionally do not show unimplemented Jira webhook auto-trigger behavior.
