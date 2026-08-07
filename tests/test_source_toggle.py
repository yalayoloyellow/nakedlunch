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
# ФРОНТ: отклик на нажатие (Раунд 56)
#
# Бэкенд теперь быстрый, но «сработало ли нажатие» — вопрос интерфейса, и
# отвечать на него он обязан ДО ответа сервера. Проверяем настоящий модуль,
# подсунув ему поддельный `this` и поддельный api — ровно тем же приёмом, что
# и остальные проверки фронта в этом проекте.
# ---------------------------------------------------------------------------

import json
import subprocess

import pytest

КОРПУС_JS = ROOT / "interface" / "react-app" / "src" / "nl" / "methods.corpus.js"


def node(тело: str):
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node не установлен")
    src = f"import {{ corpusMethods }} from '{КОРПУС_JS.as_posix()}';\n{тело}"
    p = subprocess.run(["node", "--input-type=module", "-e", src],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"node упал:\n{p.stderr}"
    return json.loads(p.stdout)


ОСНОВА = """
// Настоящий api.js ходит через fetch — его и подменяем, а не проверяемую
// функцию. Ответ НАРОЧНО медленный: весь смысл правки в том, что интерфейс
// отвечает ДО сервера.
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


def test_tochka_menyaetsya_do_otveta_servera():
    """Первый же шаг после нажатия — уже переключённая точка, ещё до сервера.

    Проверяется НАСТОЯЩИЙ `corpusMethods.toggleSource`, а не его копия: fetch
    подменён, функция взята из модуля как есть."""
    out = node(ОСНОВА + """
    const c = макет();
    const p = c.toggleSource('a');
    const сразу = шаги[0], серверМолчал = !серверОтветил;
    p.then(() => console.log(JSON.stringify({
      сразу, серверМолчал, серверОтветилПотом: серверОтветил,
      итог: ((c.state.nl || {}).sources || []).map(s => s.id + ':' + (s.active ? 1 : 0)).join(' '),
      занятоСнято: Object.keys(c.state.srcBusy || {}).length === 0 })));
    """)
    assert out["сразу"] == "a:0 b:0", "точка не переключилась до ответа сервера"
    assert out["серверМолчал"] is True, "сервер успел ответить — проверка не о том"
    assert out["серверОтветилПотом"] is True and out["итог"] == "a:0 b:0"
    assert out["занятоСнято"] is True, "строка осталась занятой навсегда"


def test_otkaz_servera_vozvrashchaet_tochku():
    """Сервер отказал — точка возвращается на место, и пользователь слышит почему.
    Без этого оптимистичный отклик стал бы враньём."""
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
    for i in range(5):
        s.add_corpus(f"книга {i}", f"Разный текст номер {i} про лето. " * 40, save=False)
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
