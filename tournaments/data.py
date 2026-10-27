"""Учебные данные первого этапа. База и генерация сеток появятся позже."""

TEAMS = [
    {"name": "POLYTECH", "tag": "PT", "captain": "chefran", "players": "chefran · frost · nexx · pulse · echo", "color": "lime"},
    {"name": "NORTH SIDE", "tag": "NS", "captain": "voskov", "players": "voskov · north · zero · flash · storm", "color": "blue"},
    {"name": "RED PIXELS", "tag": "RP", "captain": "karelov", "players": "karelov · ruby · spark · shift · nova", "color": "coral"},
    {"name": "AFTERCLASS", "tag": "AC", "captain": "after", "players": "after · dusk · pixel · orbit · ghost", "color": "violet"},
]

TOURNAMENTS = [
    {"slug": "ignite-cup", "name": "IGNITE CUP", "subtitle": "Студенческий турнир по Counter-Strike 2", "game": "CS2", "game_label": "Counter-Strike 2", "date": "23 октября 2026", "short_date": "23 окт", "status": "live", "status_label": "Идёт турнир", "accent": "lime", "edition": "01", "description": "Четыре команды, два полуфинала и один кубок. Первый студенческий турнир IGNITE: следите за расписанием, результатами и продвижением команд к финалу."},
    {"slug": "campus-arena", "name": "CAMPUS ARENA", "subtitle": "Командное соревнование по Dota 2", "game": "DOTA2", "game_label": "Dota 2", "date": "30 октября 2026", "short_date": "30 окт", "status": "soon", "status_label": "Скоро", "accent": "violet", "edition": "02", "description": "Встреча студенческих команд на арене Dota 2. Состав участников и пары уже определены. Первые матчи начнутся 30 октября в 15:00."},
    {"slug": "first-strike", "name": "FIRST STRIKE", "subtitle": "Осенняя встреча команд по Valorant", "game": "VALORANT", "game_label": "Valorant", "date": "16 октября 2026", "short_date": "16 окт", "status": "finished", "status_label": "Завершён", "accent": "coral", "edition": "03", "description": "Первый осенний турнир по Valorant завершён. Здесь сохранены участники, расписание и результаты всех встреч. Победитель — команда POLYTECH."},
]


def matches_for(tournament):
    """Готовые примеры матчей, а не алгоритм проведения турнира."""
    status = tournament["status"]
    played = status != "soon"
    return [
        {"round": "Полуфинал 1", "time": "15:00", "a": TEAMS[0], "b": TEAMS[1], "score_a": "2" if played else "—", "score_b": "0" if played else "—", "status": "Завершён" if played else "Запланирован", "winner": TEAMS[0]["name"] if played else ""},
        {"round": "Полуфинал 2", "time": "16:00", "a": TEAMS[2], "b": TEAMS[3], "score_a": "2" if played else "—", "score_b": "1" if played else "—", "status": "Завершён" if played else "Запланирован", "winner": TEAMS[2]["name"] if played else ""},
        {"round": "Финал", "time": "18:00", "a": TEAMS[0] if played else None, "b": TEAMS[2] if played else None, "score_a": "2" if status == "finished" else "1" if status == "live" else "—", "score_b": "1" if played else "—", "status": "Завершён" if status == "finished" else "Идёт матч" if status == "live" else "Запланирован", "winner": TEAMS[0]["name"] if status == "finished" else ""},
    ]
