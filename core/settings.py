# extendo — the user's own knob positions, persisted (2026-07-18, user: "по
# настройкам которые выставлены на крутилках предлагаю запоминать значение на
# котором стоит и даже после полного закрытия программы открывать с ними же —
# чтоб всё хранилось где-то конкретно"). One concrete file, data/settings.json,
# next to corpus.json/stats.jsonl — not browser localStorage: extendo runs in a
# pywebview window whose storage is opaque and per-machine-profile, so "somewhere
# concrete" means a file the user can actually open, back up, and delete.
#
# NOT analytics: stats.py already records what the knobs WERE on every run, for
# analysis. That log is append-only history; this is one live value per knob —
# two different questions ("where did he work over 125 runs" vs "where is the
# slider right now"), so they stay two files rather than one clever one.
#
# Validation is clean.knobs()'s job, not this module's (PRINCIPLES §6: one
# source of truth) — read() returns whatever was stored, api/server.py runs it
# through clean.knobs() before it reaches the domain, exactly like a slider
# value arriving from the UI. A hand-edited or stale-schema file therefore
# can't inject a bad knob; it just gets clamped/defaulted like any input.

from __future__ import annotations

import json
import os

import склад

import clean

import пути

DATA_DIR = пути.ДАННЫЕ
SETTINGS_PATH = DATA_DIR / "settings.json"

# Only what the settings PANEL owns. Deliberately not the theme: that's the
# content being worked on, not a setting — reopening on yesterday's theme
# would be a surprise, reopening with yesterday's sliders is the ask.
#
# `stanza`/`stanza_profile` replaced the plain `rhyme`/`custom_raw`/
# `custom_mode` string-scheme keys (2026-07-18, PLAN.md 0.7 — the stanza
# constructor). An old settings.json on the user's own disk with the
# retired keys just has them silently dropped by `read()`'s _ALLOWED
# filter — a graceful no-op transition, not a migration that needs writing.
# `nl_chain_profiles`/`nl_smart_folders` (2026-07-31, фаза 0 nakedlunch v2) —
# профили цепочек пайплайна и умные папки листов: чисто интерфейсные структуры,
# сервер их не интерпретирует, поэтому и не валидирует — хранит как есть.
# `nl_fs_profiles`/`nl_ui_profiles`/`nl_palette`/`nl_view` (2026-08-01, фаза 3) —
# профили сцены фристайла, профили вида, палитра и текущие настройки вида.
# Дизайн клал их в localStorage; решение раунда 26 действует и здесь: хранилище
# окна непрозрачно и привязано к машине, всё живёт конкретными файлами рядом
# с corpus.json.
# `nl_params` (2026-08-02) — положения крутилок в КООРДИНАТАХ ИНТЕРФЕЙСА
# («Источники», «Банальность», «Диссонанс», …). Отдельно от `knobs`, где лежат
# координаты ядра (real_text/banality/cohesion, часть шкал инвертирована):
# сводить их в один ключ значило бы гонять значение туда-обратно через
# инверсии при каждом чтении и однажды ошибиться знаком.
# Раунд 50: `nl_chain_profiles` УБРАН. Полка цепочек переехала в свой файл
# data/chain_profiles.json с валидатором (core/chain_profiles.py) — как две
# соседние полки. Здесь она лежала сырьём и не проверялась ни на одном конце,
# а ключ проходил ДВА независимых белых списка (роут и этот), и пропуск в
# любом молча съедал запись. Старое значение из чужого settings.json просто
# отфильтруется на чтении — миграция не нужна, сохранённых цепочек не было.
# `nl_chain` (Раунд 55) — ЖИВАЯ цепочка меню «Пайплайн»: где закрыл, там
# открыл. Крутилки и каркас восстанавливались с Раунда 26, а цепочка нет:
# собрал шесть звеньев, закрыл окно — и всё пропало, если не положил её на
# полку руками. Полка при этом остаётся полкой: там СЛЕПКИ, сохранённые
# осознанно; здесь то, что стоит в меню прямо сейчас, как и положения
# ползунков рядом. Не валидируется тут по той же причине, что и остальное:
# имена форм и профилей — подписи полок, а не значения домена, и всё, что
# едет в генерацию, проходит clean на входе.
_ALLOWED = {"nl_params", "nl_chain", "stanza", "stanza_profile",
            "nl_smart_folders", "nl_fs_profiles", "nl_ui_profiles", "nl_palette", "nl_view"}


def _nl_params(raw) -> dict:
    """`nl_params` → КАНОН имён крутилок (Раунд 52).

    Здесь единственное исключение из правила «валидация — дело clean.knobs, а
    этот модуль хранит как есть», и оно не нарушает §6, а как раз применяет
    его: имена и диапазоны берутся у `clean.knob_params`, своих правил тут
    нет. Разница в том, ЧТО именно чинится: значения и так клампятся на входе
    в домен, а вот ИМЕНА на диске не чинил никто.

    На машине пользователя это видно: в `nl_params` лежит «Разнообразие» —
    крутилка, вырезанная в Раунде 48, — и не лежат пять живых («Мат»,
    «Клаузула», «Диссонанс», «Связность», «Повтор»). Мёртвый ключ ездил в
    КАЖДОМ запросе генерации, где домен молча его выбрасывал.

    Классику НЕ обрезаем до `KNOB_CLASSIC`, в отличие от `knob_profile`: это
    не именованный профиль, а последние положения ПАНЕЛИ, и переключение в
    классику и обратно не должно стирать, где стояли ползунки."""
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode")
    return {"mode": mode if mode in clean.KNOB_MODES else clean.MODE_ALGO,
            "params": clean.knob_params(raw.get("params"))}


