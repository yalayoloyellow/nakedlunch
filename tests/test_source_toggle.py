# extendo — переключение книги не должно переписывать полгига (Раунд 56).
#
# Отчёт (2026-08-05): после нажатия «отключить книгу» непонятно, отключилась ли
# она, и иногда она не отключается.
#
# Причина была одна на обе жалобы: `toggle_active` звал `_save(full=True)`, то
# есть перезапись ВСЕГО state.json ради одного булева. На рабочем корпусе это
# 549 МБ — десятки секунд, за которые в интерфейсе не менялось ничего, и за это
# время следовало второе нажатие, переключавшее книгу обратно.
#
# Здесь сторожим бэкенд: флаг живёт своим маленьким файлом, тяжёлый не
# трогается, и после перезагрузки стора флаг тот, что поставили.
# Прогон: .venv/bin/python -m pytest tests/test_source_toggle.py -q

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from nlsrc.store import NakedLunchStore


def завести(tmp_path):
    s = NakedLunchStore(tmp_path)
    s.add_corpus("книга", "Стояла зима. Мороз был крепок. " * 40)
    return s


def test_pereklyuchenie_ne_trogaet_tyazhelyi_fail(tmp_path):
    """Тяжёлый state.json при переключении не переписывается вовсе."""
    s = завести(tmp_path)
    cid = s.state.corpora[0].id
    было = s.state_path.stat().st_mtime_ns, s.state_path.stat().st_size
    s.toggle_active(cid)
    стало = s.state_path.stat().st_mtime_ns, s.state_path.stat().st_size
    assert стало == было, "переключение книги переписало state.json"
    assert s.active_path.exists(), "флаг активности некуда было записать"
    # и файл флагов ДОЛЖЕН быть маленьким — иначе смысл потерян
    assert s.active_path.stat().st_size < 4096


def test_flag_perezhivaet_perezagruzku(tmp_path):
    """Выключил книгу — после перезапуска она выключена."""
    s = завести(tmp_path)
    cid = s.state.corpora[0].id
    assert s.get_corpus(cid).active is True
    assert s.toggle_active(cid) is False
    assert s.get_active_pool() == []          # выключенная книга не даёт фрагментов

    свежий = NakedLunchStore(tmp_path)
    assert свежий.get_corpus(cid).active is False, "флаг не пережил перезагрузку"
    assert свежий.get_active_pool() == []


def test_vklyuchil_obratno_fragmenty_vernulis(tmp_path):
    s = завести(tmp_path)
    cid = s.state.corpora[0].id
    сколько = len(s.get_active_pool())
    assert сколько > 0
    s.toggle_active(cid)
    s.toggle_active(cid)
    assert len(s.get_active_pool()) == сколько
    assert len(NakedLunchStore(tmp_path).get_active_pool()) == сколько


def test_tokeny_schitayutsya_lenivo(tmp_path):
    """Токены активных фрагментов — только по спросу.

    Их читает ровно один метод исходного CLI, а платились они на КАЖДОЙ смене
    состава активных книг: на корпусе пользователя это 2.87 млн вызовов регулярки
    и столько же множеств в памяти, каждый раз заново."""
    s = завести(tmp_path)
    assert s._active_frag_tokens is None, "токены посчитаны, хотя никто не спрашивал"
    s.toggle_active(s.state.corpora[0].id)
    assert s._active_frag_tokens is None
    n = len(s._frag_tokens())                  # спросили — посчитались
    assert s._active_frag_tokens is not None and n == len(s._active_fragments)


def test_polnaya_zapis_ostayotsya_gde_nuzhna(tmp_path):
    """Залив и удаление книги состав фрагментов МЕНЯЮТ — там полная запись
    обязана происходить, иначе после перезапуска книги бы не было."""
    s = завести(tmp_path)
    было = s.state_path.stat().st_size
    s.add_corpus("вторая", "Другой совсем текст про лето и жару. " * 40)
    assert s.state_path.stat().st_size > было, "залив книги не дошёл до диска"
    assert len(NakedLunchStore(tmp_path).state.corpora) == 2


