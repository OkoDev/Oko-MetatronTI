# metatronti.com

Публичная витрина [Metatron Trading Intelligence](https://metatronti.com).

## Структура
```
index.html          → metatronti.com/
moment/index.html   → metatronti.com/moment/
```

## Деплой
Cloudflare Pages — auto-deploy по пушу в `main`. Корень сборки = корень репо.

## Трекинг
Встроенный слой аналитики пишет события локально (localStorage).
Панель видна только по `?debug=1`. В проде заменить на `navigator.sendBeacon('/collect', …)`.

## Лицензия
© 2026 Metatron Trading Intelligence. Все права защищены.
