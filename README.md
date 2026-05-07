# Snaggle

Snaggle is a small self-hosted web app for downloading videos from social links.

The idea is simple: paste a link, Snaggle detects the source, and you download the video. No accounts, no feed, no dashboard, no complicated workflow around it.

Supported sources:

- Facebook
- X/Twitter
- TikTok
- Instagram

Snaggle uses [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) for the actual downloading. This project adds a clean web UI, basic URL detection, and a small FastAPI backend that is easy to run in Docker or on a home Kubernetes cluster.

## What it looks like

The UI is intentionally minimal:

1. Paste a video link.
2. Snaggle detects the source.
3. Click download.

## Project layout

```text
snaggle/
  app.py              FastAPI backend
  static/             HTML, CSS, and JavaScript frontend
  Dockerfile          Container image
  k8s.yaml            Basic Kubernetes Deployment and NodePort Service
examples/
  traefik-ingress.yaml
```

## Run with Docker

From the repo root:

```bash
docker build -t snaggle:latest ./snaggle
docker run --rm -p 8000:8000 snaggle:latest
```

Open:

```text
http://localhost:8000
```

## Deploy to Kubernetes

Build and push the image to a registry you control:

```bash
docker build -t your-registry/snaggle:latest ./snaggle
docker push your-registry/snaggle:latest
```

Edit `snaggle/k8s.yaml` and replace:

```text
image: snaggle:latest
```

with your image:

```text
image: your-registry/snaggle:latest
```

Then apply:

```bash
kubectl apply -f snaggle/k8s.yaml
```

The included service is a NodePort service on port `30002`, so it can be reached at:

```text
http://YOUR_SERVER_IP:30002
```

## Optional Traefik ingress

If your cluster uses Traefik or another ingress controller, copy the example and change the hostname:

```bash
cp examples/traefik-ingress.yaml my-snaggle-ingress.yaml
```

Edit:

```text
snaggle.example.local
```

to whatever hostname you use, then apply it:

```bash
kubectl apply -f my-snaggle-ingress.yaml
```

You will also need DNS for that hostname to point to your server or load balancer.

## Local k3s without a registry

For small homelab setups, you can also build the image directly on the k3s server and import it into k3s/containerd:

```bash
sudo docker build -t snaggle:latest ./snaggle
sudo docker save snaggle:latest | sudo k3s ctr -n k8s.io images import -
kubectl apply -f snaggle/k8s.yaml
```

This keeps the setup simple if you do not want to run a registry yet.

## Runtime settings

These environment variables can be changed in `snaggle/k8s.yaml` or passed to Docker:

```text
MAX_DOWNLOAD_SECONDS=900
MAX_FILE_SIZE=2000M
```

## Notes

Snaggle does not try to bypass access controls. It is meant for links you can already access and have the right to save.

Social platforms change often, so download support depends on `yt-dlp` staying current. If a platform breaks, rebuild the container so it installs a newer `yt-dlp` release.

## License

No license has been chosen yet.
