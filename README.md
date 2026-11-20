# Analyst Days 23 · API очной траектории

FastAPI читает опубликованную программу 20 и 21 ноября 2026 года через SQLAlchemy и SQLite. API вычисляет маршрут по темам и действиям из текущего запроса. Фронтенд использует результат для подсветки и сборки PNG в браузере.

[Фронтенд](https://github.com/Roman607/analyst-days-23-frontend) · [Проектный OpenAPI](API/openapi.yaml) · [Комплект для жюри](https://roman607.github.io/analyst-days-23-docs/)

## Подготовка и запуск

Установите Python 3.14 и [uv](https://docs.astral.sh/uv/). Выполните команды из корня репозитория.

```bash
uv sync --locked --python 3.14
uv run --locked python -m app.program
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Локально доступны [Swagger UI](http://127.0.0.1:8000/api/docs) и [OpenAPI JSON](http://127.0.0.1:8000/api/openapi.json). При пустой или повреждённой базе API возвращает `503 program_unavailable`. Переменная `PROGRAM_DB` задаёт путь к другому файлу.

## Снимок программы

`data/program.json` фиксирует [официальную HTML-сетку](https://analystdays.ru/ru/program/149939). Границы блицев получены из порядка в слоте и указанных 20 минут. Части мастер-классов идут по отдельным интервалам из HTML с непосредственным предшественником. Две части панельной дискуссии имеют вид `discussion` и выбираются отдельно. [Печатная сетка](https://analystdays.ru/files/AD23-Schedule.pdf) уточняет непрерывные блоки работы команд и оценки хакатона. Названия и состав спикеров сверены по актуальной HTML-сетке.

У вечерней программы 20 ноября и закрытия 21 ноября организаторы публикуют только начало. Для двух служебных карточек заложено по 30 минут, до 19:10 и 19:00 МСК. У технических перерывов пятой колонки в заголовке указана площадка хакатона. Повторяющиеся обеды второй смены сведены в одну карточку на день.

```bash
uv run --locked python -m app.program --source data/program.json --output data/program.sqlite3
uv run --locked pytest
actionlint
```

При исправлении текста сохраняйте `entry.id`. ID докладов опираются на ID карточек организаторов. Импорт строит и проверяет новый SQLite в одной транзакции и заменяет опубликованный файл только после успеха. `revision` — SHA-256 нормализованного содержимого программы. Для обновления запущенного Compose используйте новый выпуск, который примонтирует файл нового снимка.

## Выпуск на Timeweb

CI запускает проверки при pull request и при обновлении `main`. Успешная сборка из `main` публикует образ с полным SHA коммита. Оба пакета GHCR должны иметь публичный доступ для скачивания на Timeweb.

```bash
gh workflow run deploy.yml --ref main   -f backend_sha=ПОЛНЫЙ_SHA_БЭКЕНДА   -f frontend_sha=ПОЛНЫЙ_SHA_ФРОНТЕНДА
gh run list --workflow deploy.yml --limit 1
gh run watch ID_ЗАПУСКА --exit-status
```

Настройте GitHub Environment `timeweb` для ветки `main` и секреты `TIMEWEB_SSH_KEY` и `TIMEWEB_KNOWN_HOSTS`. Сервер использует сохранённый сертификат из `/opt/ad23-track/letsencrypt`. Сборка выпуска создаёт каталог `/opt/ad23-track/releases/<run>-<attempt>` со своим Compose-конфигом и SQLite выбранной версии бэкенда. Workflow перезапускает проект `ad23-track` и проверяет лендинг, API и Swagger по HTTPS со стороны GitHub Actions.

Для отката запустите тот же workflow с SHA предыдущей проверенной пары. Снимок будет собран из исходников указанной версии бэкенда. Идентификаторы обоих образов сохраняются в журнале запуска.

## Приёмка Swagger

[Сайт на Timeweb](https://ad23-track.89.23.100.193.nip.io:8445/) · [Публичный Swagger UI](https://ad23-track.89.23.100.193.nip.io:8445/api/docs)

1. Откройте `/api/docs` и вызовите `GET /api/program` через **Try it out**. Скопируйте `revision` и ID темы «ИИ».
2. В `POST /api/trajectory/preview` передайте версию, тему и `actions: []`. На 21 ноября в 16:30 результат включает Неверова (A) и Бонареву (B) как варианты.
3. Добавьте `choose` для ID Бонаревой из программы. В интервале остаётся зал B. Удалите `revision` из запроса и проверьте `422 invalid_request`.
