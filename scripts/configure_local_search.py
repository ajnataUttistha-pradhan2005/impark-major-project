"""Create missing local search settings without displaying or overwriting credentials."""

import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key


def main() -> None:
    path = Path(".env")
    if not path.exists():
        path.write_text(Path(".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    current = dotenv_values(path)
    user = current.get("POSTGRES_USER") or "impark"
    database = current.get("POSTGRES_DB") or "impark"
    password = current.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(30)
    port = current.get("POSTGRES_PORT") or "15432"
    from urllib.parse import quote

    values = {
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": database,
        "POSTGRES_PORT": port,
        "DATABASE_URL": (
            f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@localhost:{port}/{quote(database, safe='')}"
        ),
        "QDRANT_URL": "http://localhost:6333",
    }
    for key, value in values.items():
        if not current.get(key):
            set_key(path, key, value)
    print("Missing local connection settings written to ignored .env. No secrets displayed.")
    print("Run migrations and sync, then enable TEXT_SEARCH_ENABLED in .env.")


if __name__ == "__main__":
    main()
