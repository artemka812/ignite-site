"""Локальный мастер: пароль postgres вводится только в терминале."""
import configparser
import getpass
import secrets
from pathlib import Path

import psycopg
from psycopg import sql


def main():
    target = Path(__file__).with_name("config.local.ini")
    if target.exists():
        print("config.local.ini уже существует. Мастер не перезаписывает настройки.")
        return
    print("IGNITE: создание новых баз ignite_site и test_ignite_site.")
    print("Существующие базы, роли и пароли не изменяются.")
    host = input("Хост [127.0.0.1]: ").strip() or "127.0.0.1"
    port = input("Порт [5432]: ").strip() or "5432"
    admin = input("Пользователь PostgreSQL [postgres]: ").strip() or "postgres"
    password = getpass.getpass("Пароль PostgreSQL (ввод скрыт): ")
    role = "ignite_site_app"
    app_password = secrets.token_urlsafe(32)
    with psycopg.connect(host=host, port=port, dbname="postgres", user=admin,
                         password=password, connect_timeout=10, autocommit=True) as connection:
        existing_role = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        existing_databases = connection.execute(
            "SELECT datname FROM pg_database WHERE datname IN (%s, %s)",
            ("ignite_site", "test_ignite_site"),
        ).fetchall()
        if existing_role or existing_databases:
            print("Найдены одноимённые объекты. Ничего не изменено: сообщи об этом в чат.")
            return
        connection.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(app_password)))
        for name in ("ignite_site", "test_ignite_site"):
            connection.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(name), sql.Identifier(role)))
    settings = configparser.ConfigParser(interpolation=None)
    settings["database"] = {
        "name": "ignite_site", "user": role, "password": app_password,
        "host": host, "port": port,
    }
    settings["django"] = {"secret_key": secrets.token_urlsafe(48)}
    with target.open("x", encoding="utf-8") as stream:
        settings.write(stream)
    print("Готово. Настройки записаны в config.local.ini, который исключён из Git.")
    print("Пароль postgres не сохранялся. Можно вернуться в чат: напиши 'подключено'.")


if __name__ == "__main__":
    try:
        main()
    except (psycopg.Error, OSError, ValueError) as error:
        # Не печатаем строки подключения и SQL с паролями.
        print("Настройка не завершена:", type(error).__name__)
        print("Проверь имя пользователя, пароль и доступность PostgreSQL.")
    input("Нажми Enter, чтобы закрыть окно...")
