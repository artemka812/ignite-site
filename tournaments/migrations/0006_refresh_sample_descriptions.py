from django.db import migrations


REPLACEMENTS = [
    ('ignite-cup', 'subtitle', 'Студенческий турнир по Counter-Strike 2', 'Турнир по Counter-Strike 2'),
    ('ignite-cup', 'description',
     'Четыре команды, два полуфинала и один кубок. Первый студенческий турнир IGNITE: следите за расписанием, результатами и продвижением команд к финалу.',
     'Четыре команды, два полуфинала и один кубок. Следите за расписанием, результатами и продвижением команд к финалу.'),
    ('campus-arena', 'description',
     'Встреча студенческих команд на арене Dota 2. Состав участников и пары уже определены. Первые матчи начнутся 30 октября в 15:00.',
     'Встреча команд на арене Dota 2. Состав участников и пары уже определены. Первые матчи начнутся 30 октября в 15:00.'),
]


def refresh(apps, schema_editor):
    tournament = apps.get_model('tournaments', 'Tournament')
    for slug, field, old, new in REPLACEMENTS:
        tournament.objects.using(schema_editor.connection.alias).filter(slug=slug, **{field: old}).update(**{field: new})


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0005_matchconfirmation')]
    operations = [migrations.RunPython(refresh, migrations.RunPython.noop)]
