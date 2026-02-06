# 🚚 DeliveryCalc — калькулятор оптимальной доставки

DeliveryCalc помогает быстро посчитать стоимость доставки стройматериалов: сервис перебирает заводы, транспорт и тарифы, учитывает специальные пороги загрузки и показывает топ‑3 самых выгодных сценария. Интерфейс адаптирован под десктоп и мобильные устройства.

## ✨ Ключевые возможности
- **Подбор оптимальных комбинаций** тарифов (манипуляторы, длинномеры, спецтехника) с сортировкой по выгоде.
- **Сложная логика рейсов**: special_threshold, max_per_trip и ступенчатые правила для тяжёлых рейсов (например DAF).
- **Детализация рейсов** — что везёт каждая машина, какой тариф применён, с контактами заводов.
- **Импорт из Google Sheets** (`factories_products`, `tariffs`) и обновление через админские эндпоинты.
- **JWT‑аутентификация** и роли для защищённых операций.
- **PostgreSQL‑хранилище** вместо локальных JSON.
- **OSRM** для расчёта расстояний (можно держать локальный роутер в Docker).
- Готовые **шаблоны секретов**, чтобы рабочие ключи не попадали в git.

## 🧱 Стек
- **Backend**: FastAPI + SQLAlchemy + Alembic
- **Frontend**: React + Vite + Nginx (статический билд)
- **Инфраструктура**: Docker Compose, PostgreSQL, OSRM

## 📂 Структура
```
backend/                 # FastAPI, расчёты и парсинг данных
backend/storage/         # Локальные json с тарифами и товарами
frontend/                # React + Vite интерфейс
Dockerfile.backend       # Образ для FastAPI
Dockerfile.frontend      # Образ для статического фронта
docker-compose.yml       # Локальный стенд (backend + frontend + postgres + osrm)
docker-compose.timeweb.yml # Деплой на Timeweb/VDS
backend.env.example      # Шаблон окружения backend
backend.env              # Локальные переменные (в .gitignore)
google_credentials.example.json # Шаблон сервисного аккаунта
```

## 🔑 Подготовка окружения (локально)
1. Скопируйте `.env.example` → `.env` и заполните `GOOGLE_SHEET_ID`.
2. Скопируйте `backend.env.example` → `backend.env` и заполните JWT/админа.
3. Скопируйте `google_credentials.example.json` → `google_credentials.json` и заполните ключ сервисного аккаунта (файл не коммитится).
4. Установите зависимости:
   ```bash
   pip install -r backend/requirements.txt
   cd frontend && npm install
   ```
5. Запустите PostgreSQL (можно через Docker):
   ```bash
   docker compose up postgres -d
   ```
6. Инициализируйте БД и создайте администратора:
   ```bash
   python -m backend.core.db_migration
   ```

## 🧪 Запуск локально (dev)
1. **Backend** — FastAPI с горячей перезагрузкой:
   ```bash
   uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
   ```
2. **Frontend** — Vite dev‑server:
   ```bash
   cd frontend
   npm run dev -- --host --port 5173
   ```
   Если backend работает на другом адресе, задайте `VITE_API_BASE` в `.env` фронта.

## 🐳 Docker/Compose (локально)
Требуются `.env`, `backend.env` и `google_credentials.json` рядом с `docker-compose.yml`.
```bash
docker compose up --build
```
- **Backend**: http://localhost:8000
- **Frontend**: http://localhost:5173
- **PostgreSQL**: доступен на `localhost:5432` (внутри Docker — `postgres:5432`)

> Совет: можно переопределить `VITE_API_BASE` при сборке фронта.

## 🚀 Деплой на Timeweb/VDS (docker-compose.timeweb.yml)
1. Скопируйте `.env.example` → `.env` и заполните:
   ```bash
   GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/google_credentials.json
   GOOGLE_SHEET_ID=your-sheet-id

   POSTGRES_DB=delivery_calc
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=strong-password

   JWT_SECRET_KEY=replace-in-production
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=strong-password

   # OSRM
   OSRM_BASE_URL=http://osrm:5000
   OSRM_DATASET=central-fed-district-latest.osrm

   # Публичный адрес API для фронта
   VITE_API_BASE=https://your-domain.ru
   ```
