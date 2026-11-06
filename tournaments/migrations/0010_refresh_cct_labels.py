from django.db import migrations


def refresh_cct_labels(apps, schema_editor):
    alias = schema_editor.connection.alias
    users = apps.get_model("tournaments", "User").objects.using(alias)
    tournaments = apps.get_model("tournaments", "Tournament").objects.using(alias)
    curator = users.filter(email="curator@archive.ignite.invalid").first()
    if curator is None:
        return

    if curator.nickname == "Архив CCT · IGNITE" and not users.filter(nickname="IGNITE · CCT").exists():
        users.filter(pk=curator.pk, nickname=curator.nickname).update(nickname="IGNITE · CCT")

    replacements = {
        "subtitle": (
            ("Архив 2024 · плей-офф", "2024 · плей-офф"),
            ("Архив 2025 · плей-офф", "2025 · плей-офф"),
        ),
        "description": (
            ("Даты и результаты взяты из публичного архива; ", "Даты и результаты сверены с источниками. "),
        ),
        "rules": (
            ("Профиль организатора — куратор архива IGNITE; организатор соревнования — CCT.",
             "Организатор соревнования — CCT."),
        ),
    }
    for tournament in tournaments.filter(organizer=curator, slug__startswith="cct-s2-europe-").exclude(source_url=""):
        for field, pairs in replacements.items():
            original = getattr(tournament, field)
            updated = original
            for old, new in pairs:
                updated = updated.replace(old, new)
            if updated != original:
                tournaments.filter(pk=tournament.pk, **{field: original}).update(**{field: updated})


class Migration(migrations.Migration):
    dependencies = [("tournaments", "0009_stream_embed_permission")]
    operations = [migrations.RunPython(refresh_cct_labels, migrations.RunPython.noop)]
