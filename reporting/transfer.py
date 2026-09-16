"""Copy dashboard records into an empty database without changing the source."""
import argparse
from getpass import getpass

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text

from reporting.bootstrap import initialize_database
from reporting.database import Base, database_url

TABLES = ("tickets", "ticket_activity")


def snapshot(source):
    with source.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
        with connection.begin():
            result = {}
            for name in TABLES:
                table = Table(name, MetaData(), autoload_with=connection)
                result[name] = [dict(row) for row in connection.execute(select(table)).mappings()]
            return result


def copy_records(records, target):
    """Insert and verify both tables in one transaction; refuse existing data."""
    with target.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("LOCK TABLE tickets, ticket_activity IN EXCLUSIVE MODE"))
        for name in TABLES:
            table = Base.metadata.tables[name]
            if connection.execute(select(table).limit(1)).first() is not None:
                raise ValueError("Destination is not empty; no records were copied.")
        for name in TABLES:
            table = Base.metadata.tables[name]
            rows = records[name]
            if any(set(row) - set(table.columns.keys()) for row in rows):
                raise ValueError("Source has unsupported columns; refusing to discard data.")
            if rows:
                connection.execute(table.insert(), rows)
            key = list(table.primary_key.columns)[0].name
            actual = {row[key]: dict(row) for row in connection.execute(select(table)).mappings()}
            if len(actual) != len(rows) or any(
                any(actual.get(row[key], {}).get(field) != value for field, value in row.items()) for row in rows
            ):
                raise ValueError("Verification failed; destination inserts rolled back.")
    return {name: len(records[name]) for name in TABLES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy", action="store_true", help="Copy into an empty target; otherwise preview only.")
    args = parser.parse_args()
    source_url = getpass("Render EXTERNAL database URL (hidden): ").strip()
    target_url = getpass("New DIRECT PostgreSQL URL (hidden): ").strip()
    source = target = None
    try:
        if not source_url or not target_url or database_url(source_url) == database_url(target_url):
            raise ValueError("Provide two different nonempty connection strings.")
        source = create_engine(database_url(source_url), pool_pre_ping=True, hide_parameters=True)
        target = create_engine(database_url(target_url), pool_pre_ping=True, hide_parameters=True)
        if source.dialect.name != "postgresql" or target.dialect.name != "postgresql":
            raise ValueError("This transfer requires PostgreSQL connections.")
        records = snapshot(source)
        print("Source counts:", {name: len(records[name]) for name in TABLES})
        with target.connect() as connection:
            existing = inspect(connection).get_table_names()
            for name in TABLES:
                if name in existing:
                    table = Table(name, MetaData(), autoload_with=connection)
                    if connection.execute(select(table).limit(1)).first() is not None:
                        raise ValueError("Destination is not empty; use a new empty database.")
        if not args.copy:
            print("Preview complete. Nothing changed. Pause ticket editing on both apps, then rerun with --copy.")
            return
        initialize_database(target_url)
        counts = copy_records(records, target)
        print("Copied and verified:", counts)
        print("The Render source was not changed. Verify the Streamlit app before retiring Render.")
    except ValueError as error:
        # Only print our controlled validation messages; database exceptions can contain credentials or data.
        print("Transfer stopped:", str(error) if str(error).startswith(("Provide", "This transfer", "Destination", "Source has", "Verification")) else "Check the connection strings.")
        raise SystemExit(1) from None
    except Exception as error:
        print(f"Transfer stopped ({type(error).__name__}). Check database access and schema. No connection strings are printed.")
        raise SystemExit(1) from None
    finally:
        if source is not None:
            source.dispose()
        if target is not None:
            target.dispose()


if __name__ == "__main__":
    main()
