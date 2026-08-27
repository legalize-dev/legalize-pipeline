---
name: Remote fetch runbook (GCP VM)
description: Provision a VM close to a slow source, run the fetch there, and bring the data back. Reusable for any country whose fetch is slow from Europe.
type: reference
---
# Runbook: remote fetch via a cloud VM

For countries whose source server sits far from wherever you normally run the
pipeline — South American sources (AR, UY, CL) are the recurring case for a
Europe-based run — where the fetch is slow enough that it's worth renting a VM
closer to the source instead.

This is a **latency** mitigation, not a geo-blocking workaround: the sources
this applies to do not require a regional IP to serve requests, they are just
slow and timeout-prone from far away. See "Lesson learned" below — moving the
client closer helps, but it does not fix a slow origin server.

## 1. Provision a VM

```bash
gcloud compute instances create legalize-fetch-{code} \
  --project=<your-gcp-project> \
  --zone=southamerica-east1-b \
  --machine-type=e2-small \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=20GB
```

- **Zone**: `southamerica-east1-b` (São Paulo — close to sources in AR/UY/CL/BR)
- **Machine**: `e2-small` (2 vCPU, 2 GB RAM) — enough if the catalog uses a shared cache
- **Cost**: a few cents per hour; delete the VM when done

## 2. Upload the code and any pre-fetched catalog

```bash
cd engine/

# Package the engine (no fixtures, no tests — just src + config)
tar czf /tmp/{code}-engine.tar.gz src/legalize/ config.yaml pyproject.toml

# Upload the engine
gcloud compute scp /tmp/{code}-engine.tar.gz legalize-fetch-{code}:~ --zone=southamerica-east1-b

# Upload any pre-downloaded catalog (if you have one)
gcloud compute scp ../countries/data-{code}/catalog/*.zip legalize-fetch-{code}:~ --zone=southamerica-east1-b
```

## 3. Configure the VM (SSH + install deps)

```bash
gcloud compute ssh legalize-fetch-{code} --zone=southamerica-east1-b

# On the VM:
sudo apt-get update -q && sudo apt-get install -y -q python3 python3-pip python3-venv screen
mkdir -p engine && cd engine
tar xzf ~/{code}-engine.tar.gz
python3 -m venv .venv && source .venv/bin/activate
pip install -q lxml requests pyyaml click rich
mkdir -p ../countries/data-{code}/catalog ../countries/data-{code}/json ../countries/{code}

# Copy the catalog over, if uploaded in step 2
cp ~/base-*.zip ../countries/data-{code}/catalog/ 2>/dev/null || true

# Sanity check the import
PYTHONPATH=src python3 -c "from legalize.config import load_config; print('OK')"
```

## 4. Launch the fetch in `screen` (persistent across SSH disconnects)

```bash
# Create the fetch script
cat > ~/run-fetch.sh << 'SCRIPT'
#!/bin/bash
cd ~/engine
source .venv/bin/activate
export PYTHONPATH=src
python3 -u -c "
from legalize.config import load_config
from legalize.pipeline import generic_fetch_all
config = load_config('config.yaml')
fetched = generic_fetch_all(config, '{code}', force=False)
print(f'DONE: {len(fetched)} norms fetched')
" > /tmp/fetch.log 2>&1
SCRIPT
chmod +x ~/run-fetch.sh

# Launch inside screen and disconnect
screen -dmS fetch bash ~/run-fetch.sh
exit
```

You can close the SSH session (and your laptop) now. The VM keeps running.

## 5. Monitor from your machine, periodically

```bash
gcloud compute ssh legalize-fetch-{code} --zone=southamerica-east1-b --command='
  jsons=$(ls ~/countries/data-{code}/json/*.json 2>/dev/null | wc -l)
  tail -3 /tmp/fetch.log
  echo "$jsons JSONs"
  free -h | head -2
'
```

## 6. Bring the JSONs back when it finishes

```bash
# On the VM: compress the JSONs
gcloud compute ssh legalize-fetch-{code} --zone=southamerica-east1-b --command='
  tar czf /tmp/data-{code}-jsons.tar.gz -C ~/countries data-{code}/json/
'

# From your machine: download
gcloud compute scp legalize-fetch-{code}:/tmp/data-{code}-jsons.tar.gz /tmp/ --zone=southamerica-east1-b

# Extract into the right place
cd countries/
tar xzf /tmp/data-{code}-jsons.tar.gz
```