# ---------------------------------------------------------------------------
# ФРОНТ: отклик без ложного промежуточного состава
#
# Бэкенд быстрый, а интерфейс подтверждает клик занятостью строки. Активную
# точку до ответа менять нельзя: она входит в ключ префетча, и оптимистичное
# состояние могло принять строки, которые сервер ещё собрал из старого пула.
# Проверяем настоящий модуль с подменённой сетью и React-оболочкой.
# ---------------------------------------------------------------------------

import json
import io
import shutil
import subprocess
import threading
import time

import pytest

КОРПУС_JS = ROOT / "interface" / "react-app" / "src" / "nl" / "methods.corpus.js"


def node(тело: str):
    if shutil.which("node") is None:
        pytest.skip("node не установлен")
    src = f"import {{ corpusMethods }} from '{КОРПУС_JS.as_uri()}';\n{тело}"
    # ВЫВОД ДЕКОДИРУЕМ САМИ, В UTF-8 (Раунд 61). При text=True питон берёт
    # кодировку локали, и на Windows кириллица из node приходила мойбейком —
    # поймано первым же прогоном тестов на трёх системах. node печатает UTF-8
    # всегда, гадать тут нечего.
    p = subprocess.run(["node", "--input-type=module", "-e", src],
                       capture_output=True, timeout=60)
    вывод = (p.stdout or b"").decode("utf-8", "replace")
    ошибки = (p.stderr or b"").decode("utf-8", "replace")
    assert p.returncode == 0, f"node упал:\n{ошибки}"
    assert вывод.strip(), f"node ничего не напечатал. stderr:\n{ошибки}"
    return json.loads(вывод)


ОСНОВА = """
// Настоящий api.js ходит через fetch — его и подменяем, а не проверяемую
// функцию. Ответ НАРОЧНО медленный: весь смысл правки в том, что интерфейс
// ещё не ответил.
const шаги = [];
let серверОтветил = false;
globalThis.fetch = (url, opts) => new Promise(r => setTimeout(() => {
  серверОтветил = true;
  r({ ok: true, status: 200, json: async () => ({
    sources: [{ id: 'a', active: false }, { id: 'b', active: false }] }) });
}, 120));

function макет() {
  const c = Object.assign({}, corpusMethods);
  c.state = { srcBusy: {}, nl: { sources: [{ id: 'a', active: true }, { id: 'b', active: false }] } };
  c.setState = function (p) {
    Object.assign(this.state, p);
    шаги.push(((this.state.nl || {}).sources || []).map(s => s.id + ':' + (s.active ? 1 : 0)).join(' '));
  };
  c.flash = function (m) { шаги.push('flash:' + m); };
  c.reloadNl = function () {};
  return c;
}
"""


def test_do_otveta_servera_menyaetsya_tolko_zanyatost():
    """До подтверждения состав прежний, но клик уже виден как занятость."""
    out = node(ОСНОВА + """
    const c = макет();
    const p = c.toggleSource('a');
    const сразу = ((c.state.nl || {}).sources || []).map(s => s.id + ':' + (s.active ? 1 : 0)).join(' ');
    const занятоСразу = !!c.state.srcBusy.a, серверМолчал = !серверОтветил;
    p.then(() => console.log(JSON.stringify({
      сразу, занятоСразу, серверМолчал, серверОтветилПотом: серверОтветил,
      итог: ((c.state.nl || {}).sources || []).map(s => s.id + ':' + (s.active ? 1 : 0)).join(' '),
      занятоСнято: Object.keys(c.state.srcBusy || {}).length === 0 })));
    """)
    assert out["сразу"] == "a:1 b:0", "неподтверждённый состав попал в состояние"
    assert out["занятоСразу"] is True, "клик не получил мгновенного отклика"
    assert out["серверМолчал"] is True, "сервер успел ответить — проверка не о том"
    assert out["серверОтветилПотом"] is True and out["итог"] == "a:0 b:0"
    assert out["занятоСнято"] is True, "строка осталась занятой навсегда"


def test_otkaz_servera_ne_menyaet_tochku_i_soobshchaet_prichinu():
    """Сервер отказал — состав остаётся прежним, причина видна."""
    out = node(ОСНОВА + """
    globalThis.fetch = async () => ({ ok: false, status: 404,
      json: async () => ({ error: 'источник не найден' }) });
    const c = макет();
    c.toggleSource('a').then(() => console.log(JSON.stringify({
      итог: ((c.state.nl || {}).sources || []).map(s => s.id + ':' + (s.active ? 1 : 0)).join(' '),
      сказал: шаги.filter(x => String(x).startsWith('flash:')) })));
    """)
    assert out["итог"] == "a:1 b:0", "после отказа точка не вернулась на место"
    assert out["сказал"] and "не найден" in out["сказал"][0]


