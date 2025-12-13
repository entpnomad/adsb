# Desktop Antenna (Docker Desktop)

Use this when you want to forward a local dump1090 feed from macOS/Windows to the central API ingest endpoint.

## Requirements
- Docker Desktop
- Access to a dump1090 SBS-1 feed on the host (typically `30003`)

## Configure
1) Copy the env file and edit it:
```bash
cp .env.antenna.example .env.antenna
```
2) Set at least:
```
ADSB_INGEST_URL=http://SERVER_IP:8000/api/ingest
ADSB_HOST=host.docker.internal
ADSB_PORT=30003
ADSB_BATCH_SIZE=100
```
`host.docker.internal` is already mapped in the Desktop compose file.

## Run
```bash
docker compose --env-file .env.antenna -f deploy/compose.antenna.desktop.yml up -d adsb_sender
```
- Container builds from `deploy/Dockerfile.sender`.
- It POSTs batches to `/api/ingest` while following `RECONNECT_DELAY` and `FLUSH_INTERVAL` from `adsb.config`.

## Verify
```bash
docker compose -f deploy/compose.antenna.desktop.yml logs -f adsb_sender
```
You should see connection and batch send logs. Stop with:
```bash
docker compose -f deploy/compose.antenna.desktop.yml down
```
