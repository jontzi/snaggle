# Snaggle app

This folder contains the Snaggle application:

- `app.py` is the FastAPI backend.
- `static/` contains the HTML, CSS, and JavaScript UI.
- `Dockerfile` builds the app container.
- `k8s.yaml` is a basic Kubernetes Deployment and NodePort Service.

Run from the repo root:

```bash
docker build -t snaggle:latest ./snaggle
docker run --rm -p 8000:8000 snaggle:latest
```

Open:

```text
http://localhost:8000
```
