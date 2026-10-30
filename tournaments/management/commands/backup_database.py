import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Создать резервную копию PostgreSQL без изменения базы."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Новый файл .dump; существующие файлы не перезаписываются.")

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        if database["ENGINE"] != "django.db.backends.postgresql":
            raise CommandError("Команда предназначена для PostgreSQL.")
        binary = shutil.which("pg_dump")
        if not binary and os.name == "nt":
            candidates = sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin/pg_dump.exe"), reverse=True)
            binary = str(candidates[0]) if candidates else None
        if not binary:
            raise CommandError("pg_dump не найден. Укажите каталог bin PostgreSQL в PATH терминала.")
        default_name = f"ignite-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}.dump"
        output = Path(options["output"]) if options["output"] else settings.BASE_DIR / "work" / "backups" / default_name
        if output.exists():
            raise CommandError("Файл уже существует. Выберите другое имя.")
        output.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["PGPASSWORD"] = database.get("PASSWORD", "")
        command = [binary, "--format=custom", "--no-owner", "--file", str(output),
                   "--host", database["HOST"], "--port", str(database["PORT"]),
                   "--username", database["USER"], database["NAME"]]
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        if result.returncode:
            raise CommandError("Резервная копия не создана. Проверьте доступ к PostgreSQL и версию pg_dump.")
        self.stdout.write(self.style.SUCCESS(f"Резервная копия: {output.resolve()}"))