def test_vtoroy_klik_vo_vremya_pohoda_ne_schitaetsya():
    """Пока идёт первый запрос, второй клик игнорируется — иначе книга
    переключалась бы обратно — ровно то, что в отчёте выглядело как «иногда
    не отключается»."""
    out = node(ОСНОВА + """
    const c = макет();
    c.state.srcBusy = { a: 1 };
    const до = JSON.stringify(c.state.nl.sources);
    Promise.resolve(c.toggleSource('a')).then(() => console.log(JSON.stringify({
      неТронуто: JSON.stringify(c.state.nl.sources) === до, шагов: шаги.length })));
    """)
    assert out["неТронуто"] is True and out["шагов"] == 0


def test_zavershenie_chistki_i_indeksa_obnovlyaet_reviziyu_korpusa():
    """Окончание работ перечитывает /nl/state ровно один раз за тик."""
    out = node("""
    globalThis.window = {};
    globalThis.fetch = async url => {
      if (String(url) !== '/api/status') throw new Error('лишний URL: ' + url);
      return { ok: true, status: 200, json: async () => ({
        items: [
          { id: 'clean', state: 'done' },
          { id: 'nl_index', state: 'done' },
        ],
        generation: null, ошибок: 0, аварийно: false,
      }) };
    };
    const c = Object.assign({}, corpusMethods);
    c.state = {
      jobs: [
        { id: 'clean', state: 'running' },
        { id: 'nl_index', state: 'running' },
      ],
      genState: 'idle', srcBusy: {}, логОшибок: 0,
    };
    c._mounted = true;
    c._statusDead = false;
    c.setState = function (patch) { Object.assign(this.state, patch || {}); };
    let перечитано = 0, пауза = 0;
    c.reloadNl = function () { перечитано += 1; };
    c.statusSchedule = function (ms) { пауза = ms; };
    await c.statusTick();
    console.log(JSON.stringify({
      перечитано, пауза,
      состояния: c.state.jobs.map(j => j.state),
    }));
    """)
    assert out["перечитано"] == 1
    assert out["состояния"] == ["done", "done"]
    assert out["пауза"] > 0


# ---------------------------------------------------------------------------
# ЗАЛИВКА ФОНОМ (Раунд 56, шаг 3)
# ---------------------------------------------------------------------------

def test_pachka_knig_pishet_korpus_odin_raz(tmp_path):
    """Пять книг — ОДНА полная запись, а не пять.

    state.json на корпусе пользователя весит 549 МБ. `add_corpus` писал его сам,
    то есть заливка пачки платила эту цену за каждый файл. Теперь вызывающий
    копит и делает `flush()` один раз в конце."""
    s = NakedLunchStore(tmp_path)
    s.add_corpus("первая", "Текст про зиму и снег. " * 40)
    записей = []
    настоящий = s._save

    def считать(full=False):
        if full:
            записей.append(1)
        настоящий(full=full)

    s._save = считать
    # БЕЗ ЦИФР В ТЕКСТЕ: с 2026-08-21 фрагмент с цифрой выбрасывается
    # (см. `cutter.есть_цифра`), и прежнее «Разный текст номер 3 про лето»
    # вымирало целиком — `add_corpus` падал на «нечего нарезать».
    приметы = ["ясное", "мутное", "долгое", "краткое", "тихое"]
    for i, примета in enumerate(приметы):
        s.add_corpus(f"книга {i}",
                     f"Разный текст про {примета} лето и его дела. " * 40, save=False)
    assert записей == [], "заливка с save=False всё равно писала корпус"
    s.flush()
    assert len(записей) == 1
    assert len(NakedLunchStore(tmp_path).state.corpora) == 6


