# Raspberry Pi Antenna

Use this flow to run the collector on a Pi with an RTL-SDR dongle and dump1090.

## Prerequisites
- Raspberry Pi OS (Bullseye or later)
- RTL-SDR + 1090 MHz antenna
- dump1090 with `--net` enabled (e.g., `dump1090-fa`)
- Python 3.9+ and git

## Install dependencies
```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip dump1090-fa
```

## Clone and set up
```bash
git clone <repo-url> adsb
cd adsb
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally (CSV + map)
```bash
# Start dump1090 elsewhere (if not already running)
# dump1090 --net --interactive

# Collect CSVs and build the map
python -m apps.adsb_cli csv
# or the bundled helper that also serves/refreshes the map
./adsb.sh
```
- Outputs live CSVs and maps under `output/`.
- Set your home location once for accurate distances:
```bash
python -m apps.plot_map --home-address "City, Country"
```

## Install Docker (for the sender container)
Docker is optional. Use it if you prefer an isolated runtime and easy auto-restart via Compose.
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo apt-get install -y docker-compose-plugin
docker --version
docker compose version
```
- Log out/in (or reboot) after adding your user to the `docker` group.

## Send data to a central API (Pi as antenna)
Copy and edit `.env.antenna.example` to `.env.antenna`:
```
ADSB_INGEST_URL=http://SERVER_IP:8000/api/ingest
ADSB_HOST=127.0.0.1
ADSB_PORT=30003
ADSB_BATCH_SIZE=100
```
Then run the sender (host networking works on Linux/Pi):
```bash
docker compose --env-file .env.antenna -f deploy/compose.antenna.yml up -d adsb_sender
```
This reads `dump1090` locally and POSTs batches to the API ingest endpoint.