def _запасной():
    """Копия предыдущего состояния настроек. Правила записи живут в `склад` —
    здесь только имя файла, чтобы сообщения об ошибке остались прежними."""
    return склад.копия(SETTINGS_PATH)


def _сырой_файл() -> str | None:
    """Текст файла настроек, или None если его нет / он не читается.

    Отличать «файла нет» от «файл есть, но прочитать не смог» нужно ровно в
    одном месте — в `write()`: во втором случае писать поверх нельзя."""
    try:
        return SETTINGS_PATH.read_text("utf-8")
    except OSError:
        return None


def read() -> dict:
    """Stored settings, or {} if never saved / unreadable. Never raises: a
    corrupt settings file must not stop the app from opening — the user
    loses his slider positions, which is annoying, not fatal (unlike
    corpus.py, which DOES hard-fail on a corrupt corpus.json: that's his
    actual data, and silently starting empty there could lose favorites)."""
    try:
        data = json.loads(SETTINGS_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {k: v for k, v in data.items() if k in _ALLOWED}
    if "nl_params" in out:
        out["nl_params"] = _nl_params(out["nl_params"])
    return out


def write(payload: dict) -> dict:
    """Merge `payload` into the stored settings and persist. Merge, not
    replace: the UI saves the whole panel at once today, but a partial save
    from anywhere else must not silently wipe the keys it didn't mention.

    ЧУЖОЙ КЛЮЧ — ОШИБКА, А НЕ ТИШИНА (Раунд 54). Раньше он молча выпадал, и
    это стоило дорого: перенос истории из CLI писал сюда свою отметку
    «сделано», ключа не было в белом списке, отметка исчезала — и «одноразовый»
    перенос отработал десять раз, по разу на каждый запуск, каждый раз таща
    550 МБ корпуса ДО открытия порта. Ровно та ловушка, что уже описана в
    /api/settings: «фильтра два, и второй молча съедал ключ, пропущенный в
    первом».

    Ругаемся только на ЗАПИСИ. На чтении фильтр остаётся тихим намеренно:
    там источник — файл на диске, где вполне законно лежат ключи, вырезанные
    в прошлых раундах, и падать из-за них значило бы не открыть программу."""
    чужие = sorted(set(payload or {}) - _ALLOWED)
    if чужие:
        raise ValueError(f"settings.write: ключи не из белого списка {чужие} — "
                         f"внеси их в _ALLOWED или храни в своём файле")
    # СЛИЯНИЕ С ПУСТОТОЙ — ЭТО НЕ СЛИЯНИЕ, А СТИРАНИЕ (Раунд 57).
    #
    # 2026-08-05 пользователь потерял ВСЕ профили сцены фристайла: в файле остался
    # один ключ `nl_view`, записанный последним. Механизм ровно здесь. `read()`
    # намеренно молчалив — на нечитаемом файле он возвращает `{}`, чтобы
    # программа всё-таки открылась. Но `write()` сливал payload именно в этот
    # `{}` и записывал результат поверх. То есть ОДНО неудачное чтение —
    # недописанный файл, гонка двух процессов, что угодно — превращалось в
    # безвозвратную потерю всего, что в payload не упомянуто.
    #
    # Тишина уместна на чтении и недопустима на записи: там источник — файл на
    # диске, и «не смог прочитать» означает «не знаю, что там», а не «там
    # пусто». Записывать поверх того, чего не знаешь, нельзя.
    сырой = _сырой_файл()
    есть_текст = сырой is not None and сырой.strip() != ""
    целый = False
    if есть_текст:
        try:
            целый = isinstance(json.loads(сырой), dict)
        except ValueError:
            целый = False
    if есть_текст and not целый:
        raise ValueError(
            "settings.write: файл настроек есть, но не разбирается — запись "
            "отменена, чтобы не стереть то, чего не видно. Почини или убери "
            f"{SETTINGS_PATH}; копия предыдущего состояния: {_запасной()}")
    current = read()
    current.update({k: v for k, v in (payload or {}).items() if k in _ALLOWED})
    if "nl_params" in current:
        # чиним и на записи: иначе старый файл лечился бы только в памяти, а на
        # диске мёртвый ключ жил бы дальше
        current["nl_params"] = _nl_params(current["nl_params"])
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    текст = json.dumps(current, ensure_ascii=False, indent=1)
    # ЗАПИСЬ ЦЕЛИКОМ ИЛИ НИКАК. `write_text` открывает файл на усечение и потом
    # пишет: прерваться между этими шагами — значит оставить на диске обрубок,
    # который следующее чтение примет за пустые настройки (см. выше). Пишем во
    # временный файл рядом и подменяем одним системным вызовом.
    врем = SETTINGS_PATH.with_suffix(".json.новый")
    врем.write_text(текст, "utf-8")
    # Копия ПРЕДЫДУЩЕГО состояния — на случай, когда обрубок всё-таки случится
    # не у нас (правка руками, другой процесс). Стоит один файл на диске.
    if сырой:
        try:
            _запасной().write_text(сырой, "utf-8")
        except OSError:
            pass            # копия — удобство, а не обязанность
    os.replace(врем, SETTINGS_PATH)
    return current