def test_shagi_zalivki_dohodyat_naruzhu(tmp_path):
    """Этапы доходят до вызывающего — иначе прогресс показывать нечем.

    Разбор имён идёт pymorphy3 по всему тексту книги и занимает большую часть
    времени: молчать на нём значит вернуть ровно ту жалобу, ради которой всё
    и делалось."""
    s = NakedLunchStore(tmp_path)
    этапы = []
    s.add_corpus("книга", "Стояла зима, и мороз был крепок. " * 40,
                 save=False, шаг=этапы.append)
    assert "разбираю имена" in этапы, f"этапа разбора имён нет: {этапы}"
    assert "режу на фрагменты" in этапы
    assert этапы.index("разбираю имена") < этапы.index("режу на фрагменты")


# ---------------------------------------------------------------------------
# ХОЛОДНЫЙ СКЛАД: МАЛЕНЬКИЙ active.json НЕ ДОЛЖЕН БУДИТЬ state.json
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def сервер_источников():
    """Настоящие Flask-функции без запуска порта."""
    sys.path.insert(0, str(ROOT / "api"))
    import server
    return server


@pytest.fixture
def холодный_стенд(сервер_источников, monkeypatch, tmp_path):
    """Две книги в маленьких файлах; тяжёлого state.json здесь нет вовсе."""
    сервер = сервер_источников
    склад = tmp_path / "склад"
    данные = tmp_path / "данные"
    склад.mkdir()
    данные.mkdir()
    книги = [
        {"id": "книга-а", "name": "Книга А", "type": "txt",
         "added_at": "2026-09-22T00:00:00Z", "fragment_count": 3},
        {"id": "книга-б", "name": "Книга Б", "type": "txt",
         "added_at": "2026-09-22T00:00:01Z", "fragment_count": 5},
    ]
    (данные / "книги.json").write_text(
        json.dumps({"книги": книги, "пул": 8}, ensure_ascii=False), "utf-8")
    active = склад / "active.json"
    active.write_text(
        json.dumps({"книга-а": True, "книга-б": True}, ensure_ascii=False),
        "utf-8",
    )

    monkeypatch.setattr(сервер.nlbridge, "NAKEDLUNCH_DATA", склад)
    monkeypatch.setattr(сервер.nlbridge.пути, "ДАННЫЕ", данные)
    monkeypatch.setattr(сервер.nlbridge, "ОПИСЬ", None)
    monkeypatch.setattr(сервер.nlbridge, "_STORE", None)
    monkeypatch.setattr(сервер.nlindex, "forget_pool", lambda: None)
    return сервер, склад, данные, active


def _склад_запрещён(сервер, monkeypatch):
    вызовы = []

    def нельзя(*_args, **_kwargs):
        вызовы.append("тяжёлый склад")
        raise AssertionError("лёгкий путь синхронно загрузил state.json")

    monkeypatch.setattr(сервер, "_nl", нельзя)
    monkeypatch.setattr(сервер.nlbridge, "open_store", нельзя)
    return вызовы


def _вызвать(сервер, путь, функция, json_data=None):
    with сервер.app.test_request_context(путь, method="POST", json=json_data):
        return функция()


def test_holodnoe_pereklyuchenie_pishet_active_i_otdaet_svezhiy_spisok(
    холодный_стенд, monkeypatch,
):
    """Клик меняет только active.json и не ждёт разбора тяжёлого склада."""
    сервер, склад, _данные, active = холодный_стенд
    вызовы = _склад_запрещён(сервер, monkeypatch)

    # Прогреваем именно опись: ответ после клика обязан сбросить старые флаги,
    # перечитать active.json и вернуть уже новое состояние.
    assert [к["active"] for к in сервер.nlbridge.опись_книг()] == [True, True]
    ответ = _вызвать(
        сервер, "/api/nl/source/toggle", сервер.api_nl_source_toggle,
        {"id": "книга-а"},
    )

    assert вызовы == []
    assert [(к["id"], к["active"]) for к in ответ["sources"]] == [
        ("книга-а", False), ("книга-б", True),
    ]
    assert json.loads(active.read_text("utf-8")) == {
        "книга-а": False, "книга-б": True,
    }
    assert active.stat().st_size < 4096
    assert not (склад / "state.json").exists()
    assert not list(склад.glob("active.json.*")), "рядом остался огрызок записи"


