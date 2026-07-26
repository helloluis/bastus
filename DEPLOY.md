# BASTUS deployment

The control plane is deployed to the VPS `45.76.180.229` as a **systemd service behind
the existing nginx**, using the system Postgres. (Docker artifacts — `Dockerfile`,
`docker-compose.yml`, `Caddyfile` — also exist for a dedicated/fresh box, but the shared
VPS uses the systemd path documented here.)

## What's on the box

| Piece | Value |
|---|---|
| App dir | `/opt/bastus` (owned by system user `bastus`) |
| Service | `bastus.service` → `uvicorn` on `127.0.0.1:8010` |
| Python/deps | `uv` at `/usr/local/bin/uv`, venv in `/opt/bastus/.venv` |
| Database | system Postgres, db `bastus`, role `bastus` (password in `/opt/bastus/.env.local`) |
| Reverse proxy | nginx vhost `bastus.b11.dev` → `127.0.0.1:8010` (WebSocket-aware) |
| Secrets | `/opt/bastus/.env.local` (chmod 600): `DATABASE_URL`, `TARGET_API_KEY` |

## Enable HTTPS (pending DNS)

`bastus.b11.dev` must resolve to `45.76.180.229` first (add an A record; siblings like
`hiraia.b11.dev` already point here). Once it resolves:

```bash
ssh root@45.76.180.229 'certbot --nginx -d bastus.b11.dev --redirect -n --agree-tos -m you@example.com'
```

certbot edits the vhost in place to add the 443 server + HTTP→HTTPS redirect. Live
streaming works over `wss://` automatically (the vhost passes the Upgrade headers).

## Update / redeploy

From the project root on your machine:

```bash
rsync -az --delete \
  --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude '.cache/' --exclude '.local/' \
  --exclude 'data/' --exclude 'reports/' --exclude '*.db' --exclude '.git/' \
  --exclude '.env.local' --exclude '.env' \
  ./ root@45.76.180.229:/opt/bastus/
ssh root@45.76.180.229 'chown -R bastus:bastus /opt/bastus \
  && runuser -u bastus -- sh -lc "cd /opt/bastus && /usr/local/bin/uv sync --frozen --no-dev" \
  && systemctl restart bastus'
```

(`uv` is installed system-wide at `/usr/local/bin` precisely so `rsync --delete` on the
app dir can't remove it.)

## Operate

```bash
ssh root@45.76.180.229 'systemctl status bastus'          # state
ssh root@45.76.180.229 'journalctl -u bastus -n 100 -f'   # logs
ssh root@45.76.180.229 'systemctl restart bastus'         # restart

# Add secrets for live/Phase-3 runs, then restart:
#   edit /opt/bastus/.env.local  (add RUNPOD_API_KEY, real TARGET_* / ATTACKER_* / JUDGE_*)
```

## Going live with a real RunPod pod (Phase 3)

By default the server runs the **simulated** provisioner (no GPU spend). To provision a
real abliterated-Qwen pod:

1. Add these to `/opt/bastus/.env.local` (place the key yourself; don't paste it into a
   shell command):
   ```
   RUNPOD_API_KEY=rpa_...            # your RunPod key
   BASTUS_RUNPOD_REAL=1             # switch from simulated to real provisioning
   # optional target under test (OpenAI-compatible):
   TARGET_ENDPOINT=https://.../v1
   TARGET_API_KEY=...
   TARGET_MODEL=...
   # optional (only if the model repo is gated):
   HF_TOKEN=hf_...
   ```
2. `ssh root@45.76.180.229 'systemctl restart bastus'`
3. In the UI: **Provision RunPod** → watch the streamed ladder pick a GPU, pull the
   image, download weights, load the model, and go **Ready** with an inspect link.
4. Uncheck **Mock**, pick categories, **Launch** — runs now hit the live pod as attacker.
5. **Destroy** when done (or let the idle watchdog auto-destroy after
   `BASTUS_POD_IDLE_TTL_MIN`, default 30 min — the countdown starts when a run
   finishes/aborts and is suspended while any run is in flight).

### Provisioning knobs (env, all optional)

| Var | Default | Purpose |
|---|---|---|
| `BASTUS_ATTACKER_MODEL` | `huihui-ai/Qwen3-32B-abliterated` | model vLLM serves |
| `BASTUS_GPU_LADDER` | A100 80GB → H100 (comma-sep) | ordered GPU preference; first with capacity wins |
| `BASTUS_QUANTIZATION` | (none) | set `awq`/`gptq` for a quantized checkpoint (then a 48GB ladder fits) |
| `BASTUS_CONTAINER_DISK_GB` | `120` | container disk (BF16 32B weights ≈ 66GB) |
| `BASTUS_MAX_MODEL_LEN` | `8192` | vLLM context cap (KV-cache sizing) |
| `BASTUS_POD_IDLE_TTL_MIN` | `30` | auto-destroy pod after N idle minutes (idle = no run in flight; countdown starts when a run finishes/aborts) |
| `BASTUS_NETWORK_VOLUME_ID` | (none) | reuse a weight-cache volume across pods |

**Model-fit note:** BF16 `Qwen3-32B` (~66GB) needs an 80GB card (the default ladder).
For cheaper 48GB cards (A6000/L40S), point `BASTUS_ATTACKER_MODEL` at a 4-bit AWQ/GPTQ
abliterated checkpoint, set `BASTUS_QUANTIZATION=awq`, and set a 48GB `BASTUS_GPU_LADDER`.

## Reach it now (pre-DNS)

```bash
curl -H 'Host: bastus.b11.dev' http://45.76.180.229/api/health   # {"status":"ok"}
```
