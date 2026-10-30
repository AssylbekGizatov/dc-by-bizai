# Сторонние компоненты и источники

Код решения принадлежит команде; этот перечень не меняет его лицензионный статус и не распространяет лицензии библиотек на данные Grand Mobile. Прямые зависимости устанавливаются пакетными менеджерами, а не копируются из чужого приложения. Полные тексты лицензий и notices сохраняются в установленных дистрибутивах; при распространении контейнера сохраняйте их и notices транзитивных зависимостей.

| Компонент | Использование | Лицензия / первичный источник |
|---|---|---|
| FastAPI | HTTP API | [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| Pydantic | Контракт и валидация | [MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE) |
| Uvicorn | ASGI server | [BSD-3-Clause](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) |
| HTTPX | Опциональный вызов Groq | [BSD-3-Clause](https://github.com/encode/httpx/blob/master/LICENSE.md) |
| NumPy | Вычисления retrieval | [BSD-3-Clause и bundled notices](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| scikit-learn | Символьный TF-IDF | [BSD-3-Clause](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING) |
| rank-bm25 | Лексический retrieval | [Apache-2.0](https://github.com/dorianbrown/rank_bm25/blob/master/LICENSE) |
| React / React DOM | Интерфейс | [MIT](https://github.com/facebook/react/blob/main/LICENSE) |
| Lucide | Иконки | [ISC, с указанными upstream notices](https://github.com/lucide-icons/lucide/blob/main/LICENSE) |
| TypeScript | Проверка типов | [Apache-2.0](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt) |
| Vite / Vitest | Сборка и UI tests | [Vite MIT](https://github.com/vitejs/vite/blob/main/LICENSE), [Vitest MIT](https://github.com/vitest-dev/vitest/blob/main/LICENSE.md) |
| pytest | Backend tests | [MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE) |
| sentence-transformers | Только optional local encoder | [Apache-2.0](https://github.com/huggingface/sentence-transformers/blob/master/LICENSE) |
| PyTorch CPU | Только optional local encoder | [BSD-style и bundled third-party notices](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| Transformers | Только optional local encoder | [Apache-2.0](https://github.com/huggingface/transformers/blob/main/LICENSE) |
| SentencePiece | Только optional tokenizer | [Apache-2.0](https://github.com/google/sentencepiece/blob/master/LICENSE) |

Точные frontend-версии и транзитивные зависимости зафиксированы `frontend/package-lock.json`; Python ranges находятся в `backend/requirements*.txt`, а проверенное разрешение runtime/test зависимостей — в `constraints.txt` (Python 3.12, Linux). `make setup` и Docker используют эти constraints. Проверенные optional encoder versions находятся в `constraints-models.txt`; CPU PyTorch устанавливается с официального индекса по инструкции README. Для воспроизводимого пилота также зафиксируйте digest базовых Docker-образов после проверки.

## Модели и внешние сервисы

- По умолчанию используются разработанные для проекта синтетические fixtures, эвристики и шаблоны. Предобученные веса не включены и автоматически не скачиваются.
- Optional encoder: [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3), MIT по model card. Helper фиксирует revision `614241f622f53c4eeff9890bdc4f31cfecc418b3` и SHA-256 всех десяти файлов и сохраняет model card с весами вне Git. В этом snapshot отдельного LICENSE-файла нет; до дальнейшего распространения весов проверьте полноту notices у автора. Другие модели требуют отдельной проверки совместимости и лицензии.
- Groq — внешний сервис, а не встроенная open-source модель. У выбранной модели и провайдера свои условия и ограничения; [каталог моделей](https://console.groq.com/docs/models). Адаптер не предоставляет ключ, подписку или право передавать данные третьей стороне.
- Материалы кейса Grand Mobile × Decentrathon 6.0 определяют контракт и ограничения. Сам корпус, действующие правила и исторические тикеты не распространяются с решением.

Синтетические fixtures и UI-сценарии созданы для проверки функций. Они не являются цитатами правил, экспортом данных или примерами реальных игроков.
