def request_history(activity_df, ticket_id):
    """Present stored audit events as readable history for one request."""
    records = activity_df.loc[activity_df["Ticket ID"] == ticket_id].to_dict("records")
    intake = next((row for row in records if row["Action"] == "intake_recorded"), None)
    has_creation = any(row["Action"] == "support_request_created" for row in records)
    entries = []
    for row in records:
        action = row["Action"]
        if action == "intake_recorded" and has_creation:
            continue
        old, new, note = (str(row.get(key) or "").strip() for key in ("Old Value", "New Value", "Note"))
        field = row.get("Field", "")
        details = []
        if action == "support_request_created":
            title = "Request created"
            if new:
                details.append(f"Status: {new.capitalize()}")
            if intake and intake.get("Note"):
                details.append(f"Received from: {intake['Note']}")
        elif action == "status_changed":
            title = "Status changed"
            details.append(f"{old.capitalize()} → {new.capitalize()}")
        elif action == "field_edited":
            title = "Resolution updated" if field == "Resolution Summary" else f"{field} updated"
            details.append(new or "Value cleared")
            if old:
                details.append(f"Previously: {old}")
        else:
            title = {"intake_recorded": "Request details recorded", "ticket_deleted": "Request deleted"}.get(
                action, action.replace("_", " ").capitalize()
            )
            if new:
                details.append(new)
        if note and note != new:
            details.append(note)
        entries.append({"timestamp": row.get("Timestamp", ""), "title": title, "details": details})
    return sorted(entries, key=lambda entry: str(entry["timestamp"]), reverse=True)
