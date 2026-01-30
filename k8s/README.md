# K8s Manifests (homework-agent)

This directory contains a minimal set of Kubernetes manifests for running the backend.

Important:
- Do not commit real secrets. Use an external Secret Manager or CI/CD injection.
- `k8s/secret.example.yaml` is a template only.

## Apply order

```bash
kubectl apply -f k8s/namespace.yaml

# Create the Secret using your own method.
# Option A (manual, non-prod):
kubectl apply -f k8s/secret.example.yaml

# IMPORTANT (prod):
# - Set `ALLOW_ORIGINS` in `k8s/deployment-api.yaml` to your real frontend origin allowlist
#   (JSON list string, e.g. ["https://app.example.com"]). The default is "[]", which will fail-fast.
# - Set `AUTH_MODE` to `local` or `supabase` based on your auth strategy.

kubectl apply -f k8s/deployment-api.yaml
kubectl apply -f k8s/service.yaml

kubectl apply -f k8s/worker-grade.yaml
kubectl apply -f k8s/worker-qindex.yaml
kubectl apply -f k8s/worker-facts.yaml
kubectl apply -f k8s/worker-report.yaml
kubectl apply -f k8s/worker-review-cards.yaml
kubectl apply -f k8s/cronjob-expiry-worker.yaml

# Optional: autoscaling (requires Metrics Server and KEDA installed)
kubectl apply -f k8s/hpa-api.yaml
kubectl apply -f k8s/keda-grade-worker.yaml
```

## Notes

- `k8s/keda-grade-worker.yaml` uses `REDIS_HOST` (host:port) via env on the grade worker pods.
- The application runtime uses `REDIS_URL` (redis://.../db).
