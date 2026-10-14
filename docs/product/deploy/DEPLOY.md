# 🚀 Деплой на metatronti.com

Файлы готовы к хостингу: standalone HTML с `<meta viewport>` (мобильный включается),
кириллический Onest/IBM Plex через Google Fonts, картинок нет — грузится мгновенно.

## Файлы (структура `public/` = корень сайта)
| Файл | URL | Что |
|---|---|---|
| `public/index.html` | metatronti.com/ | ЛЕНДИНГ — холодная дверь, «понятно за один раз» |
| `public/moment/index.html` | metatronti.com/moment/ | демо-разбор дня (вкладки под замком по подписке) |

Папка-роутер: каждый `index.html` в своей папке даёт чистый путь без `.html` и без редиректов.
Связность страниц: лендинг → `/moment/` (hero, тур, тариф Observer); /moment шапка → `/` и `/#pricing`.

## Шаги (Cloudflare Pages — бесплатно, уже есть аккаунт)
1. Cloudflare → **Pages** → Create → подключить репозиторий (см. ниже про отдельный web-репо), **корень сборки (output) = `public`**, build command пустой (статика).
2. Custom domains → **metatronti.com** → привязать к проекту Pages.
3. Пуш в ветку деплоя → Pages пересобирает сам. Больше не перезаливать руками.

## 🔁 Отдельный репозиторий для web (настроено 15.10)
Репо: **https://github.com/OkoDev/metatronti-web** — зеркало `docs/product/deploy/public/`.
Remote `web` уже добавлен в основном проекте.

**Деплой (одна команда):**
```bash
bash scripts/deploy_web.sh
# или вручную:
git subtree push --prefix=docs/product/deploy/public web main
```
Cloudflare Pages подхватывает пуш в `main` автоматически.

**Порядок работы:**
1. Правишь файлы в `docs/product/deploy/public/` (основной проект)
2. Коммитишь в основной проект (ветка `product-gtm`)
3. `bash scripts/deploy_web.sh` → public/ улетает в `metatronti-web` → Pages деплоит
4. Первый push долгий (перебор истории), последующие — секунды

- Трекинг-панель скрыта в проде, видна только по `?debug=1` (класс `html.dbg`).
- Основной проект к Pages НЕ подключаем (приватный, с БД и ключами).

## 🔴 ДО того, как кидать ссылку людям
- **metatronti.com → ЛЕНДИНГ** (эти файлы), НЕ терминал. Холодный человек видит дверь, не кабину.
- **app.metatronti.com → терминал** (кабина) — включить **Cloudflare Access** (вход по коду на почту).
  Сейчас чтение открыто всем: журнал волн, скринер, форвард-табло. См. память `tunnel_public_domain_guard_1210`.
- **cmd.metatronti.com → Command Center** — тоже за Access.
- Кидаешь людям **metatronti.com** (лендинг) и, кто заинтересовался, **/moment**. app/cmd — только себе.

## Позже (НЕ блокирует первый показ)
- **Трекинг:** в `index.html` трекинг пишет локально (демо). Для реальной статистики — раскомментировать
  `navigator.sendBeacon('/collect', …)` и завести endpoint (PostHog/Umami, EU-хостинг, free). См. `landing.md`.
- **«Ранний доступ»:** сейчас кнопки — якоря на секции. Для захвата email — форма (Tally.so / Google Form) или TG.
- **Числа на /moment** помечены «демо · пример». Когда будет живой публичный источник — подставить реальные.

## Обновление
Файлы собираются из артефактов-прототипов (claude.ai). При правке — пересобрать standalone тем же
оборачиванием (`<!doctype>…<head><meta viewport></head><body>` + контент + `</body></html>`).
