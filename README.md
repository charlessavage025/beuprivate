# SwiftTrack

A Django + HTMX package tracking demo (FedEx-style), built for the `swifttrack` project. Every status change comes from a `TrackingEvent`; `Shipment.status` and `Shipment.current_location` are cached copies always recomputed from the latest event. There are no background workers — scans only happen when a person clicks a button, submits a form, or runs a management command.

Just two models: `Shipment` and `TrackingEvent`. There is no separate Address or
Facility table — sender/recipient details are plain fields directly on `Shipment`,
and the hubs/facilities a shipment passes through (`Shipment.route`, a JSON list of
plain strings) are typed in by hand when the shipment is created, not picked from a
lookup table.

## Stack

- Django 5.2, single app `tracking`
- HTMX (via CDN) + `django-htmx` for partial-page updates, no React/Vue
- PostgreSQL via `DATABASE_URL`, falling back to SQLite if unset
- `python-dotenv` for environment variables

## Setup

```bash
python -m venv venv
source venv/Scripts/activate        # Windows Git Bash / macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                # edit if you want Postgres / different settings

python manage.py migrate
python manage.py seed_demo          # creates facilities, an admin user, and sample shipments
python manage.py runserver
```

Then open http://127.0.0.1:8000/.

`seed_demo` prints:
- The superuser credentials (`admin` / `admin123`) if it created one.
- Three sample tracking numbers (one in transit, one out for delivery, one delivered) so you have something to search for immediately.

Useful flags:
- `python manage.py seed_demo --shipments 40` — seed more shipments.
- `python manage.py seed_demo --reset` — wipe existing shipments/events first, then reseed.

## Creating a shipment (route typed in by hand)

When staff create a shipment at `/staff/shipments/new/`, they type in the sender and
recipient details directly (plain fields on `Shipment`, no separate Address record),
plus an **Origin**, a **Destination**, and an optional **Stops** textarea — one
hub/facility name per line, in order. That typed-in list becomes `Shipment.route`
verbatim; nothing is looked up or randomly generated for shipments created this way.
Every scan (manual, staff "Advance", or the management command) just moves the
shipment forward through that specific list, one stop at a time.

(`seed_demo` is the one exception: it generates a random 1-3-stop route per shipment,
picked from a small built-in list of sample hub names in `tracking/simulator.py`, so
the demo data has variety without requiring 20+ manual entries.)

## Ways to trigger a scan (all manual, all staff-only — nothing runs on a timer, and the public tracking page is read-only)

