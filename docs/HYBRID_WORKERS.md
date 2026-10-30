# Hybrid VM1/Raspberry Pi workers

This slice keeps the FoodMaster API, frontend, and PostgreSQL on VM1. PULL jobs
and push jobs are durable database queue entries. Push jobs target VM1 and are
executed by the VM1 worker; PULL jobs can be executed by one of two workers:

- `vm1`: primary worker; claims `vm1` and `auto` jobs immediately.
- `pi`: assist worker; claims explicit `pi` jobs immediately and claims `auto`
  jobs only after the configured overflow delay (30 seconds by default).

Price push and C5 push jobs use `worker_target=vm1`; the Pi worker does not claim
push jobs because its browser/session files are not part of the push deployment.
The worker runs up to three jobs concurrently by default (`WORKER_CONCURRENCY=3`).
GoFood jobs remain sequential behind the GoFood platform lock.

The API defaults new PULL requests to `worker_target=auto`. Existing jobs are
migrated to `vm1` so an upgrade does not reroute work that was already queued.
The endpoint also accepts `worker_target=vm1|pi|auto` for explicit routing.

## Before enabling the Pi worker

1. Bind VM1 PostgreSQL to its Tailscale address only, not the public interface.
2. Restrict the PostgreSQL port in the VM1 firewall to the Pi Tailscale IP.
3. Create a Pi `.env` with the same database URL and required application
   credentials. Do not copy credentials into this document or source control.
4. Make `/app/data` shared between VM1 and Pi. PULL results and exported files
   are currently stored under this path, so a private Pi-only `data` directory
   would make the job status point at files that the API cannot serve.
5. Copy/sync the platform session files and browser profiles required by the
   selected outlets to the Pi. Do not run the same browser profile on both
   workers at the same time.

## VM1

The normal Compose stack now includes `foodmaster-worker-vm1`. Start it with
the existing backend stack after reviewing the generated Compose config:

```sh
docker compose up -d --build backend worker frontend
```

## Raspberry Pi

From a checkout with the shared `data` mount prepared, run only the worker:

```sh
docker compose -f docker-compose.worker.yml up -d --build worker
```

The Pi worker uses `WORKER_ID=pi` and `WORKER_AUTO_DELAY_SECONDS=30`.

## Acceptance checks

- A normal Pull creates `PENDING` with `worker_target=auto`.
- VM1 claims it immediately when the VM1 worker is healthy.
- A queued `auto` job older than the Pi overflow delay can be claimed by Pi.
- An explicit `worker_target=pi` job is never claimed by VM1.
- VM1 and Pi cannot claim the same job.
- Cancelling a queued or running job keeps the existing `CANCELLED` behavior.
- The resulting export is readable through the VM1 download endpoint.
