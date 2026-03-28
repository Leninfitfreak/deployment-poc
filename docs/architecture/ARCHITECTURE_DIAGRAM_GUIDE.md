# Architecture Diagram Guide

This folder now contains three architecture views for different audiences and levels of detail.

## Which Diagram To Use

- `leninkart-platform-architecture-showcase.*`
  Use for LinkedIn, GitHub portfolio pages, and interview walkthroughs. This is the best single-image summary of the platform story.
- `leninkart-platform-architecture.*`
  Use for a simpler high-level boundary view when you want a lighter technical overview.
- `leninkart-platform-architecture-detailed.*`
  Use for engineering deep dives. It expands the real in-cluster workloads, platform support, observability runtime, and Docker Compose Kafka boundary.
- `deployment-flow.*`
  Use when the focus is specifically the Jira -> GitHub Actions -> self-hosted runner -> deployment-poc -> GitOps -> ArgoCD deployment path.

## How These Map To The Real Workspace

- `deployment-poc`
  Jira-driven deployment orchestration, safety controls, Jira feedback, and workflow entrypoints.
- `leninkart-infra`
  GitOps source of truth for the dev branch and ArgoCD-managed applications.
- `leninkart-frontend`, `leninkart-product-service`, `leninkart-order-service`
  Application repos represented inside the Kubernetes runtime.
- `kafka-platform`
  External Docker Compose Kafka runtime used by the in-cluster services.
- `observability-stack/bootstrap`
  External bootstrap/generator layer that writes observability values into GitOps.
- `project-validation`
  Observer-only evidence and reporting layer.

## Regeneration Notes

- PlantUML files are the technical source-of-truth for architecture meaning.
- draw.io files are the editable presentation layer.
- PNG files are the presentation exports currently used by the README and architecture docs.

When updating the diagrams in the future, keep the architecture meaning aligned with the real workspace and cluster runtime before changing layout or visual style.
