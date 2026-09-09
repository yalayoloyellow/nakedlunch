# nakedlunch — СИРОТЫ-СБОРКИ: ЗАКРЫЛ ОКНО, А ПЕРЕПЕЧКА ИДЁТ
# (открытый долг с 2026-08-05, закрыт 2026-08-28).
#
# ЧТО БЫЛО. launch.py при выходе гасит РОВНО ОДИН процесс — сервер. А сервер
# запускает своих детей: пересчёт ударений и перепечку колоночного индекса,
# обоих через subprocess.Popen. Закрыл окно — программы нет, а
# ребёнок ещё минуты держит гигабайты и пишет в core/data. Следующий запуск
# после этого видит в сайдкаре живую чужую сборку и молча отказывает кнопке
# «пересчитать».
#
# ЧТО СТАЛО. Детей гасит САМ СЕРВЕР — он единственный знает, кто из них его.
# Регистрация в `main()`: atexit плюс перехват SIGINT/SIGTERM, потому что
# launch.py гасит сервер именно SIGTERM'ом, а на него по умолчанию процесс
# умирает мгновенно и atexit не отрабатывает вовсе.
#
# ЧТО СТОРОЖИТ ЭТОТ ФАЙЛ:
#   1. гашение действительно снимает ЖИВЫХ детей, а не «просит»;
#   2. гасятся ТОЛЬКО свои два хэндла — не группа и не дерево. Это прямая
#      защита оговорки про запись фристайла: она живёт в процессе launch.py
#      вместе с ffmpeg-склейкой, и порванный дубль не восстановить;
#   3. зарегистрировано И на atexit, И на обоих сигналах;
#   4. обработчик сигнала гасит детей и уходит, а не гасит «когда-нибудь»;
#   5. регистрация зовётся из `main()`, а не с уровня модуля;
#   6. НАША смерть ребёнка не пишется в сайдкар как авария — иначе выход из
#      программы врал бы в шапке следующего запуска про нехватку памяти.
#
# ДЕТИ ЗДЕСЬ НАСТОЯЩИЕ, а не заглушки: весь вопрос задачи — умирают ли они
# на самом деле. `sleep 120` сам не кончится, поэтому зелёный тест означает
# ровно то, что написано. Боевых каталогов они не касаются.
#
# Прогон: .venv/bin/python -m pytest tests/test_сироты_сборок.py -q

import ast
import json
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))


@pytest.fixture(scope="module")
def сервер():
    """`api/server.py` с заглушенными тяжёлыми прогревами — как в
    tests/test_живость_сборки.py: гашение детей корпуса не касается, а импорт
    без заглушек стоил бы гигабайты."""
    # `generate` из этого списка ушёл 2026-08-29 вместе с самим файлом
    # core/generate.py: глушить прогрев модуля, которого нет, — это
    # ModuleNotFoundError на импорте фикстуры, а не защита.
    import filters
    было = (filters.warm_caches,)
    filters.warm_caches = lambda: None
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    try:
        import server
    finally:
        (filters.warm_caches,) = было
    return server


@pytest.fixture()
def дети():
    """Раздатчик долгих детей с уборкой за собой: тест, оставивший `sleep 120`
    в живых, отравил бы рабочую машину на две минуты."""
    заведённые = []

    def завести():
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        заведённые.append(p)
        return p

    yield завести
    for p in заведённые:
        if p.poll() is None:
            p.kill()
        p.wait()


def _пережил(p, сколько: float = 0.4) -> bool:
    """Жив ли процесс СПУСТЯ паузу. Без паузы «жив» ничего не значит: сигнал
    доходит не мгновенно, и тест на «не тронули» зеленел бы даже после SIGTERM."""
    time.sleep(сколько)
    return p.poll() is None


# ------------------------------------------------------------ 1. само гашение

def test_gashenie_snimaet_zhivykh_detey(сервер, дети, monkeypatch):
    """ГЛАВНОЕ. Оба ребёнка — те самые: пересчёт ударений и перепечка индекса."""
    рифмы, индекс = дети(), дети()
    monkeypatch.setattr(сервер, "_NL_RHYME_PROC", рифмы)
    monkeypatch.setattr(сервер, "_NL_INDEX_PROC", индекс)
    monkeypatch.setattr(сервер, "_ГАСИМ_СВОИХ", False)

    сервер._погасить_детей()

    assert рифмы.poll() is not None, "пересчёт ударений пережил выход — это сирота"
    assert индекс.poll() is not None, "перепечка индекса пережила выход — это сирота"


def test_gasyatsya_TOLKO_svoi(сервер, дети, monkeypatch):
    """Не «всё дерево» и не группа. Гашение по группе задело бы и запись
    фристайла с её ffmpeg — а порванный дубль не восстановить (та же оговорка,
    что в launch.py про `recording`). Чужой процесс здесь — за них всех."""
    свой = дети()
    чужой = дети()
    monkeypatch.setattr(сервер, "_NL_RHYME_PROC", свой)
    monkeypatch.setattr(сервер, "_NL_INDEX_PROC", None)
    monkeypatch.setattr(сервер, "_ГАСИМ_СВОИХ", False)

    сервер._погасить_детей()

    assert свой.poll() is not None
    assert _пережил(чужой), "погашен процесс, которого сервер не запускал"


