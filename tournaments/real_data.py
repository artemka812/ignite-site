"""Verified March 2025 CCT playoff archive; rosters are historical, not current.

Every match links to its HLTV record. Only the single-elimination playoffs
are imported: the preceding Swiss stage is deliberately outside this dataset.
"""

ROSTERS = {
    "BC.Game": "nawwk,CYPHER,pr1metapz,jkaem,nexa",
    "fnatic": "Burmylov,MATYS,KRIMZ,blameF,fEAR",
    "Nexus": "ADRON,XELLOW,ragga,BTN,s0und",
    "NAVI Junior": "cmtry,dem0n,dziugss,Krabeni,makazze",
    "Nemiga": "Xant3r,1eeR,riskyb0b,zweih,khaN",
    "Metizport": "hampus,L00m1,Plopski,adamb,isak",
    "Passion UA": "Kvem,zeRRoFIX,Topa,jambo,jackasmo",
    "9 Pandas": "Krad,shalfey,d1Ledez,r3salt,KaiR0N-",
    "Monte": "leen,hades,Gizmy,ryu,DemQQ",
    "500": "oxygeN,CeRq,Rainwaker,SHiPZ,SPELLAN",
    "ECLOT": "forsyy,The eLiVe,nbqq,M1key,Dytor",
    "GUN5": "fineshine52,Lack1,Sdaim,xiELO,SELLTER",
    "GTZ": "rafaxF,Linko,NOPEEj,snapy,Sprayy",
    "BETBOOM": "Ax1Le,Boombl4,zorte,S1ren,Magnojez",
    "BIG": "hyped,kyuubii,Krimbo,tabseN,JDC",
    "ENCE": "xKacpersky,sdy,Neityu,gla1ve,podi",
    "OG": "nicoodoz,spooke,F1KU,Chr1zN,Buzz",
    "Betclic": "hfah,hypex,Demho,jcobbb,Prism",
    "PARIVISION": "BELCHONOKK,Jame,Qikert,nota,TRAVIS",
    "Zero Tenacity": "simke,aVN,brutmonster,nEMANHA,Cjoffo",
    "ECSTATIC": "Kristou,Anlelele,nut nut,TMB,sirah",
}
ROSTERS = {team: names.split(",") for team, names in ROSTERS.items()}

# Roles for the archived lineups, not the players' current teams.
# BC.Game: club announcement and HLTV's roster reporting.
# https://bcgameesports.com/welcome-nawwk
# https://esports.ru/counter-strike-2/news/cypher-i-nexa-prisoedinilis-k-sostavu-bc-game-esports/
# https://www.hltv.org/news/42839/bcgame-bench-pr1metapz
# fnatic: https://fnatic.com/talent/MATYS
# https://www.hltv.org/news/38987/fnatic-sign-blamef
# https://www.reddit.com/r/fnatic/comments/1hya1l4
PLAYER_POSITIONS = {
    "nawwk": "Снайпер (AWPer)",
    "nexa": "Игровой лидер (IGL)",
    "CYPHER": "Рифлер",
    "pr1metapz": "Рифлер",
    "fEAR": "Игровой лидер (IGL)",
    "Burmylov": "Снайпер (AWPer)",
    "MATYS": "Рифлер",
    "blameF": "Рифлер",
    "KRIMZ": "Рифлер (опорник)",
    "BTN": "Игровой лидер (IGL)",
    "XELLOW": "Снайпер (AWPer)",
    "hades": "Снайпер (AWPer)",
    "forsyy": "Снайпер (AWPer)",
    "podi": "Снайпер (AWPer)",
    "gla1ve": "Игровой лидер (IGL)",
    "hyped": "Снайпер (AWPer)",
    "tabseN": "Игровой лидер (IGL)",
    "kyuubii": "Рифлер",
    "jambo": "Снайпер (AWPer)",
    "Topa": "Игровой лидер (IGL)",
    "nicoodoz": "Снайпер (AWPer)",
    "Chr1zN": "Игровой лидер (IGL)",
    "Jame": "Снайпер (AWPer)",
    "Qikert": "Игровой лидер (IGL)",
    "L00m1": "Снайпер (AWPer)",
    "hampus": "Игровой лидер (IGL)",
    "hypex": "Снайпер (AWPer)",
    "Prism": "Игровой лидер (IGL)",
    "zorte": "Снайпер (AWPer)",
    "khaN": "Снайпер (AWPer)",
}

