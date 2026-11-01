# Разметка в Label Studio

Этот документ описывает рабочий экспорт Label Studio. Полный протокол качества, включая два независимых чтения и adjudication, находится в [ANNOTATION.md](ANNOTATION.md). Результаты одного разметчика допустимо публиковать только с этой оговоркой; они не называются согласованным экспертным эталоном.

Зачем: без человеческой разметки нельзя честно измерить accuracy категории и macro-F1 приоритета
; обучение на слабых метках возможно, но такие метки не заменяют независимую оценку (см. `ANNOTATION.md`). Размечаем только два оцениваемых поля:
**категорию и приоритет** — два клика на тикет.

Все файлы ниже содержат приватные данные: **только вне Git**, удалить в течение 14 дней после
объявления победителей.

## 1. Выборка, конфиги, деление между людьми

```sh
H=/private/handout          # tickets_train.jsonl.gz, tickets_valid.jsonl, taxonomy.json, rules.json
O=/private/labeling
PYTHONPATH=backend python scripts/labeling.py sample --train $H/tickets_train.jsonl.gz --valid $H/tickets_valid.jsonl --taxonomy $H/taxonomy.json --out-dir $O
PYTHONPATH=backend python scripts/labeling.py config --taxonomy $H/taxonomy.json --out-dir $O
PYTHONPATH=backend python scripts/labeling.py split --in-dir $O --out-dir $O/split --people 2
```

| Часть | Строк | Зачем | Как отобрана |
|---|---|---|---|
| test | 200 | финальная оценка, **не трогать до конца экспериментов** | как organizer valid: доля каналов и языков (≈82% жалоб, ≈12% uz) |
| dev | 100 | пороги и выбор модели | так же |
| train | 500 | обучение | половина как valid, половина — покрытие редких категорий |

Защита от утечки: только train организаторов; без игроков и текстов из valid; группы
«один игрок или одинаковый текст из ≥ 4 слов» целиком в одной части; один тикет на группу.
Результат проверок — `sample_summary.json` → `leakage_checks` (все нули).
Разметчик видит только сообщения игрока, комментарий обвиняемого и метаданные — никаких ответов
админа, вердиктов, наказаний и подсказок модели.

`split` делит 800 задач поровну и без пересечений: `split/person_1` и `split/person_2`, по 400
(test 100, dev 50, train 250 у каждого). В каждой папке 4 файла задач и оба конфига.

## 2. Label Studio

```sh
python -m venv .ls-venv && .ls-venv/Scripts/pip install label-studio      # проверено на 1.23.2
LABEL_STUDIO_BASE_DATA_DIR=/private/labeling/ls-data .ls-venv/Scripts/label-studio start --port 8080
```

Каждый человек берёт **только свою папку** и создаёт 4 проекта:
Create Project → Labeling Setup → Code → вставить XML → Data Import → JSON-файл → Save.

| Проект | Конфиг (XML) | Задачи (JSON) |
|---|---|---|
| complaint-test | `label_config_complaint.xml` | `tasks_complaint_test.json` |
| report-test | `label_config_report.xml` | `tasks_report_test.json` |
| complaint-trainval | `label_config_complaint.xml` | `tasks_complaint_trainval.json` |
| report-trainval | `label_config_report.xml` | `tasks_report_trainval.json` |

`complaint` к `complaint`, `report` к `report`: в чужом конфиге нет нужных категорий.
Порядок: сначала оба test-проекта, потом trainval. Если проект уже создан со старым конфигом —
Settings → Labeling Interface → Code → вставить новый XML, задачи импортировать заново не нужно.

## 3. Как размечать

1. **Категория** — по смыслу сообщения игрока и только из списка своего канала. Категория — это заявленная
   проблема, доказанность не нужна. Апелляция своего наказания («не согласен с наказанием») → `complaint.admin`.
   Одно «помогите», «ау», «+» → `report.offtopic`. Ник на латинице смысла не меняет.
2. **Приоритет** — по критериям из подсказок (таксономия организаторов).

**Решить командой до начала:** таксономия ставит в p1 «жалобы с доказательствами», а в p2 «оскорбления, DM»,
но вложения есть у всех жалоб handout. Договоритесь об одном правиле (рекомендация: тип проблемы решает —
оскорбления/DM p2, читы/скам/RMT p1, без доказательств p3) и размечайте одинаково.

## 4. Gold

Export → JSON в каждом проекте у каждого человека, затем все файлы разом:

```sh
PYTHONPATH=backend python scripts/labeling.py gold --export $O/export_*.json --rules $H/rules.json --output $O/gold.jsonl --report $O/gold_report.json
```

Статусы: `single_annotator`, `agreed`, `adjudicated` — годны; `has_errors` (категория чужого канала,
нет приоритета) и `needs_adjudication` — исправить в Label Studio и выгрузить снова.

**Ограничение:** при делении без пересечений каждую задачу видит один человек, поэтому согласие
разметчиков (Cohen's kappa) не измеряется — так и указываем в отчёте. Чтобы его получить, оба размечают
одни и те же 50 задач test; тогда `gold_report.json` → `agreement_before_adjudication` посчитает raw и kappa.

## 5. Совместимость с серверным обучением и оценкой

Экспорт gold содержит `labels.category` / `labels.priority` и annotation_id. Для `evaluate` используйте `--gold` и `--manifest`: оценщик связывает annotation_id с ticket_id и сравнивает ответы полного сервиса.

Для `train-reports` подготовьте приватный объединённый файл: `kind`, `split`, `text`/`player_text`, `category`/`labels.category`, при наличии — `field`, `accused`/`accused_text`, reporter_hash и group_id. Сохраняйте строки dev/test при проверке групп: trainer исключает связанные компоненты до обучения на train. Не передавайте admin replies как text. Автоматического join gold с задачами в trainer нет; отсутствие текстовых признаков вызывает ошибку.

Для модели complaint передавайте полный manifest удерживаемых задач в `make train ... EXCLUDE=...`. Исключение целых групп действует по указанным IDs; отдельно проверьте пересечения с organizer valid. Наличие одинакового текста короче четырёх слов также учитывается новым trainer, поэтому его разбиение консервативнее исходного sampler.