def test_gashenie_bez_detey_ne_padaet(сервер, monkeypatch):
    """Обычный случай: окно закрыли, сборок не было. Исключение на выходе
    из программы — худшее место для исключения."""
    monkeypatch.setattr(сервер, "_NL_RHYME_PROC", None)
    monkeypatch.setattr(сервер, "_NL_INDEX_PROC", None)
    monkeypatch.setattr(сервер, "_ГАСИМ_СВОИХ", False)
    сервер._погасить_детей()


# ------------------------------------------------------------ 2. регистрация

@pytest.fixture()
def перехват(monkeypatch):
    """Подменить atexit и signal на время проверки регистрации: настоящую
    подмену обработчиков в процессе pytest делать нельзя — SIGINT его собственный."""
    import atexit
    записано = []
    обработчики = {}
    monkeypatch.setattr(atexit, "register",
                        lambda f, *a, **k: (записано.append(f), f)[1])
    monkeypatch.setattr(signal, "signal",
                        lambda номер, f: обработчики.__setitem__(номер, f))
    return записано, обработчики


def test_registratsiya_i_na_atexit_i_na_oboikh_signalakh(сервер, перехват):
    """ОДНОГО atexit МАЛО, и это суть починки: launch.py гасит сервер через
    `terminate()`, то есть SIGTERM, а на него процесс по умолчанию умирает
    мгновенно — atexit не отрабатывает."""
    записано, обработчики = перехват
    сервер._гасить_детей_при_выходе()
    assert сервер._погасить_детей in записано, "гашение не зарегистрировано на atexit"
    assert set(обработчики) == {signal.SIGINT, signal.SIGTERM}


def test_obrabotchik_signala_gasit_i_ukhodit(сервер, дети, перехват, monkeypatch):
    """Обработчик обязан снять детей ДО выхода, а не понадеяться на atexit —
    его-то как раз может и не быть."""
    _, обработчики = перехват
    сервер._гасить_детей_при_выходе()
    ребёнок = дети()
    monkeypatch.setattr(сервер, "_NL_RHYME_PROC", ребёнок)
    monkeypatch.setattr(сервер, "_NL_INDEX_PROC", None)
    monkeypatch.setattr(сервер, "_ГАСИМ_СВОИХ", False)

    with pytest.raises(SystemExit):
        обработчики[signal.SIGTERM](signal.SIGTERM, None)

    assert ребёнок.poll() is not None


def test_registriruet_main_a_ne_import():
    """Импорт модуля тестом не имеет права трогать обработчики сигналов чужого
    процесса — то же правило, что у `_поднять_прогрев`. Читаем дерево, а не
    зовём `main()`: он поднимает сервер."""
    дерево = ast.parse((КОРЕНЬ / "api" / "server.py").read_text("utf-8"))
    main = next(у for у in дерево.body
                if isinstance(у, ast.FunctionDef) and у.name == "main")
    зовёт = {у.func.id for у in ast.walk(main)
             if isinstance(у, ast.Call) and isinstance(у.func, ast.Name)}
    assert "_гасить_детей_при_выходе" in зовёт, \
        "main() больше не регистрирует гашение — дети снова осиротеют"
    # и НЕ на уровне модуля
    верхние = {у.value.func.id for у in дерево.body
               if isinstance(у, ast.Expr) and isinstance(у.value, ast.Call)
               and isinstance(у.value.func, ast.Name)}
    assert "_гасить_детей_при_выходе" not in верхние


# ------------------------------------------------------- 3. честность сайдкара

def test_nashe_gashenie_ne_pishetsya_kak_avariya(сервер, дети, monkeypatch, tmp_path):
    """Убитая НАМИ сборка — не авария. Без этой оговорки сторож дописывал бы в
    сайдкар «завершился с кодом -15, чаще всего нехватка памяти», и закрытие
    окна врало бы в шапке следующего запуска."""
    статус = tmp_path / "nl_rhyme.status.json"
    было = {"state": "running", "cached": 7, "mode": "incremental",
            "updated_at": time.time()}
    статус.write_text(json.dumps(было, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(сервер, "_NL_RHYME_STATUS_PATH", статус)
    ребёнок = дети()
    monkeypatch.setattr(сервер, "_NL_RHYME_PROC", ребёнок)
    monkeypatch.setattr(сервер, "_NL_INDEX_PROC", None)
    monkeypatch.setattr(сервер, "_ГАСИМ_СВОИХ", False)

    сервер._проследить_за_сборкой(ребёнок)
    сервер._погасить_детей()
    for т in threading.enumerate():
        if т.name == "nl-rhyme-watch":
            т.join(10)

    assert json.loads(статус.read_text("utf-8")) == было, \
        "выход из программы записан в сайдкар как отказ сборки"
