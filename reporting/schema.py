CORE_HEADERS = [
    "Ticket ID",
    "Summary",
    "Status",
    "Priority",
    "Created",
    "Diagnosed At",
    "Resolved At",
    "Updated At",
]

EXTENDED_HEADERS = [
    "External Key",
    "Description",
    "Severity",
    "Category",
    "Subcategory",
    "Assignee",
    "Reporter",
    "Team",
    "Channel",
    "Customer Email",
    "Customer WhatsApp",
    "Escalation Owner",
    "First Response At",
    "Closed At",
    "Reopened Count",
    "Resolution Category",
    "Support Request Number",
    "Requester Type",
    "Requester Name",
    "Job Request ID",
    "Solver ID",
    "Office Department",
    "Received By",
    "Call Outcome",
    "Callback Required",
    "Callback Deadline",
    "Callback Completed At",
    "Resolution Summary",
    "Reg No",
    "Reported At",
]

TICKET_HEADERS = CORE_HEADERS + EXTENDED_HEADERS

ACTIVITY_HEADERS = [
    "Activity ID",
    "Ticket ID",
    "Action",
    "Field",
    "Old Value",
    "New Value",
    "Note",
    "Timestamp",
    "Actor",
]

PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"]
STATUSES = ["to do", "diagnosed", "in progress", "qa testing", "deployed", "closed"]
