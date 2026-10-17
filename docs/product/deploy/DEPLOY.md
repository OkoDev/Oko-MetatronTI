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
- **Терминал и Command Center** публикуются через туннель только на время показа и закрываются входом
  (Cloudflare Access). Адреса, состав туннеля и статус защиты — в auto-memory (`tunnel_public_domain_guard_1210`),
  **не в git**: репозиторий уже дважды менял видимость.
- Кидаешь людям **metatronti.com** (лендинг) и, кто заинтересовался, **/moment**. Терминал — только себе.

## Позже (НЕ блокирует первый показ)
- **Трекинг:** в `index.html` трекинг пишет локально (демо). Для реальной статистики — раскомментировать
  `navigator.sendBeacon('/collect', …)` и завести endpoint (PostHog/Umami, EU-хостинг, free). См. `landing.md`.
- **«Ранний доступ»:** сейчас кнопки — якоря на секции. Для захвата email — форма (Tally.so / Google Form) или TG.
- **/moment — два источника данных у одной страницы (17.10):**
  - `metatronti.com/moment` (Pages) — сохранённый снимок `agenda.json` с `live:false` → бейдж «пример · живые данные —
    при демонстрации». Обновить пример: `python scripts/moment_snapshot.py` → коммит → `bash scripts/deploy_web.sh`.
  - путь `/moment` на поддомене терминала (через туннель) — живые данные с локальной машины (`live:true`),
    только пока туннель включён. Туннель включать на время показа.
  - Постоянный поток для всех — уже в редизайне на сервере (stack.md, фазы 2–3).

## Обновление
Файлы собираются из артефактов-прототипов (claude.ai). При правке — пересобрать standalone тем же
оборачиванием (`<!doctype>…<head><meta viewport></head><body>` + контент + `</body></html>`).
