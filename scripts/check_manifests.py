"""Rules for the rendered Kubernetes manifests that a schema cannot check.

Usage:  kubectl kustomize k8s > rendered.yaml
        python scripts/check_manifests.py rendered.yaml

Project 2's requirements were health checks and horizontal scaling. This
makes the pipeline fail if a later change quietly drops one of them.
Needs PyYAML (already on GitHub's runners).
"""
import sys

import yaml

SERVICES = {"web", "links", "stats"}


def main():
    docs = [d for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")) if d]
    by_kind = {}
    for doc in docs:
        by_kind.setdefault(doc["kind"], {})[doc["metadata"]["name"]] = doc
    problems = []

    def need(condition, message):
        if not condition:
            problems.append(message)

    deployments = by_kind.get("Deployment", {})
    need(set(deployments) == SERVICES, f"expected Deployments {sorted(SERVICES)}, found {sorted(deployments)}")
    for name, deployment in deployments.items():
        spec = deployment["spec"]
        need("replicas" not in spec, f"{name}: 'replicas' is set, but the autoscaler owns that number")
        pod = spec["template"]["spec"]
        need(pod.get("topologySpreadConstraints"), f"{name}: pods are not spread over zones")
        for container in pod["containers"]:
            where = f"{name}/{container['name']}"
            need("livenessProbe" in container, f"{where}: no liveness probe")
            need("readinessProbe" in container, f"{where}: no readiness probe")
            resources = container.get("resources", {})
            need(resources.get("requests", {}).get("cpu"), f"{where}: no CPU request (the autoscaler needs one)")
            need(resources.get("limits"), f"{where}: no resource limits")
            security = container.get("securityContext", {})
            need(security.get("runAsNonRoot") is True, f"{where}: may run as root")
            need(security.get("readOnlyRootFilesystem") is True, f"{where}: root filesystem is writable")
            image = container["image"]
            need(":latest" not in image, f"{where}: image uses the 'latest' tag")

    for kind in ("HorizontalPodAutoscaler", "PodDisruptionBudget", "Service"):
        missing = SERVICES - set(by_kind.get(kind, {}))
        need(not missing, f"no {kind} for {sorted(missing)}")
    for name, hpa in by_kind.get("HorizontalPodAutoscaler", {}).items():
        need(hpa["spec"]["minReplicas"] >= 2, f"{name}: fewer than 2 pods allowed, so one failure is an outage")

    # Only web may be reachable from outside the cluster.
    for name, service in by_kind.get("Service", {}).items():
        if name in ("links", "stats"):
            need(service["spec"].get("type", "ClusterIP") == "ClusterIP", f"{name}: must stay internal (ClusterIP)")
    need(by_kind.get("NetworkPolicy"), "no NetworkPolicy protecting links and stats")

    # The web pods must have no Google Cloud identity.
    web_pod = deployments.get("web", {}).get("spec", {}).get("template", {}).get("spec", {})
    need(web_pod.get("automountServiceAccountToken") is False, "web: service account token is mounted")

    for problem in problems:
        print(f"FAIL  {problem}")
    print(f"{len(docs)} objects checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
