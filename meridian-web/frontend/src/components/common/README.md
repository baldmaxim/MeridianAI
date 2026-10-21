# Анимации портала — transitions.dev

Единственный стандарт анимаций Meridian. Это **не npm-пакет**, а набор portable CSS-переходов (copy-paste, в стиле shadcn). Источник сниппетов — скил [`.agents/skills/transitions-dev/`](../../../../../.agents/skills/transitions-dev/) (verbatim). Все классы под префиксом `t-*`, токены в `:root`, у каждого перехода есть `@media (prefers-reduced-motion: reduce)`.

- CSS: [`src/styles/transitions.css`](../../styles/transitions.css) — подключается один раз в [`main.tsx`](../../main.tsx) после `index.css`.
- React-обёртки: этот каталог (`components/common/`).
- Хуки: [`hooks/useExitTransition.ts`](../../hooks/useExitTransition.ts), [`hooks/useOpenClose.ts`](../../hooks/useOpenClose.ts), [`hooks/useErrorShake.ts`](../../hooks/useErrorShake.ts).

## Что для чего (decision rules)

| Ситуация в UI | Компонент / класс | transitions.dev |
|---|---|---|
| Диалог по центру поверх backdrop | `<Modal>` | 06 modal |
| Меню/поповер из триггера | `<Dropdown>` или `useOpenClose` + `t-dropdown` | 05 menu-dropdown |
| Выбор из списка (замена `<select>`) | `<Select>` | 05 menu-dropdown |
| Свободный ввод + подсказки (замена `<input list>`/`<datalist>`) | `<Combobox>` | 05 menu-dropdown |
| Панель/шторка выезжает в область | `t-panel-slide` + `useExitTransition` | 07 panel-reveal |
| Смена роута (вход страницы) | `<PageTransition>` | 08 (производное, enter-only) |
| Список ↔ деталь side-by-side | `t-page-slide` / `t-page` | 08 page-side-by-side |
| Меняется ширина/высота контейнера | `<CardResize>` / `t-resize` | 01 card-resize |
| Число обновилось | `<PopNumber>` | 02 number-pop-in |
| Текст меняется на месте | `<TextSwap>` | 04 text-states-swap |
| Два значка в одном слоте | `<IconSwap>` | 09 icon-swap |
| Маленькая точка-бейдж на триггере | `<NotificationBadge>` | 03 notification-badge |
| Момент «готово»/успех (чек) | `<SuccessCheck>` | 10 success-check |
| Ряд аватаров/чипов на hover | `<AvatarGroup>` | 11 avatar-group-hover |
| Ошибка валидации формы | `useErrorShake` + класс `t-input` | 12 error-state-shake |

Если два перехода подходят — выбирай более лёгкий (card-resize вместо panel-reveal, dropdown вместо modal).

## Мини-примеры

```tsx
import { Modal, Dropdown, IconSwap, SuccessCheck, PopNumber } from '../common';
import { useErrorShake } from '../../hooks/useErrorShake';

// Modal — вход/выход без срезания exit-анимации (держи смонтированным, управляй open)
<Modal open={show} onClose={() => setShow(false)} maxWidth={460}>…</Modal>

// Dropdown — origin-aware, закрытие по клику вне и Esc
<Dropdown open={open} onClose={close} origin="top-right"
          style={{ position:'absolute', top:40, right:0 }}>…</Dropdown>

// IconSwap — кросс-фейд двух глифов/иконок
<IconSwap state={open ? 'b' : 'a'} a="▼" b="▲" />

// SuccessCheck — рисующийся чек на «готово»
<SuccessCheck show={saved} size={14} color="var(--on-accent)" />

// PopNumber — ре-вход цифр при смене значения
<PopNumber value={count} />

// Error shake — bump shakeKey на каждую неудачу
const [shakeKey, setShakeKey] = useState(0);
const formRef = useErrorShake<HTMLFormElement>(shakeKey);
<form ref={formRef} className="t-input">…</form>
```

## TextInput — поле с крестиком «Очистить»

Правило проекта: каждое текстовое поле (текст, поиск, логин, пароль, e-mail, телефон, число) — с кнопкой «×». Использовать `TextInput` вместо голого `<input>`; стили — `TextInput.module.css` (только токены темы).

```tsx
import { TextInput } from '../common';

<TextInput
  type="email"
  value={email}
  onChange={(e) => setEmail(e.target.value)}
  onClear={() => setEmail('')}   // необязательно: без него поле очищается нативно + событие input
  clearLabel="email"             // aria-label: «Очистить email» (по умолчанию «Очистить поле»)
  className="…"                  // класс обёртки
  inputClassName="…"             // класс самого <input>
/>
```

- «×» виден только у непустого поля, не у `disabled`/`readOnly`; кнопка `type="button"`, 44×44 px, справа внутри поля; у input есть `padding-right`, текст под неё не заходит.
- После очистки фокус остаётся в поле; `forwardRef` отдаёт ref на `<input>`; остальные пропсы `<input>` пробрасываются как есть.
- Системные крестики (`type="search"` webkit, `::-ms-clear`, `::-ms-reveal`) скрыты — свой один на все браузеры.
- `font-size` 16px на мобильных (нет авто-зума Safari), 14px от 768px.

## Правила

- Не добавлять motion-библиотеки (framer-motion и т.п.) — стандарт чисто CSS.
- Не заменять перечисленные `transition: …` на `transition: all`.
- Сохранять `@media (prefers-reduced-motion: reduce)` в каждом сниппете.
- Тюнинг — только через токены в `:root` (`transitions.css`), не хардкодить длительности в JS.
- Новые переходы из каталога — копировать из скила **verbatim**, не переписывать селекторы.
- Скил триггерится на фразы «добавь переход», «анимируй дропдаун», «success animation»; команды: `transitions reveal` / `transitions review` / `transitions apply`.

## Select / SearchableSelect / Combobox — стили без inline

- `triggerClassName` (Select, SearchableSelect) — класс кнопки-триггера, `inputClassName` (Combobox) — класс самого `<input>`; `className` — на обёртку. Старые `style`/`wrapperStyle` остаются для обратной совместимости.
- Общие стили меню/опций — `SelectShared.module.css` (только токены темы). Базовый вид `TextInput` обёрнут в `:where()` — класс вызывающего кода всегда перебивает его, порядок загрузки CSS не важен.
