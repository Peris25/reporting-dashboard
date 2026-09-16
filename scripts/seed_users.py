"""Seed or update dashboard user accounts from a CSV.

Reads a CSV of users and upserts them into the database referenced by
DATABASE_URL (or the local SQLite development database). Passwords are stored
only as salted PBKDF2 hashes. Every account created here is flagged to require a
password change on first login.

CSV columns (a header row is required):

    username, display_name, department, subteam, role, temp_password

- subteam is optional and only meaningful for Operations.
- role is "member" or "admin". Blank defaults to member. IT always has the
  global view regardless of role.
- temp_password is optional. Leave it blank to have one generated and printed.

Usage:
    python scripts/seed_users.py users_seed.csv
    python scripts/seed_users.py users_seed.csv --database-url postgresql://...
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reporting.access import generate_temp_password, hash_password
from reporting.database import create_user_store
from reporting.departments import DEPARTMENTS, normalize_department, normalize_subteam


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Seed dashboard user accounts from a CSV.")
    parser.add_argument("csv_path", help="Path to the users CSV.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Override DATABASE_URL.")
    args = parser.parse_args(argv)

    store = create_user_store(args.database_url or None)
    generated = []
    upserted = 0
    for row in load_rows(args.csv_path):
        username = (row.get("username") or "").strip()
        if not username:
            continue
        department = normalize_department(row.get("department"))
        if not department:
            print(f"Skipping {username}: unknown department {row.get('department')!r}. Use one of {DEPARTMENTS}.")
            continue
        subteam = normalize_subteam(department, row.get("subteam"))
        role = (row.get("role") or "member").strip().lower()
        role = role if role in {"member", "admin"} else "member"
        temp_password = (row.get("temp_password") or "").strip()
        if not temp_password:
            temp_password = generate_temp_password()
            generated.append((username, temp_password))
        store.upsert(
            username=username,
            display_name=(row.get("display_name") or username).strip(),
            password_hash=hash_password(temp_password),
            department=department,
            subteam=subteam,
            role=role,
            must_change_password=True,
            active=True,
        )
        upserted += 1

    print(f"Upserted {upserted} account(s).")
    if generated:
        print("Generated temporary passwords (share securely, they are shown only once):")
        for username, password in generated:
            print(f"  {username}: {password}")


if __name__ == "__main__":
    main()