def test_uspeshnaya_zapis_ne_pereklyuchaetsya_vtoroy_raz_pri_sboe_opisi(
    холодный_стенд, monkeypatch,
):
    """После replace ответ строится из уже прочитанных данных.

    Повторное чтение могло вернуть None; роут принимал это за неудачу,
    загружал склад и инвертировал уже записанный флаг ещё раз.
    """
    сервер, _склад, _данные, active = холодный_стенд
    вызовы = _склад_запрещён(сервер, monkeypatch)
    настоящая_опись = сервер.nlbridge.опись_книг
    чтений = 0

    def исчезающая_опись():
        nonlocal чтений
        чтений += 1
        return настоящая_опись() if чтений == 1 else None

    monkeypatch.setattr(сервер.nlbridge, "опись_книг", исчезающая_опись)

    ответ = _вызвать(
        сервер, "/api/nl/source/toggle", сервер.api_nl_source_toggle,
        {"id": "книга-а"},
    )

    assert вызовы == []
    assert чтений == 1
    assert json.loads(active.read_text("utf-8"))["книга-а"] is False
    assert {к["id"]: к["active"] for к in ответ["sources"]}["книга-а"] is False


def test_goryachiy_store_poluchaet_to_zhe_active_sostoyanie(
    холодный_стенд, monkeypatch,
):
    """Если склад уже в памяти, быстрый клик не оставляет в нём старый флаг."""
    сервер, склад, _данные, active = холодный_стенд
    store = NakedLunchStore(склад)
    store.add_corpus("Книга А", "Стояла зима, и крепкий мороз звенел. " * 40)
    store.add_corpus("Книга Б", "Настало лето, и тёплый ветер шумел. " * 40)
    первая, вторая = store.state.corpora

    # В стенде заранее были условные id; заменяем маленькие файлы настоящими
    # id загруженного store, не обращаясь ни к каким пользовательским данным.
    active.write_text(json.dumps({первая.id: True, вторая.id: True}), "utf-8")
    сервер.nlbridge.записать_опись(store)
    monkeypatch.setattr(сервер.nlbridge, "_STORE", store)
    вызовы = _склад_запрещён(сервер, monkeypatch)
    было = len(store.get_active_pool())

    ответ = _вызвать(
        сервер, "/api/nl/source/toggle", сервер.api_nl_source_toggle,
        {"id": первая.id},
    )

    assert вызовы == []
    assert store.get_corpus(первая.id).active is False
    assert store.get_corpus(вторая.id).active is True
    assert len(store.get_active_pool()) < было
    assert json.loads(active.read_text("utf-8")) == {
        первая.id: False, вторая.id: True,
    }
    assert {к["id"]: к["active"] for к in ответ["sources"]} == {
        первая.id: False, вторая.id: True,
    }


def test_dva_odnovremennyh_pereklyucheniya_ne_teryayut_drug_druga(
    холодный_стенд, monkeypatch,
):
    """Read-modify-write active.json сериализован целиком, а не по записи."""
    сервер, склад, _данные, active = холодный_стенд
    _склад_запрещён(сервер, monkeypatch)
    настоящий_read_text = Path.read_text

    def медленное_чтение(путь, *args, **kwargs):
        текст = настоящий_read_text(путь, *args, **kwargs)
        # Без общего замка оба запроса успевают прочесть одно старое состояние
        # и последний replace затирает изменение соседа. Под замком задержка
        # безвредна: второй прочтёт уже результат первого.
        if путь == active:
            time.sleep(0.05)
        return текст

    monkeypatch.setattr(Path, "read_text", медленное_чтение)
    старт = threading.Barrier(3)
    ошибки = []

    def переключить(cid):
        try:
            старт.wait()
            _вызвать(
                сервер, "/api/nl/source/toggle", сервер.api_nl_source_toggle,
                {"id": cid},
            )
        except BaseException as e:                                  # noqa: BLE001
            ошибки.append(e)

    потоки = [threading.Thread(target=переключить, args=(cid,))
              for cid in ("книга-а", "книга-б")]
    for поток in потоки:
        поток.start()
    старт.wait()
    for поток in потоки:
        поток.join(5)

    assert all(not поток.is_alive() for поток in потоки), "переключение зависло"
    assert not ошибки, [repr(e) for e in ошибки]
    assert json.loads(active.read_text("utf-8")) == {
        "книга-а": False, "книга-б": False,
    }
    assert not list(склад.glob("active.json.*")), "атомарная запись оставила временный файл"