2. Положите `google_credentials.json` рядом с compose‑файлом.
3. Скачайте OSRM‑данные (например, `russia-latest.osrm`) и положите в `osrm-data/`.
4. Запуск:
   ```bash
   docker compose -f docker-compose.timeweb.yml up -d --build
   ```
5. Пересборка после обновлений:
   ```bash
   docker compose -f docker-compose.timeweb.yml up -d --build
   ```
6. Остановка:
   ```bash
   docker compose -f docker-compose.timeweb.yml down
   ```

## 📡 Основные эндпоинты
### Публичные
- `GET /api/factories`
- `GET /api/tariffs`
- `GET /api/categories`
- `POST /api/quote`
- `GET /api/fibonacci?count=<N>` — сервисный эндпоинт

### Аутентификация
- `POST /auth/login/json`
- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/register` (опционально)

### Админские
- `POST /admin/reload`
- `POST /admin/reload/factories`
- `POST /admin/reload/tariffs`

## 🧹 Работа с секретами
- `.env`, `backend.env`, `google_credentials.json` уже в `.gitignore`.
- Если ключ попал в git — удалите его из истории, выпустите новый в Google Cloud и обновите локальный файл.

## ✅ Тесты
```bash
python -m pytest backend/tests
```
Тесты покрывают API-эндпоинты (`/api/factories`, `/api/tariffs`, `/api/categories`, `/api/quote`, `/api/fibonacci`) и сервисную логику. Для API-тестов нужен пакет `httpx` (он уже указан в `backend/requirements.txt`). Если `httpx` не установлен, эти тесты будут пропущены.

## 💡 Эксплуатационные советы
- Для продакшена выставляйте `VITE_API_BASE` на публичный адрес backend.
- В `docker-compose.yml` подключение `backend/storage` вынесено в volume: можно обновлять json без пересборки образа.
- UI адаптивный: таблицы внутри карточек имеют горизонтальную прокрутку, элементы управления увеличены для смартфонов.

## 💾 Резервное копирование БД (JSON-снимок)
Для экспорта и импорта всех таблиц, управляемых SQLAlchemy, используйте скрипты:

```bash
python backend/scripts/export_db_json.py --output db_snapshot.json
```
Снимок сохраняется в путь, указанный в `--output` (по умолчанию — `db_snapshot.json` в текущей папке).
В Windows/PowerShell используйте именно `python ...`, запуск через `./backend/scripts/*.py` может открыть файл в редакторе вместо выполнения.

Если вы запускаете БД в Docker, проще выполнить экспорт внутри контейнера backend и сохранить файл в `backend/storage`,
который примонтирован как volume:

```bash
docker compose exec backend python backend/scripts/export_db_json.py --output /app/backend/storage/db_snapshot.json
```

## Автоматический снапшот каждые 6 часов

Добавлен планировщик `backend/scripts/scheduled_db_snapshot.py`, который по умолчанию
перезаписывает `backend/storage/db_snapshot.json` каждые 6 часов.

Локально (в т.ч. Windows):

```bash
python backend/scripts/scheduled_db_snapshot.py
```

Проверка одного запуска:

```bash
python backend/scripts/scheduled_db_snapshot.py --once
```

Windows Task Scheduler (каждые 6 часов) можно создать так:

```powershell
schtasks /Create /SC HOURLY /MO 6 /TN "DeliveryCalcDbSnapshot" /TR "python C:\path\to\delivery_calc\backend\scripts\scheduled_db_snapshot.py"
```

Docker/VDS: включите отдельный сервис снапшотов, который пишет в тот же volume `backend/storage`:

```bash
docker compose up -d db_snapshot
```
Если запускать все сервисы сразу (`docker compose up -d`), `db_snapshot` тоже поднимется и будет работать в фоне с перезапуском (`restart: unless-stopped`).

```bash
python backend/scripts/import_db_json.py --input db_snapshot.json
```
Импорт по умолчанию удаляет текущие строки и восстанавливает данные из снимка. Чтобы сохранить текущие данные, используйте `--no-truncate`.
Для Docker поместите файл в `backend/storage` и выполните импорт внутри контейнера:

```bash
docker compose exec backend python backend/scripts/import_db_json.py --input /app/backend/storage/db_snapshot.json
```