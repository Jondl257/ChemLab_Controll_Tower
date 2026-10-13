"""Local account authentication and a CLI-only bootstrap for user provisioning."""
import argparse
from getpass import getpass

from werkzeug.security import check_password_hash, generate_password_hash

from data.repository import Repository


def authenticate(repo: Repository, username: str, password: str) -> dict | None:
    user = repo.local_user(username)
    if user is None or not user["active"]:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return user


def add_user(
    repo: Repository,
    username: str,
    password: str,
    role: str,
    employee_id: str | None,
    created_by: str = "local-provisioning",
) -> None:
    if len(password) < 12:
        raise ValueError("Das lokale Kennwort muss mindestens 12 Zeichen lang sein.")
    password_hash = generate_password_hash(password)
    repo.add_local_user(username, password_hash, role, employee_id, created_by)


def reset_password(
    repo: Repository, username: str, password: str, actor: str
) -> None:
    if len(password) < 12:
        raise ValueError("Das lokale Kennwort muss mindestens 12 Zeichen lang sein.")
    repo.reset_local_user_password(
        username, generate_password_hash(password), actor
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Lokales ChemLab-Benutzerkonto anlegen.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=("Laborant", "Laborleitung", "Administrator"))
    parser.add_argument("--employee-id", help="Erforderlich für Laborant/Laborleitung, z. B. E-01.")
    args = parser.parse_args()
    password = getpass("Kennwort (mindestens 12 Zeichen): ")
    confirmation = getpass("Kennwort wiederholen: ")
    if password != confirmation:
        parser.error("Die Kennwörter stimmen nicht überein.")
    repository = Repository()
    try:
        add_user(repository, args.username, password, args.role, args.employee_id)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Lokales Konto '{args.username}' wurde angelegt.")


if __name__ == "__main__":
    main()