# ---------------------------------------------------------------------------
# ПОСТАНОВКА ФОНОВОЙ РАБОТЫ: СКЛАД НУЖЕН РАБОТНИКУ, НЕ HTTP-ЗАПРОСУ
# ---------------------------------------------------------------------------

class _НеЗапущенныйПоток:
    """Записывает постановку, но не выполняет тяжёлую работу."""

    созданные = []

    def __init__(self, target=None, args=(), **kwargs):
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.__class__.созданные.append(self)

    def start(self):
        self.started = True


class _ПроцессДвойник:
    def poll(self):
        return None


def test_open_dir_ne_gruzit_store(холодный_стенд, monkeypatch):
    сервер, _склад, _данные, _active = холодный_стенд
    вызовы = _склад_запрещён(сервер, monkeypatch)
    открыто = []
    папка = Path(сервер.nlbridge.NAKEDLUNCH_DATA).parent
    monkeypatch.setattr(сервер.nlbridge, "NAKEDLUNCH_PROG_DIR", папка)
    monkeypatch.setattr(subprocess, "run",
                        lambda команда, check=False: открыто.append((команда, check)))

    ответ = _вызвать(сервер, "/api/nl/open-dir", сервер.api_nl_open_dir)

    assert ответ == {"ok": True}
    assert вызовы == []
    assert открыто == [(["open", str(папка)], False)]


def test_index_stavitsya_v_fon_bez_zagruzki_store(холодный_стенд, monkeypatch):
    сервер, _склад, _данные, _active = холодный_стенд
    вызовы = _склад_запрещён(сервер, monkeypatch)
    запуски = []
    процесс = _ПроцессДвойник()
    monkeypatch.setattr(сервер, "_NL_INDEX_PROC", None)
    monkeypatch.setattr(сервер, "_лог_сборки", lambda _имя: io.BytesIO())
    monkeypatch.setattr(сервер.дочерний, "команда", lambda _имя: ["индекс"])
    monkeypatch.setattr(сервер.subprocess, "Popen",
                        lambda *args, **kwargs: запуски.append((args, kwargs)) or процесс)
    monkeypatch.setattr(сервер, "_после", lambda proc, callback: None)

    ответ = _вызвать(сервер, "/api/nl/index/run", сервер.api_nl_index_run)

    assert ответ == {"начали": True}
    assert вызовы == []
    assert len(запуски) == 1 and запуски[0][0][0] == ["индекс"]


def test_rhyme_stavitsya_v_fon_bez_zagruzki_store(
    холодный_стенд, monkeypatch, tmp_path,
):
    сервер, _склад, _данные, _active = холодный_стенд
    вызовы = _склад_запрещён(сервер, monkeypatch)
    запуски = []
    процесс = _ПроцессДвойник()
    monkeypatch.setattr(сервер, "_NL_RHYME_PROC", None)
    monkeypatch.setattr(сервер, "_NL_RHYME_STATUS_PATH", tmp_path / "нет-статуса.json")
    monkeypatch.setattr(сервер, "_лог_сборки", lambda _имя: io.BytesIO())
    monkeypatch.setattr(сервер.дочерний, "команда", lambda _имя: ["ударения"])
    monkeypatch.setattr(сервер.subprocess, "Popen",
                        lambda *args, **kwargs: запуски.append((args, kwargs)) or процесс)
    monkeypatch.setattr(сервер, "_после", lambda proc, callback: None)
    monkeypatch.setattr(сервер, "_проследить_за_сборкой", lambda proc: None)

    ответ = _вызвать(сервер, "/api/nl/rhyme/run", сервер.api_nl_rhyme_run)

    assert ответ == {"ok": True}
    assert вызовы == []
    assert len(запуски) == 1
    assert запуски[0][0][0] == ["ударения", "--full"]


