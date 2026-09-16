# Reporting Dashboard

Solvit's internal support dashboard, built with Streamlit and PostgreSQL. It tracks first response, diagnosis, closure, and turnaround time (TAT) for Solver, Solvit Office Team, and External Clients requests. Google Sheets remains available as a migration fallback.

## Features

- Filters and free-text search
- First response within 30 minutes, diagnosis within 2 hours, and closure within 48 hours
- One SLA summary and an attention list for overdue or unassigned open requests
- SLA outcome bar chart and open-versus-closed doughnut chart, both following dashboard filters
- CSV report export
- Email and WhatsApp click-to-share actions
- Ticket creation, change-only editing, and deletion
- Per-field activity logging
- Optional password access gate
- Targeted Google Sheets updates that preserve unrelated rows
- Normalized Jira CSV import with repeat-import deduplication
- Four overview cards: open, needing attention, closed, and average closure turnaround time
- Validated ticket workflow transitions
- Mark responded / Mark diagnosed buttons that save the current form and record the time
- Live deadline countdowns and analytics that refresh every 10 minutes without rerunning intake/edit forms
- Assigned-agent and unassigned filters, with an open-request ownership list
- Downloadable last-seven-days versus previous-seven-days comparison
- Vehicle registration (Reg No) in Solver intake, search, request details, and CSV exports
- Official Solvit website logo in the login screen, sidebar, and dashboard header

## Using the dashboard

1. Under **Who needs support?**, select **Solver**, **Solvit Office Team**, or **External Clients**. Solver requests require a Job Request ID and allow an optional **Reg No**, such as `KDA 123A`. External client requests allow optional Job Request ID and Reg No, without an office department. All types capture the requester's name, contact details, and issue, and use the same SLA targets. Choose the actual reporting time; dashboard entry time is recorded automatically.
2. Assign a support agent at intake or under **Manage support requests**. Use **Assigned agent → Unassigned** to find requests needing an owner.
3. After responding, click **Mark responded**. Once the problem is understood, click **Mark diagnosed**. Each button records the time now and saves the current form edits. Mark diagnosed moves a To do request to Diagnosed.
4. Use the date/time fields to correct an earlier response or diagnosis time. Enter Nairobi time. New timestamps must fall between reporting and now, and cannot be later than closure for a closed request. Previously recorded milestones are not overwritten by the quick-action buttons.
5. To close an issue, select **Closed**, provide a **Resolution summary**, and save. Any open status can move directly to Closed. Editing the summary alone does not close the request.
6. Read **History for this request** for the selected request's changes. Creation and intake are combined into one readable entry. History entries are updates to one request, not additional requests.

Existing Solver IDs remain stored separately for compatibility; they are not reinterpreted as vehicle registrations. The registration migration adds a new `reg_no` column. Google Sheets appends the new header without shifting existing data.

## Roles and departments

The dashboard supports multiple departments with named user accounts. The departments are **IT, HR, Operations, and BD**. Operations is split into three sub-teams, **Scheduling, Approval, and Solver (Submissions)**, which are tagged on each request and used for filtering rather than for separate logins. The same SLA targets apply to every department.

Each request carries three routing fields on top of the existing "Who needs support?" requester type, which is a separate question about who reported the issue.

- **Assigned Department** is the department responsible for resolving the request. Operations requests also carry an **Assigned Sub-team**.
- **Reporting Department** is recorded automatically from the signed-in user's department.

When you log a request you assign it to any department, your own or another. The owning department then sees it.

### What each role sees and can do

- **A department member** sees requests their department owns plus requests their department raised, so both work sent to them and work they raised are visible. They can create requests, and edit, progress, close, or reassign only the requests their department owns. On requests owned by another department they have view-only access and can add a note.
- **IT has the global view.** Every IT account, and any account with the `admin` role, sees every request across the company. A **Department** filter in the sidebar scopes the whole dashboard, including KPIs, charts, exports, and the weekly comparison, to one department. A **Company-wide by department** table shows open, needs-attention, breach percentages, and average closure TAT for each department and Operations sub-team, so the weakest links are visible at a glance.
- **Admin powers are separate from the global view.** The global view is read access across all departments. Managing any department's requests and deleting are admin powers that come only from the `admin` role. So IT support (an IT member) sees everything but can edit only IT-owned requests and cannot delete, while an IT admin can manage and delete anything.

Legacy requests created before departments existed are routed to IT so nothing is hidden.

### User accounts

Accounts are named users with a hashed password, a department, an optional Operations sub-team, and a role of `member` or `admin`. Seed or update them from a CSV:

```bash
cp users_seed.example.csv users_seed.csv   # then edit with your real users
python scripts/seed_users.py users_seed.csv
```

