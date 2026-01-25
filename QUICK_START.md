# ⚡ Быстрый старт (Docker) — с пересборкой контейнеров

## 🎯 За 3 шага

### 1️⃣ Подготовка файлов

**Создайте `.env` в корне проекта:**
```bash
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/google_credentials.json
GOOGLE_SHEET_ID=ваш-id-таблицы

POSTGRES_DB=delivery_calc
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/delivery_calc

JWT_SECRET_KEY=your-secret-key-change-in-production

ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
```

**Положите `google_credentials.json` в корень проекта**

### 2️⃣ Пересборка и запуск

```bash
# Остановить и удалить старые контейнеры (если были)
docker compose down --remove-orphans

# Пересобрать образы и поднять сервисы
docker compose up -d --build
```

### 3️⃣ Откройте в браузере

- **Приложение:** http://localhost:5173
- **Вход:** http://localhost:5173/login
  - Логин: `admin`
  - Пароль: `admin`

---

## 🛑 Остановка

```bash
# Остановить контейнеры
docker compose stop

# Остановить и удалить:
docker compose down
```

---

## 🔍 Проверка

```bash
# Статус контейнеров
docker compose ps

# Логи
docker compose logs -f
```

---

## ✅ Тесты

```bash
python -m pytest backend/tests
```

> Примечание: API-тесты используют `httpx`, он уже включён в `backend/requirements.txt`.

---

**Подробная инструкция:** см. `README.md`