# round, position, HLTV match id, March day, team A, team B, maps A, maps B
# Positions follow the real bracket, rather than chronological match order.
PLAYOFFS = {
    19: [
        (1, 1, 2380171, 9, "Nexus", "Monte", 2, 0),
        (1, 2, 2380164, 8, "ENCE", "NAVI Junior", 1, 2),
        (1, 3, 2380166, 8, "BETBOOM", "9 Pandas", 1, 2),
        (1, 4, 2380169, 9, "ECLOT", "fnatic", 1, 2),
        (1, 5, 2380165, 8, "BIG", "BC.Game", 0, 2),
        (1, 6, 2380170, 9, "Passion UA", "500", 2, 1),
        (1, 7, 2380167, 8, "Nemiga", "GTZ", 2, 0),
        (1, 8, 2380168, 9, "Metizport", "GUN5", 2, 1),
        (2, 1, 2380175, 10, "Nexus", "NAVI Junior", 2, 0),
        (2, 2, 2380172, 10, "9 Pandas", "fnatic", 1, 2),
        (2, 3, 2380173, 10, "BC.Game", "Passion UA", 2, 0),
        (2, 4, 2380174, 10, "Nemiga", "Metizport", 1, 2),
        (3, 1, 2380177, 11, "fnatic", "Nexus", 2, 1),
        (3, 2, 2380176, 11, "BC.Game", "Metizport", 2, 1),
        (4, 1, 2380178, 11, "BC.Game", "fnatic", 2, 0),
    ],
    20: [
        (1, 1, 2380550, 14, "Nemiga", "OG", 0, 2),
        (1, 2, 2380548, 14, "Metizport", "Betclic", 1, 2),
        (1, 3, 2380547, 14, "BIG", "PARIVISION", 1, 2),
        (1, 4, 2380549, 14, "Passion UA", "Zero Tenacity", 1, 2),
        (1, 5, 2380546, 13, "Nexus", "9 Pandas", 0, 2),
        (1, 6, 2380543, 13, "ENCE", "ECSTATIC", 2, 1),
        (1, 7, 2380544, 13, "BETBOOM", "NAVI Junior", 0, 2),
        (1, 8, 2380545, 13, "ECLOT", "500", 0, 2),
        (2, 1, 2380554, 15, "OG", "Betclic", 2, 0),
        (2, 2, 2380553, 15, "PARIVISION", "Zero Tenacity", 2, 0),
        (2, 3, 2380552, 15, "9 Pandas", "ENCE", 0, 2),
        (2, 4, 2380551, 15, "NAVI Junior", "500", 0, 2),
        (3, 1, 2380556, 16, "PARIVISION", "OG", 1, 2),
        (3, 2, 2380555, 16, "ENCE", "500", 0, 2),
        (4, 1, 2380557, 16, "500", "OG", 0, 2),
    ],
}


def match_roster(series, match_id, team):
    # POP0V stood in for SHiPZ only in this quarterfinal.
    if series == 20 and match_id == 2380551 and team == "500":
        return ["oxygeN", "CeRq", "Rainwaker", "POP0V", "SPELLAN"]
    return ROSTERS[team]


def match_source(match_id):
    for series, rows in PLAYOFFS.items():
        for row in rows:
            if row[2] == match_id:
                names = [name.lower().replace(".", "").replace(" ", "-") for name in row[4:6]]
                return f"https://www.hltv.org/matches/{match_id}/{names[0]}-vs-{names[1]}-cct-season-2-europe-series-{series}"
    raise ValueError(f"Unknown archive match: {match_id}")


EVENTS = {
    19: ("2025-02-26", "2025-03-11", "https://www.hltv.org/events/8388/cct-season-2-europe-series-19"),
    20: ("2025-03-03", "2025-03-16", "https://www.hltv.org/events/8398/cct-season-2-europe-series-20"),
}
