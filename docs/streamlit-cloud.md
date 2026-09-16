# Move from Render to Streamlit Community Cloud and Neon

Streamlit hosts the app. Neon hosts PostgreSQL. The GitHub repository stays at
`Parkire-Solvit/reporting-dashboard`. Existing tickets and history remain on
Render until the copy below is completed and verified.

## 1. Create the new database

Create a project at https://console.neon.tech/ and open **Connect**. Copy the
**direct** PostgreSQL connection string, preserving its TLS options. Use a new,
empty database for the transfer. Keep connection strings private; do not put
them in GitHub, screenshots, or chat.

## 2. Prepare the Streamlit app

Use repository `Parkire-Solvit/reporting-dashboard`, branch `main`, file `app.py`.
In Streamlit's app settings, open **Secrets** and paste the template from
`.streamlit/community-cloud.secrets.toml.example`. Replace `DATABASE_URL` with
the Neon direct URL and `DASHBOARD_PASSWORD_HASH` with your existing hash.

- `AUTO_MIGRATE = "true"` applies schema migrations at app initialization.
- `REQUIRE_POSTGRES = "true"` stops the app if PostgreSQL is not configured,
  avoiding accidental use of the local SQLite fallback.
- `USE_DATABASE = "true"` selects PostgreSQL instead of Google Sheets.

The new database can be initialized by the app or transfer tool. Do not create
test tickets in it before transfer: the copy intentionally refuses nonempty
destination tables. No Render-specific startup command is needed on Streamlit.

## 3. Transfer existing requests and activity history

Temporarily permit this computer's public IP in the Render database's external
access settings. Get the **external** Render database connection string and use
TLS. The internal Render address cannot be reached from this computer.

From the repository root, with dependencies installed, preview:

```text
python -m reporting.transfer
```

The tool asks for both connection strings using hidden input. Preview reads
the source and checks the target without creating or copying anything.

Pause ticket editing on both apps during the final transfer. Then run:

```text
python -m reporting.transfer --copy
```

This creates/upgrades the target schema, copies both `tickets` and
`ticket_activity`, and verifies all copied field values before committing.
Existing IDs, reporting times, response/diagnosis/closure times, registrations,
and history are retained. Source records are read only. Existing target data
causes refusal; a failed insert or verification rolls back both target tables.
Empty schema tables may remain after a failed attempt.

This app-specific tool copies the two dashboard tables, not PostgreSQL users,
roles, or unrelated tables. It loads those records into memory and is intended
for this small dashboard. Larger databases should use a PostgreSQL-native
dump/restore workflow. Changes made on Render after the snapshot are not copied.

## 4. Verify and switch over

Confirm the copied counts, open several old tickets and their histories, then
create and update a request on Streamlit. Check that reporting times, SLA
calculations, charts, and exports are correct. Direct the team to the new URL.

Only after verification and a retained backup should you retire the Render web
service and database. Neither the app nor transfer tool deletes Render resources.
Streamlit plus Neon then operates independently of Render. Keep Neon database
backups configured according to your retention needs.

## References

- [Streamlit deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [Streamlit persistent storage guidance](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data)
- [Neon connections](https://neon.com/docs/connect/connect-from-any-app)
- [Render external database connections](https://render.com/docs/postgresql-creating-connecting)
