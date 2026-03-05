# Browser Automation Docker Infrastructure

## Quick Start

```bash
cd docker
docker-compose up -d
```

## Architecture

Each `browser-node` runs a persistent Chromium instance accessible via
Chrome DevTools Protocol (CDP) on its assigned port.

The Flask app connects to these browsers using:
```python
pool.connect_remote_cdp(account_id, "ws://localhost:9222")
```

## Scaling

Duplicate browser-node entries in docker-compose.yml for more instances.
Each node can handle up to MAX_CONCURRENT_SESSIONS concurrent tabs.

## Profile Persistence

Browser profiles are mounted as volumes from `data/browser_profiles/`.
All cookies, localStorage, IndexedDB, cache survive container restarts.

## Resource Limits

Each browser node is limited to 2GB RAM and 2 CPU cores.
Adjust in `deploy.resources.limits` as needed.
