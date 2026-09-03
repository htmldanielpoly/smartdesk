# Deploying SmartDesk to an Azure VM

The pipeline in `.github/workflows/ci.yml` does the whole chain on every push
to `main`:

```
lint-test (ruff + pytest, 3 services) ──► docker-smoke (full stack, e2e) ──► publish (GHCR images, :latest + :<sha>)
                                                                                  │
                                                                                  ▼
                                                                    deploy (SSH to the VM, pull :<sha>, health check)
```

`deploy` only runs when the repository variable `DEPLOY_HOST` exists, so the
pipeline is green and complete before the VM is provisioned (CI-only), and
switches itself on the moment the variable is set (CI + CD).

## 1. The VM (once)

Any Ubuntu 22.04/24.04 VM with 2 vCPU / 4 GB works (`Standard_B2s`); the local
models run on CPU and need ~1 GB of RAM together. Open inbound **22, 80, 443**
in the network security group and give the VM a DNS name (an `A` record for
your domain pointing at its public IP; Azure's `<name>.<region>.cloudapp.azure.com`
label works too).

```bash
# on the VM
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
sudo mkdir -p /opt/smartdesk && sudo chown $USER /opt/smartdesk
```

Copy `deploy/docker-compose.prod.yml`, `deploy/Caddyfile` and a filled-in
`deploy/.env.example` as `/opt/smartdesk/.env`:

```bash
scp deploy/docker-compose.prod.yml deploy/Caddyfile azureuser@<vm>:/opt/smartdesk/
# then on the VM
cd /opt/smartdesk
cp /path/to/.env.example .env      # set DOMAIN, ADMIN_EMAIL, ADMIN_PASSWORD
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
```

The GHCR packages are private by default. Either make the three packages
public (GitHub → Packages → package → Settings → Change visibility) or log the
VM in once with a classic PAT that has `read:packages`:

```bash
echo <PAT> | docker login ghcr.io -u <github-user> --password-stdin
```

First start (downloads the ~450 MB of model files into a volume):

```bash
docker compose --env-file .env -f docker-compose.prod.yml pull
docker compose --env-file .env -f docker-compose.prod.yml up -d
curl -fsS https://$DOMAIN/health        # {"status":"ok"}
```

Caddy obtains the certificate automatically; the first HTTPS request can take
a few seconds while it does.

## 2. GitHub configuration (once)

Repository **variables** (Settings → Secrets and variables → Actions → Variables):

| Variable | Value |
|---|---|
| `DEPLOY_HOST` | the VM's public DNS name or IP (this switches the job on) |
| `DEPLOY_USER` | SSH user, e.g. `azureuser` |
| `DEPLOY_DOMAIN` | the public domain, used for the post-deploy health check |

Repository **secrets**:

| Secret | Value |
|---|---|
| `DEPLOY_SSH_KEY` | private key whose public half is in the VM's `~/.ssh/authorized_keys` |

Nothing else: the images are pulled by the VM, and all application secrets
live only in `/opt/smartdesk/.env` on the VM.

## 3. What a deploy does

1. Waits for `publish` (which waited for the tests and the full-stack smoke
   test), so a red build never reaches the server.
2. SSHes in, rewrites `IMAGE_TAG=<commit sha>` in `.env`, `docker compose
   pull`, `docker compose up -d --remove-orphans`, prunes old images.
3. Polls `https://$DEPLOY_DOMAIN/health` until it answers `200` (up to two
   minutes) and fails the run otherwise.

**Rollback:** on the VM, set `IMAGE_TAG` in `.env` to any earlier commit sha
(every published image is tagged with its sha) and run
`docker compose --env-file .env -f docker-compose.prod.yml up -d`.

## 4. Scaling notes

The gateway is stateless apart from the in-memory rate limiter and (after the
forum upgrade) the WebSocket manager, so scaling out means moving those to a
shared store (Redis) and running `api-service`/`forum-service` with several
replicas behind Caddy. Inside one VM the parallelism is already there: the AI
service schedules work on a priority queue across a worker pool with one lock
per model (`AI_WORKERS`, `LLM_THREADS`), and the gateway never blocks on the
AI.

## 5. Local Docker Desktop instead of Azure

The self-hosted flavour of the deploy job still exists for demos on a
teammate's machine: register a self-hosted runner on the repo and set the
repository variable `DEPLOY_SELF_HOSTED=true`. It rebuilds from source on
that machine and needs a `.env` there (it copies `.env.example` if none
exists).
