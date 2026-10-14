# 🚀 Деплой на metatronti.com

Файлы готовы к хостингу: standalone HTML с `<meta viewport>` (мобильный включается),
кириллический Onest/IBM Plex через Google Fonts, картинок нет — грузится мгновенно.

## Файлы
| Файл | Куда | Что |
|---|---|---|
| `index.html` | **корень** metatronti.com | ЛЕНДИНГ — холодная дверь, «понятно за один раз» |
| `moment.html` | metatronti.com/moment | демо-разбор дня (вкладки под замком по подписке) |

## Шаги (Cloudflare Pages — бесплатно, уже есть аккаунт)
1. Cloudflare → **Pages** → Create → Direct Upload (или подключить этот репозиторий, корень сборки = `docs/product/deploy`).
2. Залить `index.html` и `moment.html`.
3. Custom domains → **metatronti.com** → привязать к проекту Pages.
4. `/moment` → откроется как `metatronti.com/moment.html` (или настроить чистый путь `/moment` редиректом).

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
