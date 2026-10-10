"""
One-time helper: creates the PostgreSQL user + database and writes your .env file.

    python scripts/setup_env.py

It asks for the password of the PostgreSQL "postgres" admin user (the one you chose when you
installed PostgreSQL). Nothing is sent anywhere; it connects to your own PostgreSQL on localhost.

Non-interactive use:
    python scripts/setup_env.py --admin-password XXXX --db-password YYYY
"""
import argparse
import getpass
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def manual_instructions(db, user, password):
    print(
        "\nCould not create the database automatically. Do it manually:\n"
        "  1. Open 'SQL Shell (psql)' from the Start menu and log in as postgres.\n"
        "  2. Run these three lines:\n\n"
        f"     CREATE USER {user} WITH PASSWORD '{password}';\n"
        f"     CREATE DATABASE {db} OWNER {user};\n"
        f"     ALTER USER {user} CREATEDB;\n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", default="5432")
    ap.add_argument("--admin-user", default="postgres")
    ap.add_argument("--admin-password")
    ap.add_argument("--db-name", default="localbiz_db")
    ap.add_argument("--db-user", default="localbiz_user")
    ap.add_argument("--db-password")
    ap.add_argument("--force", action="store_true", help="overwrite an existing .env")
    args = ap.parse_args()

    if ENV_FILE.exists() and not args.force:
        print(f"{ENV_FILE} already exists. Re-run with --force to replace it.")
        return 0

    db_password = args.db_password or secrets.token_urlsafe(16)
    admin_password = args.admin_password
    if admin_password is None:
        admin_password = getpass.getpass(f"Password of the PostgreSQL '{args.admin_user}' user (typed text is hidden): ")

    created = False
    try:
        import psycopg
        from psycopg import sql

        with psycopg.connect(host=args.host, port=args.port, user=args.admin_user, password=admin_password,
                             dbname="postgres", autocommit=True, connect_timeout=5) as conn:
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (args.db_user,)).fetchone()
            if exists:
                conn.execute(sql.SQL("ALTER USER {} WITH PASSWORD {} CREATEDB").format(sql.Identifier(args.db_user), sql.Literal(db_password)))
            else:
                conn.execute(sql.SQL("CREATE USER {} WITH PASSWORD {} CREATEDB").format(sql.Identifier(args.db_user), sql.Literal(db_password)))
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (args.db_name,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(args.db_name), sql.Identifier(args.db_user)))
        created = True
        print(f"PostgreSQL user '{args.db_user}' and database '{args.db_name}' are ready.")
    except ImportError:
        print("psycopg is not installed. Run:  pip install -r requirements.txt   and try again.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"PostgreSQL connection failed: {exc}")
        manual_instructions(args.db_name, args.db_user, db_password)

    ENV_FILE.write_text(
        f"SECRET_KEY={secrets.token_urlsafe(50)}\n"
        f"DB_NAME={args.db_name}\nDB_USER={args.db_user}\nDB_PASSWORD={db_password}\n"
        f"DB_HOST={args.host}\nDB_PORT={args.port}\n",
        encoding="utf-8",
    )
    print(f"Wrote {ENV_FILE}  (keep this file private; it is already in .gitignore)")
    if created:
        print("\nNext:  python manage.py migrate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