The CSV columns are `username, display_name, department, subteam, role, temp_password`. Leave `temp_password` blank to have one generated and printed once. Every seeded account must change its password on first login. Passwords are stored only as salted PBKDF2 hashes, and `users_seed.csv` is git-ignored because it holds names and temporary passwords.

Login is required only once auth is configured, meaning at least one account exists or a bootstrap admin is set. Set `DASHBOARD_ADMIN_USER` and `DASHBOARD_ADMIN_PASSWORD` for a bootstrap admin that can sign in before any accounts are seeded and recover access if every account is locked out; it always has the IT global view. Run `alembic upgrade head` (or deploy with `AUTO_MIGRATE=true`) so the `users` table and the routing columns are created. The Google Sheets fallback keeps the earlier shared-password gate and treats its single user as an IT admin.

## SLA and turnaround time

| Milestone | Target from reporting | Recorded timestamp |
|---|---|---|
| First response | 30 minutes | `First Response At` |
| Diagnosis / understanding the problem | 2 hours | `Diagnosed At` |
| Closure | 48 hours | `Closed At` |

All three clocks start together at the actual reporting time; they are not sequential stages. **TAT is total elapsed time from reporting to closure.** A milestone completed exactly at its deadline is on time.

Choose **Reported at (Nairobi time)** when creating a request. For example, a
ticket received on 9 September at 9 PM can be entered the next day with the original
reporting timestamp. `Reported At` stores this time; `Created` separately records
when the ticket was entered in the dashboard. Both appear in request details and
exports. The activity history retains the time each dashboard action occurred.
Call, WhatsApp, SMS, Email, and Other channels are available.

SLA targets use elapsed time (24/7) from `Reported At`. Existing records without
that field fall back to `Created` until their reporting time is corrected in the
edit form. Corrections are logged in history and cannot be in the future, after
dashboard entry, or after a recorded response, diagnosis, or closure. First response and
diagnosis times can be recorded in Nairobi time when editing a request; moving
into diagnosis or a later working stage records diagnosis if it is missing.
Direct closure does not invent a response or diagnosis time. Closure records
`Closed At`; deployment does not stop the closure clock. Reopening clears the
closure timestamp and resumes the clock from the original reporting time.

Turnaround time is reported to closed. Averages and on-time percentages use
recorded milestones only; pending and missing records never imply 100% compliance.
Closed historical records with missing milestone times show as not recorded.
Existing saved timestamps are retained; previously inferred diagnosis timestamps
cannot be distinguished automatically from actual observations. The new targets
also apply to historical requests in filtered reports.

The SLA table distinguishes recorded on-time and late milestones, work still waiting within target, overdue milestones, and missing or invalid timestamps. Completed-late milestones remain visible in performance statistics but no longer require that milestone to be performed.

## Analytics and reports

- **Four overview cards:** open requests, requests needing attention, closed requests, and average closure TAT. Needs attention counts each open request once if it is overdue or unassigned.
- **SLA bar chart:** one bar per milestone showing on-time, late, waiting, overdue, and missing/invalid counts. Each bar evaluates the same requests against a different target.
- **Open/closed doughnut chart:** one count per request. Deployed requests remain open until Closed.
- **Attention list and ownership:** identify the responsible agent, missing assignments, and overdue actions. Expand **Open requests and owners** for the full filtered open workload.
- **Deadline countdowns:** the selected request shows time remaining or time overdue for each milestone, with warning colours near the deadline. Completed milestones show their recorded duration.
- **Filtered CSV:** follows status, priority, created month, assigned-agent, and search filters. Includes Reg No, milestone times, durations in hours, and SLA outcomes.
- **Weekly comparison and download:** expandable summary of logged and closed counts, each milestone's on-time percentage, and average closure TAT, with a CSV download.

Analytics, filtered exports, and selected-request deadline messages refresh every **10 minutes** while the page session is active. Refreshing those sections does not rerun the intake/edit forms. The analytics show their last refresh time in Nairobi time. Reload the page to refresh request-selector choices after another user creates a request.

The weekly comparison covers all requests independently of dashboard filters.
Logged counts use logging dates; closure counts and TAT use closure dates.
Each SLA percentage uses the corresponding milestone timestamps in that window.
Reopened requests are counted as closed only once they are closed again, using
their latest closure timestamp. Timer refreshes run while the dashboard session
is active; they do not send messages or run a background notification service.

## Local setup

1. Create a Python virtual environment.
2. Install packages with `pip install -r requirements.txt`.
3. Set `DATABASE_URL` to a PostgreSQL URL. If it is omitted, development uses the ignored local `reporting.db` SQLite file.
4. Run `alembic upgrade head`.
5. Run `streamlit run app.py`.