@pytest.mark.parametrize("вид", ["индекс", "ударения"])
def test_dva_odnovremennyh_starta_sozdayut_odin_process(
    холодный_стенд, monkeypatch, tmp_path, вид,
):
    """Проверка busy и присваивание Popen составляют одну операцию."""
    сервер, _склад, _данные, _active = холодный_стенд
    процесс = _ПроцессДвойник()
    запуски = []
    monkeypatch.setattr(сервер, "_лог_сборки", lambda _имя: io.BytesIO())
    monkeypatch.setattr(сервер.дочерний, "команда", lambda имя: [имя])
    monkeypatch.setattr(сервер, "_после", lambda proc, callback: None)

    def медленный_popen(*args, **kwargs):
        time.sleep(0.05)
        запуски.append((args, kwargs))
        return процесс

    monkeypatch.setattr(сервер.subprocess, "Popen", медленный_popen)
    if вид == "индекс":
        monkeypatch.setattr(сервер, "_NL_INDEX_PROC", None)
        запустить = сервер._nl_index_ensure_running
    else:
        monkeypatch.setattr(сервер, "_NL_RHYME_PROC", None)
        monkeypatch.setattr(
            сервер, "_NL_RHYME_STATUS_PATH", tmp_path / "нет-статуса.json")
        monkeypatch.setattr(сервер, "_проследить_за_сборкой", lambda proc: None)
        запустить = сервер._nl_rhyme_ensure_running

    старт = threading.Barrier(3)
    результаты = []
    ошибки = []

    def работа():
        try:
            старт.wait()
            результаты.append(запустить())
        except BaseException as e:                                  # noqa: BLE001
            ошибки.append(e)

    потоки = [threading.Thread(target=работа) for _ in range(2)]
    for поток in потоки:
        поток.start()
    старт.wait()
    for поток in потоки:
        поток.join(5)

    assert all(not поток.is_alive() for поток in потоки)
    assert not ошибки, [repr(e) for e in ошибки]
    assert sorted(результаты) == [False, True]
    assert len(запуски) == 1


def test_import_stavitsya_v_fon_do_zagruzki_store(холодный_стенд, monkeypatch):
    сервер, _склад, _данные, _active = холодный_стенд
    вызовы = _склад_запрещён(сервер, monkeypatch)
    _НеЗапущенныйПоток.созданные = []
    monkeypatch.setattr(сервер, "_IMPORT", {
        "state": None, "files": [], "i": 0, "n": 0, "detail": "",
        "added": [], "errors": [], "done_at": 0.0,
    })
    monkeypatch.setattr(сервер, "_IMPORT_LOCK", threading.Lock())
    monkeypatch.setattr(сервер, "_ЧИСТКА", {"state": None})
    monkeypatch.setattr(сервер.threading, "Thread", _НеЗапущенныйПоток)

    with сервер.app.test_request_context(
        "/api/nl/source/add", method="POST",
        data={"files": (io.BytesIO("Текст книги".encode()), "книга.txt")},
    ):
        ответ = сервер.api_nl_source_add()

    assert вызовы == []
    assert ответ["queued"] == ["книга.txt"]
    assert len(_НеЗапущенныйПоток.созданные) == 1
    задача = _НеЗапущенныйПоток.созданные[0]
    assert задача.started is True and задача.target is сервер._import_worker
    assert задача.args == ([("книга.txt", "Текст книги".encode())],)


def test_clean_stavitsya_v_fon_do_zagruzki_store(холодный_стенд, monkeypatch):
    сервер, _склад, _данные, _active = холодный_стенд
    вызовы = _склад_запрещён(сервер, monkeypatch)
    _НеЗапущенныйПоток.созданные = []
    monkeypatch.setattr(сервер, "_IMPORT", {"state": None})
    monkeypatch.setattr(сервер, "_ЧИСТКА", {
        "state": None, "этап": "", "done": 0, "total": 0,
        "итог": None, "сухой": False, "done_at": 0,
    })
    monkeypatch.setattr(сервер, "_CLEAN_LOCK", threading.Lock())
    monkeypatch.setattr(сервер, "_сборка_сейчас", lambda: False)
    monkeypatch.setattr(сервер.threading, "Thread", _НеЗапущенныйПоток)

    ответ = _вызвать(
        сервер, "/api/nl/clean", сервер.api_nl_clean, {"сухой": True},
    )

    assert ответ == {"ok": True, "пошло": True, "сухой": True}
    assert вызовы == []
    assert len(_НеЗапущенныйПоток.созданные) == 1
    задача = _НеЗапущенныйПоток.созданные[0]
    assert задача.started is True and задача.target is сервер._чистка_поток
    assert задача.args == (True,)
