# 📖 Полное руководство по командам AgentBox (CLI Reference)

[English](CLI.md) | [Русский](CLI.ru.md)

AgentBox — это набор команд, созданный специально для ИИ-помощников (**Cursor, Claude Code, Antigravity, Aider, Windsurf, Roo-Code**) и разработчиков.

Главная цель утилиты — **не тратить лишние токены (и деньги)**, **не засорять контекст модели гигантскими логами** и **навсегда забыть про ошибки со сломанными кавычками в Windows PowerShell и SSH**.

> [!TIP]
> **Как этим пользоваться:** Тебе не обязательно учить все эти команды наизусть! Достаточно один раз запустить `agentbox rules` в своём проекте. Команда создаст файл инструкций `AGENTS.md`, и твой ИИ-ассистент будет сам вызывать нужные команды. Но знать, как они работают, очень полезно!

---

## 📑 Оглавление

1. [Главные параметры всех команд (Глобальные флаги)](#1-главные-параметры-всех-команд-глобальные-флаги)
2. [Управление серверами (`agentbox target`)](#2-управление-серверами-agentbox-target)
3. [Рецепты задач проекта (`agentbox task`)](#3-рецепты-задач-проекта-agentbox-task)
4. [Генератор правил для ИИ (`agentbox rules`)](#4-генератор-правил-для-ии-agentbox-rules)
5. [Изучение кода без лишних токенов](#5-изучение-кода-без-лишних-токенов)
   * [`agentbox outline` — скелет файла](#agentbox-outline-file)
   * [`agentbox get-fn` — одна конкретная функция](#agentbox-get-fn-file-name)
   * [`agentbox find-fn` — найти, где объявлена функция](#agentbox-find-fn-name-path---exact)
   * [`agentbox refs` — где используется символ](#agentbox-refs-symbol-path)
   * [`agentbox view` — аккуратный срез строк файла](#agentbox-view-file---start-n---end-m---tail-n)
   * [`agentbox tree` — дерево проекта без мусора](#agentbox-tree-path---depth-n)
   * [`agentbox grep` — быстрый поиск текста](#agentbox-grep-query-path---fixed---max-n--l)
6. [Безопасное редактирование файлов](#6-безопасное-редактирование-файлов)
   * [`agentbox patch-lines` — замена диапазона строк](#agentbox-patch-lines-file---start-n---end-m)
   * [`agentbox write` — безопасная запись файла](#agentbox-write-file)
   * [Пакетная передача файлов через `agentbox write local:remote`](#пакетная-передача-нескольких-файлов)
   * [`agentbox cp` — копирование между серверами](#agentbox-cp-src-dest)
   * [`agentbox patch` — умная замена блока текста](#agentbox-patch-file---old-old---new-new)
   * [`agentbox rollback` — откат к предыдущей версии](#agentbox-rollback-file)
7. [Тихий запуск тестов, сборки и скриптов](#7-тихий-запуск-тестов-сборки-и-скриптов)
   * [`agentbox run` — тихий запуск любой команды](#agentbox-run-command)
   * [`agentbox test` — умный запуск тестов](#agentbox-test-test_command)
   * [`agentbox py` — быстрый запуск Python без проблем с кавычками](#agentbox-py)
   * [`agentbox pip` — установка библиотек в изолированное окружение](#agentbox-pip-args)
8. [Фоновые процессы на сервере](#8-фоновые-процессы-на-сервере)
   * [`agentbox spawn` — запустить процесс в фоне](#agentbox-spawn-command)
   * [`agentbox status` — узнать статус процесса](#agentbox-status-task_id)
   * [`agentbox logs` — посмотреть или читать логи на лету](#agentbox-logs-task_id)
   * [`agentbox kill` — остановить процесс](#agentbox-kill-task_id)
9. [Экономный Git](#9-экономный-git)
   * [`agentbox git-status` — статус без простыни текста](#agentbox-git-status-path)
   * [`agentbox diff` — разница без пробелов и lock-файлов](#agentbox-diff-path)
   * [`agentbox git-log` — история коммитов в 1 строку](#agentbox-git-log-path--n-n)
   * [`agentbox git-view` — просмотр файла из прошлого коммита](#agentbox-git-view-file-rev)
   * [`agentbox git-fn-history` — история изменений одной функции](#agentbox-git-fn-history-file-function_name)
10. [Синхронизация папок проекта (`agentbox sync`)](#10-синхронизация-папок-проекта-agentbox-sync)
11. [Граф связей в проекте (`graphify`)](#11-граф-связей-в-проекте-graphify)
12. [Ускоритель удаленной работы (`agentbox daemon`)](#12-ускоритель-удаленной-работы-agentbox-daemon)
13. [Аналитика и статистика (`stats`, `audit`, `batch`)](#13-аналитика-и-статистика-stats-audit-batch)

---

## 1. Главные параметры всех команд (Глобальные флаги)

Любую команду AgentBox можно запускать как на своём компьютере, так и на удалённом сервере. Для этого используются глобальные флаги (их можно указывать до или после подкоманды):

```bash
agentbox [-t <цель>] [--host <user@host>] [--cwd <путь>] [--venv <путь>] [--no-daemon] <команда>
```

| Флаг | Что означает простыми словами |
|---|---|
| `-t, --target <имя>` | На каком сервере выполнять команду (например: `-t dev`, `-t prod` или прямо строка SSH `user@server.com`). Если флаг не указан, команда выполняется локально на твоём компьютере. |
| `--host <user@host>` | Адрес сервера для разового подключения без сохранения в конфиг. |
| `--cwd <путь>` | В какую папку на сервере перейти перед выполнением команды. |
| `--venv <путь>` | Путь к виртуальному окружению Python (если не указано, AgentBox находит или создаёт его сам в `.agentbox/venv`). |
| `--no-daemon` | Отключить быстрый постоянный мост и запускать команду через прямой SSH-вызов. |
| `--version` | Показать версию программы. |

**Пример:**
```bash
# Выполнить команду локально:
agentbox outline src/main.py

# Выполнить ту же команду на сервере "dev":
agentbox -t dev outline src/main.py
```

---

## 2. Управление серверами (`agentbox target`)

У тебя может быть локальный проект, тестовый сервер (dev) и боевой сервер (prod). AgentBox хранит их в файле `.agentbox.json`.

```bash
# Посмотреть список всех настроенных серверов и узнать, какой выбран по умолчанию:
agentbox target
# или:
agentbox target list

# Добавить удаленный сервер по SSH:
agentbox target add dev --host developer@dev.server.com --cwd /home/developer/app --venv /home/developer/app/.venv

# Добавить боевой сервер в режиме "Только для чтения" (Read-Only):
agentbox target add prod --host deploy@prod.server.com --cwd /var/www/backend --readonly

# Сделать сервер активным по умолчанию:
agentbox target use dev

# Включить или выключить режим Read-Only для существующего сервера:
agentbox target prod --readonly
agentbox target prod --off

# Удалить сервер из настроек:
agentbox target rm dev
```

> [!IMPORTANT]
> **Что такое Read-Only Guard?**
> Если сервер помечен флагом `--readonly`, AgentBox блокирует любые попытки изменить на нём файлы (`write`, `patch`, `sync push`) или выполнить произвольные команды (`run`, `test`, `spawn`). ИИ-ассистент сможет только безопасно читать код, файлы и логи (`view`, `outline`, `tree`, `grep`, `graphify-query`), не имея физической возможности сломать прод.

---

## 3. Рецепты задач проекта (`agentbox task`)

В любом проекте мы постоянно повторяем одни и те же команды: запустить тесты, сделать миграцию, собрать проект. 

Если ИИ пытается выполнить длинную команду с кавычками прямо через консоль Windows, она часто падает из-за проблем с экранированием. **Рецепты задач решают эту проблему раз и навсегда.**

```bash
# Посмотреть список доступных задач в проекте:
agentbox task

# Запустить сохранённую задачу (например, запуск тестов):
agentbox task test

# Запустить задачу с дополнительными аргументами:
agentbox task test -k "test_login"

# Добавить новую задачу в проект:
agentbox task add test "pytest tests/ -v"
agentbox task add build "python -m build"

# Задача с подстановкой аргументов ({args}):
agentbox task add db "psql -U postgres -d mydb -c {args}"
# Теперь можно вызывать так:
agentbox task db "SELECT * FROM users LIMIT 5;"

# Закрепить задачу за конкретным сервером:
agentbox task add deploy "git pull && systemctl restart app" --target prod

# Удалить задачу:
agentbox task rm test
```

---

## 4. Генератор правил для ИИ (`agentbox rules`)

Чтобы ИИ-ассистент (**Cursor, Claude Code, Antigravity, Aider, Windsurf**) сразу знал, как правильно работать с проектом и не транжирить токены, AgentBox генерирует файл правил.

```bash
# Создать файл AGENTS.md (стандартный формат для большинства ИИ):
agentbox rules

# Создать правила для конкретного редактора:
agentbox rules --type cursor   # Создаст .cursorrules
agentbox rules --type claude   # Создаст CLAUDE.md
agentbox rules --type all      # Создаст все форматы сразу

# Обновить список серверов и задач в уже существующих файлах правил:
agentbox rules --sync
```

**Что находится внутри сгенерированного файла:**
1. Строгий запрет читать файлы целиком командами `cat`, `Get-Content` или гонять нефильтрованный `grep`.
2. Список всех настроенных серверов (с пометками, если сервер защищён `read-only`).
3. Список всех готовых задач (`task`), чтобы ИИ запускал их вместо ручного ввода сложных команд.
4. Правила безопасного редактирования файлов.

---

## 5. Изучение кода без лишних токенов

Обычный ИИ тратит тысячи токенов просто на то, чтобы понять, что написано в файле. Инструменты навигации AgentBox позволяют агенту видеть ровно то, что нужно.

### `agentbox outline <file>`
Показывает краткий «скелет» файла: только имена классов, функций и методов с номерами строк. Тела функций не выводятся.
```bash
agentbox outline src/auth.py
```
*Результат (всего ~120 токенов вместо 3 000):*
```text
=== OUTLINE: src/auth.py (350 lines) ===
  12-  45 | class AuthConfig:
  48- 110 | async def verify_jwt(token: str) -> dict
  115- 180 | def hash_password(raw_password: str) -> str
```

### `agentbox get-fn <file> <name>`
Достаёт точный код одной функции, метода (`Класс.метод`) или всего класса.
```bash
# Получить функцию:
agentbox get-fn src/auth.py verify_jwt

# Получить метод конкретного класса:
agentbox get-fn src/models.py User.validate_password
```

### `agentbox find-fn <name> [path] [--exact]`
Ищет по всему проекту, в каком именно файле определена нужная функция или класс. Не нужно перебирать все файлы подряд!
```bash
agentbox find-fn verify_jwt
agentbox find-fn User --exact
```

### `agentbox refs <symbol> [path]`
Находит все места в проекте, где используется указанный символ (функция, класс, переменная): импорты, вызовы, наследование.
```bash
agentbox refs verify_jwt src/
```

### `agentbox view <file> [--start N --end M] [--tail N]`
Показывает аккуратный срез строк файла с номерами:
```bash
# Посмотреть строки с 48 по 65:
agentbox view src/auth.py --start 48 --end 65

# Посмотреть последние 30 строк файла (удобно для логов):
agentbox view logs/app.log --tail 30
```

### `agentbox tree [path] [--depth N]`
Показывает дерево файлов и папок, автоматически скрывая мусор: `.git`, `node_modules`, `__pycache__`, `.venv`, папки сборки и кэша.
```bash
# Дерево проекта глубиной в 2 уровня:
agentbox tree --depth 2
```

### `agentbox grep "<query>" [path] [-F] [--max N] [-l]`
Быстрый поиск по тексту файлов с защитой от переполнения контекста (по умолчанию выводит не больше 20 совпадений):
```bash
# Обычный поиск по фразе:
agentbox grep "verify_jwt" src/

# Точный поиск без регулярных выражений (-F):
agentbox grep "token.split('.')" src/ -F

# Вывести только имена файлов, где найдено совпадение (-l):
agentbox grep "DatabaseError" src/ -l
```

---

## 6. Безопасное редактирование файлов

Самая частая боль при работе с ИИ в консоли Windows — сломанные кавычки при попытке записать код в файл. AgentBox гарантирует безопасную запись через флаги `--file`, `--base64` или потоки. Перед каждым изменением файла **автоматически делается резервная копия**.

### `agentbox patch-lines <file> --start N --end M`
Заменяет диапазон строк (с `start` по `end`) на новый текст. Проверяет синтаксис Python перед сохранением!
```bash
# Передать новый код через временный файл:
agentbox patch-lines src/main.py --start 10 --end 15 --file new_code.py

# Передать код в формате Base64 (идеально для автоматизации ИИ без риска сломать кавычки):
agentbox patch-lines src/main.py --start 10 --end 15 --base64 aW1wb3J0IG9z...
```

### `agentbox write <file>`
Создаёт новый файл или полностью перезаписывает существующий:
```bash
# Записать содержимое из файла:
agentbox write src/config.py --file temp_config.py

# Дописать строки в конец файла (--append):
agentbox write logs/audit.log --file entry.txt --append
```

### Пакетная передача нескольких файлов
Позволяет скопировать сразу несколько файлов за одно подключение за миллисекунды:
```bash
agentbox write file1.py:remote/file1.py file2.py:remote/file2.py
```

### `agentbox cp <src> <dest>`
Копирует файлы между локальной машиной и любыми серверами:
```bash
# Скачать файл с удаленного сервера на свой компьютер:
agentbox cp dev:/var/log/app.log ./local_app.log

# Загрузить локальный файл на сервер:
agentbox cp ./config.json dev:/home/developer/app/config.json

# Скопировать файл с сервера dev на сервер prod напрямую через агентскую машину:
agentbox cp dev:/app/dist/app.whl prod:/var/www/dist/
```

### `agentbox patch <file> --old-file <old> --new-file <new>`
Точечно находит блок старого кода и заменяет его на новый с проверкой синтаксиса.
```bash
agentbox patch src/main.py --old-file old_block.py --new-file new_block.py
```

### `agentbox rollback <file>`
Если ИИ написал что-то не то или сломал файл — верни всё как было одной командой!
```bash
agentbox rollback src/main.py
```

---

## 7. Тихий запуск тестов, сборки и скриптов

### `agentbox run "<command>"`
Запускает команду «тихо». Если команда завершилась успешно, она не засоряет экран простынями логов, а выводит компактную строку с временем выполнения. 
Если команда упала — выводит последние строки ошибки.

```bash
agentbox run "python -m build"
```
*Успех (всего ~40 токенов):*
```text
OK [exit 0, 4.15s] Log: /tmp/agent_logs/task_123456.log
```
*Ошибка (показывает только суть проблемы):*
```text
FAILED [exit 1, 2.30s] Log: /tmp/agent_logs/task_123456.log
--- Failure Tail (5 lines) ---
ModuleNotFoundError: No module named 'fastapi'
```

### `agentbox test "<test_command>"`
Умный раннер для тестов. Поддерживает `pytest`, `unittest`, `cargo test`, `pnpm check`, `vitest` и другие.
* Если все тесты прошли — выводит лаконичное: `OK (42 passed)`.
* Если хотя бы один тест упал — фильтрует шум и вырезает **точный traceback ошибки**.

```bash
agentbox test "pytest tests/"
```

### `agentbox py`
Быстрое и безопасное исполнение Python-кода внутри изолированного виртуального окружения проекта:
```bash
# Через Base64:
agentbox py --base64 aW1wb3J0IHN5czsgcHJpbnQoc3lzLnZlcnNpb24p

# Запуск файла с кодом:
agentbox py --file script.py
```

### `agentbox pip <args>`
Устанавливает пакеты строго внутри изолированного окружения `.agentbox/venv`:
```bash
agentbox pip install requests pydantic
agentbox pip list
```

---

## 8. Фоновые процессы на сервере

Часто нужно запустить долгий процесс (обучение модели, dev-сервер, миграцию базы данных), который должен продолжать работать, даже если ты отключился от SSH.

```bash
# 1. Запустить процесс в фоне:
agentbox spawn "python app.py"
# Вывод: SPAWNED: task_id=bg_849201 pid=4215 log=/tmp/agent_logs/bg_849201.log

# 2. Проверить, работает ли процесс:
agentbox status bg_849201
# Вывод: TASK: bg_849201 | Status: RUNNING | PID: 4215 | Runtime: 2m 10s

# 3. Посмотреть последние 50 строк логов:
agentbox logs bg_849201 -n 50

# Читать логи в реальном времени (как tail -f):
agentbox logs bg_849201 -f

# 4. Остановить фоновый процесс:
agentbox kill bg_849201
```

---

## 9. Экономный Git

Обычные команды git выводят слишком много шума (особенно если изменились lock-файлы или просто сдвинулись пробелы). Команды `agentbox git-*` оптимизированы специально под контекст ИИ.

### `agentbox git-status [path]`
Показывает изменённые файлы с лаконичными счётчиками добавленных и удалённых строк (`+строк, -строк`):
```bash
agentbox git-status
```
*Вывод (всего ~25 токенов):*
```text
=== GIT STATUS: 2 changed files ===
  M   src/auth.py (+12, -3)
  ??  tests/test_auth_new.py
```

### `agentbox diff [path] [--rev <rev>]`
Умный diff:
* Игнорирует изменения только в пробелах (`-w`).
* Автоматически пропускает шумные lock-файлы (`package-lock.json`, `Cargo.lock`, `poetry.lock`).
* Ограничивает длину вывода, чтобы не переполнять контекст.
```bash
agentbox diff src/auth.py
agentbox diff --rev HEAD~1
```

### `agentbox git-log [path] [-n N]`
История последних коммитов в одну строку на коммит:
```bash
agentbox git-log -n 5
```

### `agentbox git-view <file> [rev] [--start N --end M]`
Позволяет посмотреть кусок файла из любого прошлого коммита без скачивания всего репозитория или переключения веток:
```bash
agentbox git-view src/auth.py HEAD~1 --start 20 --end 45
```

### `agentbox git-fn-history <file> <function_name>`
Показывает, как конкретная функция менялась в прошлых коммитах:
```bash
agentbox git-fn-history src/auth.py verify_jwt -n 3
```

---

## 10. Синхронизация папок проекта (`agentbox sync`)

Двусторонняя синхронизация файлов между твоим компьютером и удалённым сервером на базе Rsync:

```bash
# Посмотреть, какие файлы изменились и готовы к синхронизации:
agentbox sync status -t dev

# Отправить локальные изменения на сервер:
agentbox sync push -t dev

# Проверить, что будет отправлено, без реальной записи (--dry-run):
agentbox sync push -t dev --dry-run

# Скачать изменения с сервера на локальный компьютер:
agentbox sync pull -t dev
```

---

## 11. Граф связей в проекте (`graphify`)

Если проект большой, ИИ сложно понять, как связаны модули, классы и сервисы. AgentBox интегрирован с анализатором архитектуры `graphify`:

```bash
# 1. Установить движок анализа на сервере или локально:
agentbox graphify-install

# 2. Построить граф архитектуры проекта:
agentbox graphify-build

# 3. Задать вопрос об архитектуре на человеческом языке (ответ займёт всего ~150 токенов):
agentbox graphify-query "Как устроена авторизация и работа с JWT токенами?"

# 4. Открыть интерактивную визуальную карту проекта в браузере:
agentbox graphify-open
```

---

## 12. Ускоритель удаленной работы (`agentbox daemon`)

Когда ты запускаешь команды на удалённом сервере через обычный SSH, на каждое подключение тратится по 0.5–1.5 секунды.

AgentBox автоматически поднимает легковесный фоновый процесс (Daemon Bridge), который держит соединение открытым. В результате удалённые команды выполняются за **2–5 миллисекунд**!

```bash
# Проверить статус активных соединений:
agentbox daemon status

# Остановить фоновый мост вручную:
agentbox daemon stop
```
*(При бездействии более 30 минут мост автоматически и безопасно завершает работу сам).*

---

## 13. Аналитика и статистика (`stats`, `audit`, `batch`)

### `agentbox stats`
Показывает красивую панель с подсчётом: сколько вызовов было сделано и сколько тысяч токенов AgentBox сэкономил тебе за время работы:
```bash
agentbox stats
```

### `agentbox audit`
Журнал действий агента: какие команды запускались чаще всего, где возникали ошибки и на чём агент тратил больше всего времени:
```bash
agentbox audit -n 20
```

### `agentbox batch`
Позволяет передать сразу пачку действий в одном запросе, чтобы агент выполнил их подряд за один шаг диалога.

---

## 💡 Шпаргалка: С чего начать новичку?

1. Установи: `pip install ai-agentbox`
2. Создай конфиг серверов в `.agentbox.json` (или работай локально).
3. Запусти `agentbox rules` — всё! Твой ИИ готов к бережной и быстрой работе.