## 7. Commit locally (fast-import, minutes)

```bash
cd engine/
rm -rf ../countries/{code} && mkdir -p ../countries/{code}
legalize commit -c {code} --all
```

Or, if the country has a custom bootstrap hook:

```bash
legalize bootstrap -c {code}
```

## 8. Push, sync the DB, deploy

```bash
# Push
git -C ../countries/{code} remote add origin git@github.com:legalize-dev/legalize-{code}.git 2>/dev/null
git -C ../countries/{code} branch -M main
git -C ../countries/{code} push -u origin main --force

# DB sync (from the local repo, no API calls)
cd ../enrichment
law-sync full --repo ../countries/{code}

# Web deploy
cd ../web
vercel deploy --prod --force
```

## 9. Delete the VM

```bash
gcloud compute instances delete legalize-fetch-{code} --zone=southamerica-east1-b --quiet
```

## Gotchas

- **RAM**: the InfoLEG catalog takes ~250 MB in memory. With the shared cache
  (`_CATALOG_CACHE` in `client.py`), 4 workers fit in 2 GB. Without it, every
  worker loads its own copy and you OOM.
- **screen**: always launch with `screen -dmS fetch bash script.sh` so the
  process survives the SSH session closing. An inline `nohup` inside an SSH
  one-liner does not survive.
- **SSH timeouts**: long inline SSH commands (>30s) can fail. Split into short
  steps or upload scripts as files instead.
- **Lockfile**: if your deploy pipeline uses `uv` to install deps, regenerate
  `uv.lock` (`uv lock`) after changing `pyproject.toml`, or the deploy fails
  with `ModuleNotFoundError`.
- **Monthly catalog refresh**: InfoLEG regenerates its catalog on the 1st of
  the month. For fresh data, delete `data-ar/catalog/*.zip` before fetching.

## Lesson learned (Argentina bootstrap)

**A VM in São Paulo cuts latency ~3× (300ms→107ms) but does NOT eliminate
timeouts from the InfoLEG server.** Its Apache 2.2.22 server returns
`Read timed out (60s)` regardless of where the client sits. The VM helps a lot
for "Tier 2" norms (one request each — 30K norms in ~3h instead of ~9h), but
for "Tier 1" norms (many amending-act lookups, each prone to timing out) the
improvement is marginal.

**Takeaway**: the VM pays for itself for countries with mostly Tier-2 norms
(one request per norm). Where most norms are Tier 1 (heavily amended), the
bottleneck is the origin server, not the network — a regional VM will not fix
that.

## Multi-VM: splitting the fetch across several machines

For sources that rate-limit per IP, split the work across N machines with
distinct IPs.

### Example: 3 VMs for 32K norms

```bash
# VM-1: norms 0-10724
legalize fetch -c ar --all --limit 10725

# VM-2: norms 10725-21449
legalize fetch -c ar --all --offset 10725 --limit 10725

# VM-3: norms 21450-32175
legalize fetch -c ar --all --offset 21450
```

### Merging the JSONs

Each VM produces JSONs under `data-ar/json/`. Filenames are the norm ID
(unique), so they merge without conflict:

```bash
# From your machine:
for vm in vm1 vm2 vm3; do
  gcloud compute scp $vm:/tmp/data-ar-jsons.tar.gz /tmp/data-ar-$vm.tar.gz --zone=southamerica-east1-b
  tar xzf /tmp/data-ar-$vm.tar.gz -C ../countries/
done
# All JSONs now sit together under data-ar/json/
```

### Commit once

```bash
cd engine/
legalize commit -c ar --all    # fast-import, reads ALL JSONs under data-ar/json/
```

### Notes

- `discovery_ids.txt` is generated on the first VM. Copy it to the others so
  they use the same ordering and `--offset` lines up correctly.
- Each VM needs the catalog (`catalog/*.zip`). Upload it once and copy to all.
- The JSONs are independent of each other — there is no shared state between
  VMs during the fetch.
