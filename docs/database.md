# Структура базы IGNITE

Этап 30.10.2026. База PostgreSQL, модели Django в `tournaments/models.py`.
Основа — восемь сущностей из ТЗ и ранее подготовленной диаграммы классов.
UML-диаграмма описывает полную систему; на этом этапе реализованы данные и админка, а не все будущие методы.

```mermaid
erDiagram
    User ||--o{ Team : captain
    User ||--o{ TeamMember : player
    Team ||--o{ TeamMember : composition
    User ||--o{ Tournament : organizer
    Team ||--o{ TournamentTeam : applications
    Tournament ||--o{ TournamentTeam : participants
    Tournament ||--o{ Match : matches
    Team o|--o{ Match : team_a
    Team o|--o{ Match : team_b
    Match o|--o{ Match : next_match
    Match ||--o{ Stream : streams
    Match ||--o{ MatchResultLog : history
    User ||--o{ MatchResultLog : changed_by

    User {
        bigint id PK
        string email UK
        string password_hash
        string nickname UK
        string role
        string game_id
        string position
        string avatar_url
        bool is_staff
        bool is_superuser
    }
    Team {
        bigint id PK
        string name UK
        string tag
        bigint captain_id FK
        string logo_url
        string contacts
        string color
    }
    TeamMember {
        bigint id PK
        bigint player_id FK
        bigint team_id FK
        string status
        datetime joined_at
        datetime left_at
    }
    Tournament {
        bigint id PK
        string name
        string slug UK
        string subtitle
        text description
        bigint organizer_id FK
        string game
        string format
        datetime starts_at
        datetime ends_at
        int team_limit
        int team_size
        text rules
        string status
        string accent
        int edition
    }
    TournamentTeam {
        bigint id PK
        bigint tournament_id FK
        bigint team_id FK
        string status
        int seed
        datetime applied_at
    }
    Match {
        bigint id PK
        bigint tournament_id FK
        bigint team_a_id FK
        bigint team_b_id FK
        int round
        int position
        int best_of
        datetime scheduled_at
        int score_a
        int score_b
        string status
        bigint next_match_id FK
        string next_slot
    }
    Stream {
        bigint id PK
        bigint match_id FK
        string platform
        string url
        string status
    }
    MatchResultLog {
        bigint id PK
        bigint match_id FK
        bigint changed_by_id FK
        int old_score_a
        int old_score_b
        int new_score_a
        int new_score_b
        datetime changed_at
    }
```

`PK` — идентификатор, `FK` — связь, `UK` — уникальное поле. `0..1` — необязательная связь, `0..*` — любое количество записей.
В модели Django хеш пароля хранится в стандартном поле `password`, аватар в `avatar`, логотип в `logo`. Названия на схеме поясняют тип содержимого.

## Что проверяется

- Email уникален без учёта регистра. Вход в админку выполняется по email.
- Для игрока и команды создаётся одна запись TeamMember, в которой меняется состояние.
- Для команды и турнира создаётся одна заявка. Одобренные номера посева не повторяются.
- Конец турнира не раньше начала, лимит — не менее двух команд.
- Матч не может содержать одного соперника с обеих сторон. Указанные команды должны быть приняты в турнир.
- Номер матча уникален внутри раунда турнира. Счёт задаётся для обеих сторон и проверяется с учётом BO1/BO3/BO5.
- Следующий матч принадлежит тому же турниру и более позднему раунду. У него два места: `a` и `b`, по одному предыдущему матчу на место.
- В круговом турнире ссылка на следующий матч не используется.
- При изменении счёта через админку автоматически записываются автор и прежние/новые значения. Запись счёта и истории выполняется в одной транзакции.
- Журнал доступен для просмотра, но не для ручного редактирования в админке.

Простые ограничения продублированы в PostgreSQL. Проверки состава, лимита и формата выполняются формами и `Model.clean()`; код, который в будущем записывает данные напрямую через ORM, также должен вызывать валидацию. Обработка одновременных заявок и продвижение победителя относятся к следующим этапам.

## Хранение и удаление

Данные сохраняются в PostgreSQL и остаются после перезапуска Django. Капитаны, организаторы, участники и авторы истории защищены `PROTECT`, пока используются в связанных записях. При удалении турнира его матчи и заявки удаляются каскадно; стандартная админка заранее показывает список связанных объектов. Не удаляйте учебный турнир ради проверки изменения полей.

Дата и время хранятся с часовым поясом; на сайте и в админке показываются по Москве.
Логотипы и аватары пока задаются ссылками. Загрузка файлов, игровые показатели и исторические снимки составов добавляются на следующих этапах.