1. **Staff dashboard** (`/staff/`, requires a staff login), per shipment row:
   - **Advance** — moves the shipment forward one step (or resumes it if it's currently flagged delayed).
   - **Rewind** — undoes the shipment's latest scan, moving it back one step. Works even on a delivered shipment, to undo an accidental delivery. Disabled once there's nothing left to undo.
   - **Flag delay** — prompts for a reason, then marks the shipment `DELAYED` and logs that reason on the event, independent of the random delay `advance()` sometimes rolls on its own. Hidden once delivered.
   - **Run to delivery** — repeatedly advances a single shipment until it's delivered.
   - **Advance all in-transit** (dashboard-wide button) — advances every non-delivered shipment by one step.
2. **Manual staff scan** (`/staff/scan/`) — staff pick the event type, type in a location/facility name, location note, and (required when the event type is "Delayed") a delay reason; can optionally backdate the timestamp.
3. **Management command**:
   ```bash
   python manage.py simulate_scan <tracking_number> [--steps N]
   python manage.py simulate_scan --all
   ```
   Runs once and exits — no loop, no daemon.

## Login

Staff-only pages (`/staff/...`) require a logged-in user with `is_staff=True`. Log in at `/accounts/login/` with `admin` / `admin123` after seeding (or via `python manage.py createsuperuser`).

## Running tests

```bash
python manage.py test
```

## Deploying (Render + Neon)

The app is ready to deploy as-is: `dj-database-url` + `psycopg2-binary` handle
Postgres, `whitenoise` serves static files (no separate CDN/static host
needed), and `gunicorn` is the production server.

**1. Database — [Neon](https://neon.tech) (free Postgres)**

1. Create a Neon project. Copy the connection string from the dashboard —
   it already includes `?sslmode=require`, e.g.:
   `postgresql://user:password@ep-xxxx-pooler.region.aws.neon.tech/dbname?sslmode=require`
2. Keep it handy for the `DATABASE_URL` env var below.

**2. Web service — [Render](https://render.com) (free tier)**

Either use the included `render.yaml` Blueprint (New → Blueprint, point it at
this repo — it wires up the build/start commands and generates `SECRET_KEY`
for you), or configure a Web Service manually with:

- Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
- Start command: `gunicorn swifttrack.wsgi:application`

Either way, set these environment variables on the service:

| Variable | Value |
|---|---|
| `SECRET_KEY` | a random secret (Render's Blueprint generates this automatically) |
| `DEBUG` | `False` |
| `DATABASE_URL` | the Neon connection string from step 1 |
| `ALLOWED_HOSTS` | `your-app.onrender.com` |
| `CSRF_TRUSTED_ORIGINS` | `https://your-app.onrender.com` |

Render assigns the `onrender.com` subdomain on first deploy — after that
first deploy, go back and fill in `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` with
the real hostname and redeploy.

**3. First-time data**

Render's shell (or a one-off job) lets you run management commands against
the deployed app, same as locally:

```bash
python manage.py seed_demo
```

Note: Render's free web service spins down after periods of inactivity, so
the first request after idling will be slow (cold start) — expected on the
free tier, not a bug.

## 2-minute demo script

1. Run `python manage.py seed_demo` and note the three sample tracking numbers it prints.
2. Open the **out-for-delivery** tracking number in one browser tab: `http://127.0.0.1:8000/track/<tracking_number>/`.
3. In a second tab, log in at `/accounts/login/` (`admin` / `admin123`) and open the **staff dashboard** (`/staff/`). Filter by status if you like.
4. Find the same shipment in the staff table and click **Advance**. Its row updates immediately.
5. Switch back to the first tab — within 15 seconds the public tracking page polls `/track/<tn>/timeline/` and shows the new status without a refresh.
6. Back on the staff dashboard, click **Rewind** on that same row — it undoes the step you just advanced, and the public tab reflects that on its next poll too.
7. Click **Flag delay** on an in-transit shipment, type in a reason when prompted — it's marked `DELAYED` immediately, with that reason visible in its tracking history; click **Advance** again to resume its normal flow.
8. Go to **Manual scan** (`/staff/scan/`). Submit a scan for a tracking number with an event type that's *earlier* than its current status and a backdated timestamp — submit, then reload the tracking page and confirm the status badge did **not** move backwards (TrackingEvent is the source of truth; the shipment always reflects whichever event has the latest timestamp).
9. Back on the staff dashboard, click **Run to delivery** on any remaining in-transit shipment. It jumps straight to Delivered, and its public tracking page timeline stops polling (no more `hx-trigger` on the timeline block) once delivered. Click **Rewind** on it — it un-delivers and starts polling again.

## Project layout

- `tracking/models.py` — just `Shipment` and `TrackingEvent`. Sender/recipient are flat `sender_*`/`recipient_*` fields on `Shipment` (no Address model); `Shipment.route` is a JSON list of plain hub/facility name strings (no Facility model); `TrackingEvent.location` is a free-text string, not a relation. The status/location sync rule lives in `TrackingEvent.save()` and a `post_delete` signal, both recomputing from `shipment.events.order_by("-timestamp", "-id").first()`.
- `tracking/services.py` — `create_shipment()`, the only way shipments get created (sets `route`, the initial `LABEL_CREATED` event, and the ETA).
- `tracking/simulator.py` — `advance()`, `rewind()`, `flag_delay()`, `advance_all()`, `run_to_delivery()`, and `build_sim_route()` (random-route fallback for seed data only, drawing from `SAMPLE_WAYPOINT_NAMES`). All scan-producing logic lives here; views and the management command just call into it.
- `tracking/views.py` — thin views; templates in `tracking/templates/tracking/` (full pages) and `tracking/templates/tracking/partials/` (HTMX fragments).
- `tracking/management/commands/` — `seed_demo.py`, `simulate_scan.py`.
- `tracking/tests/` — model, simulator, view, and management-command tests.