Use `.env.example` as a configuration reference; the application does not automatically load a `.env` file. Set environment variables in your shell or hosting configuration. Run `alembic upgrade head` after pulling changes so an existing database receives new fields, including Reg No.

### Google Sheets fallback

To temporarily use the old Google Sheets backend, set `USE_DATABASE=false`, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, and configure the service account. The tickets worksheet must use these columns in this exact order:

```text
Ticket ID, Summary, Status, Priority, Created, Diagnosed At, Resolved At, Updated At
```

The activity worksheet is created automatically if it does not exist.

Existing worksheets using the original eight ticket columns are extended automatically with the reporting fields. Existing data and column order are preserved. New deployments should use PostgreSQL.

## Deployment (Streamlit Community Cloud)

The app is hosted on [Streamlit Community Cloud](https://streamlit.io/cloud) and the
database on managed PostgreSQL (for example [Neon](https://neon.tech/)). The app
is stateless; all tickets, history, and user accounts live in PostgreSQL, so the
host and the database are independent.

1. In Streamlit Community Cloud, create an app from this repository, branch `main`, file `app.py`.
2. Open the app's **Settings → Secrets** and paste the template from `.streamlit/community-cloud.secrets.toml.example`.
   Set `DATABASE_URL` to your PostgreSQL connection string (Neon's direct URL, preserving its TLS options).
   Keep `USE_DATABASE = "true"`, `REQUIRE_POSTGRES = "true"`, and `AUTO_MIGRATE = "true"`.
3. Deploy. On start, `AUTO_MIGRATE` applies Alembic migrations (creating the `users` table and routing columns), then the app runs.
4. Seed accounts once the database is reachable: `python scripts/seed_users.py users_seed.csv` (see **Roles and departments**).

`AUTO_MIGRATE=true` is additive and safe on an existing database: it adds the new
columns and the `users` table and tags pre-existing requests as IT, without
rewriting or deleting ticket data.

### Migrating existing data off Render

If you are moving an existing Render-hosted database to Neon, follow
[Streamlit Community Cloud + Neon setup and data transfer](docs/streamlit-cloud.md).
The transfer tool copies `tickets` and `ticket_activity` and preserves IDs and all
timestamps; re-run `scripts/seed_users.py` against the new database afterwards to
recreate accounts. Keep the old database until you have verified the copy.

## Jira import

Open **Import and normalize Jira data**, upload the raw Jira CSV, inspect the preview, and then import. The importer supports Jira's repeated CSV headers, maps legacy statuses into the dashboard workflow, and generates a stable UUID from each Jira issue key. Uploading the same issues again will not duplicate them.

## Tests

Install development dependencies and run:

```text
pip install -r requirements-dev.txt
pytest
```

Business rules live under `reporting/`, separately from the Streamlit interface, so SLA, workflow, and import behavior can be tested without connecting to Google Sheets.

The suite also covers deadline boundaries, weekly period comparisons, ownership filters, one-click milestone updates, direct closure and reopening, activity history, preservation of legacy Solver IDs during migration, and the department roles model (password hashing, per-department visibility scoping, edit and delete permissions, per-department analytics, and the user account store). App tests use temporary SQLite databases; they do not write to production. The latest feature verification passed all 53 tests, including external-client intake with and without optional job details. App tests validate chart specifications without rendering charts to avoid local native-library restrictions.

## Branding

The logo is bundled at `assets/solvit-logo.jpg`, sourced unchanged from Solvit's official website. See [asset source details](assets/README.md). It is embedded locally, so displaying it does not require a request to the company website.

## Security

Never commit `.streamlit/secrets.toml` or raw Jira exports. Configure `DASHBOARD_PASSWORD_HASH` for the built-in access gate. For a larger team, replace the shared password with an identity provider and role-based permissions.

## Notifications

`SUPPORT_EMAIL` enables a prefilled email action and `SUPPORT_WHATSAPP` enables a prefilled WhatsApp action. These deliberately require a user to confirm sending. Automated alerts require a mail service and the WhatsApp Business Cloud API, including approved credentials and message templates.

## Production direction

PostgreSQL is the primary store. For this two-person internal tool, the password gate is a practical first deployment. Organization SSO, named users, backups, monitoring, and scheduled SLA alerts remain the next production hardening steps.

Reporting date and time start blank and must be selected before creating a request. Use the refresh buttons for immediate analytics or deadline updates between automatic refreshes. Saving a request also updates the dashboard.

New support requests do not ask for a requester name. Existing saved requester names remain available in historical records.
