# 🚚 DeliveryCalc — калькулятор оптимальной доставки

DeliveryCalc рассчитывает стоимость доставки стройматериалов: перебирает заводы, машины и тарифы, учитывает особые пороги и выдаёт топ‑3 самых выгодных комбинаций. Интерфейс адаптирован под десктоп и мобильные устройства.

## ✨ Возможности
- Подбор оптимальной комбинации тарифов (манипуляторы, длинномеры, спецтехника).
- Учёт special_threshold / max_per_trip и ступенчатой логики для тяжёлых рейсов (DAF).
- Разбивка рейсов с деталями: что везёт каждая машина, какой тариф выбран, контакт завода.
- Импорт данных из Google Sheets (`factories_products` и `tariffs`).
- **Аутентификация через JWT** — защита админских операций логином и паролем.
- **PostgreSQL** — все данные хранятся в базе данных вместо JSON файлов.
- Готовые шаблоны секретов, чтобы рабочие ключи не попадали в git.

## 📂 Структура
```
backend/                 # FastAPI, расчёты и парсинг данных
backend/storage/          # Локальные json с тарифами и товарами
frontend/                # React + Vite интерфейс
Dockerfile.backend       # Образ для FastAPI
Dockerfile.frontend      # Образ для статического фронта на nginx
docker-compose.yml       # Готовый стенд: backend + frontend
.env.example             # Шаблон окружения
google_credentials.example.json # Шаблон сервисного аккаунта
```

## 🔑 Подготовка окружения (локально)
1. Скопируйте `.env.example` → `.env` и подставьте свой `GOOGLE_SHEET_ID` и путь к `google_credentials.json`.
2. Добавьте в `.env` настройки PostgreSQL и JWT:
   ```
   POSTGRES_DB=delivery_calc
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=postgres
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/delivery_calc
   JWT_SECRET_KEY=your-secret-key-change-in-production
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=admin
   ```
3. Скопируйте `google_credentials.example.json` → `google_credentials.json` и заполните реальным ключом сервисного аккаунта (файл в git не коммитим).
4. Установите зависимости:
   ```bash
   pip install -r backend/requirements.txt
   cd frontend && npm install
   ```
5. Запустите PostgreSQL (через Docker или локально):
   ```bash
   docker compose up postgres -d
   ```
6. Инициализируйте БД и создайте администратора:
   ```bash
   python -m backend.core.db_migration
   ```

### Как запустить локально (dev)
1. **Backend** — FastAPI с горячей перезагрузкой и доступом для фронта:
   ```bash
   uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   - OSRM используется «как есть» (стандартный публичный экземпляр), координаты и входные параметры передаются через `/api/quote`.
   - JSON-файлы `backend/storage` подхватываются автоматически; при обновлении можно вызвать `/admin/reload`.

2. **Frontend** — Vite dev-server c пробросом API на localhost:
   ```bash
   cd frontend
   npm run dev -- --host --port 5173
   ```
   - В dev API база задаётся автоматически (`http://127.0.0.1:8000`). Если меняете порт или хост бэкенда, задайте `VITE_API_BASE` в `.env` фронта.

## 🐳 Docker/Compose
Требуются `.env` и `google_credentials.json` рядом с `docker-compose.yml`. Полный цикл сборки и запуска (локально):
```bash
docker compose up --build
```
- **Backend**: http://localhost:8000 (авто-добавляет CORS для фронта из compose).
- **Frontend**: http://localhost:5173 — статика на nginx, `/api` и `/admin` проксируются на backend.
- **PostgreSQL**: порт 5432 (внутри Docker доступен как `postgres:5432`).
- **Пересборка фронта с другим API**: во время `docker compose build` можно задать `VITE_API_BASE=http://<host>:8000`.

**При первом запуске:**
- БД автоматически инициализируется при старте backend
- Создаётся администратор по умолчанию (см. переменные окружения)
- Данные из Google Sheets загружаются в БД при старте

### 🚀 Первый деплой на VDS/Timeweb через Docker Compose
1. Подготовьте `.env` из шаблона и положите рядом с `docker-compose.timeweb.yml`. Убедитесь, что `GOOGLE_APPLICATION_CREDENTIALS` указывает на путь `/app/secrets/google_credentials.json` (он монтируется внутрь контейнера).
2. Разместите файл `google_credentials.json` рядом с compose-файлом (не коммитим в git).
3. Скачайте данные OSRM (например, `russia-latest.osrm`) в папку `osrm-data` — она автоматически монтируется в контейнер osrm. В `.env` оставьте `OSRM_BASE_URL=http://osrm:5000`, чтобы backend ходил к локальному роутеру.
4. Запуск сервисов в фоне:
   ```bash
   docker compose -f docker-compose.timeweb.yml up -d --build
   ```
   - Backend будет доступен на `:8000`, frontend — на порту `80` (nginx).
   - `VITE_API_BASE` можно переопределить в `.env` перед сборкой, чтобы фронтенд сразу указывал на публичный домен.
5. Пересобрать фронт/бэкенд после обновлений: `docker compose -f docker-compose.timeweb.yml up -d --build`.
6. Остановить контейнеры: `docker compose -f docker-compose.timeweb.yml down`.

## 📡 Основные эндпоинты

### Публичные (без аутентификации)
- `GET /api/factories` — список товаров на заводах
- `GET /api/tariffs` — тарифы транспорта
- `GET /api/categories` — список категорий товаров
- `POST /api/quote` — расчёт доставки (возвращает варианты, рейсы, тарифы)
- `GET /api/fibonacci?count=<N>` — последовательность Фибоначчи длиной N и последнее значение

### Аутентификация
- `POST /auth/login/json` — вход в систему (JSON: `{"username": "...", "password": "..."}`)
- `POST /auth/login` — вход через OAuth2 form (для Swagger)
- `GET /auth/me` — информация о текущем пользователе (требует токен)
- `POST /auth/register` — регистрация нового пользователя (опционально)

### Админские (требуют роль admin)
- `POST /admin/reload` — обновить данные из Google Sheets в БД
- `POST /admin/reload/factories` — обновить только заводы и товары
- `POST /admin/reload/tariffs` — обновить только тарифы

**По умолчанию создаётся администратор:** `admin` / `admin` (можно изменить через переменные окружения `ADMIN_USERNAME` и `ADMIN_PASSWORD`)

### Пример запроса `/api/quote`
```json
{
  "upload_lat": 55.7558,
  "upload_lon": 37.6173,
  "transport_type": "auto",
  "addManipulator": true,
  "selectedSpecial": "Манипулятор SPECIAL",
  "items": [
    { "category": "Дорожные ПЛИТЫ/ПАГИ", "subtype": "2п30.18.30 ТУ", "quantity": 10 }
  ]
}
```
### Пример ответа (сокращённо)
```json
{
  "variants": [
    {
      "totalCost": 167000,
      "deliveryCost": 48000,
      "totalWeight": 44,
      "tripItems": [
        {
          "завод": "тубетон",
          "машина": "Длинномер MAN TSG",
          "тариф": "80-100 км / длиномер / >20т",
          "расстояние_км": 79.29,
          "загрузка_т": 40,
          "товары": "2п30.18.30 ТУ × 18",
          "стоимость_доставки": 48000
        }
      ]
    }
  ]
}
```

## 🧹 Правила работы с секретами
- `.env`, `google_credentials.json`, `delivery_bot_2_credentials.json` уже в `.gitignore` и `.dockerignore`.
- Если ключ случайно попал в git — удалите его из истории, выпустите новый в Google Cloud и обновите локальный файл из шаблона.

## ✅ Тесты
- Запуск: `python -m pytest backend/tests`
- Что проверяют тесты Фибоначчи:
  - `/api/fibonacci?count=7` возвращает последовательность `[0, 1, 1, 2, 3, 5, 8]` и `last = 8`.
  - Нулевое или отрицательное значение `count` валидируется и приводит к ответу 422.
  - Сервисная функция строит 20 первых чисел и заканчивает на `4181`.
- Ожидаемый вывод:
  - При установленных тестовых зависимостях (`httpx`) — `3 passed`.
  - Если `httpx` отсутствует — `1 passed, 2 skipped` (пропускаются API-тесты).

## 💡 Советы по эксплуатации
- Для продакшена можно переопределить `VITE_API_BASE` при сборке фронта, если backend размещён на другом домене.
- В `docker-compose.yml` подключение `backend/storage` вынесено в volume: можно обновлять json без пересборки образа.
- UI адаптивный: таблицы внутри карточек имеют горизонтальную прокрутку, кнопки и поля увеличены для удобства на телефоне.
