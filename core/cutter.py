# nakedlunch 1.0.0
# Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow). Personal use only.

"""
Cutter: детерминированная нарезка текста на рваные фрагменты (cut-up стиль).

Правила:
- Однотипная обработка для поэзии и прозы.
- "Грязные" разрезы: обрывы посередине, мосты между предложениями, скользящие окна.
- Детерминировано (без random в основном пути).
- Фильтрация короткого мусора.
"""

from __future__ import annotations

import html
import re
from typing import List


def clean_text(text: str) -> str:
    """Aggressively clean HTML, entities, and artifacts from raw text before fragmentation.
    Centralized cleaning so all sources (via /a or otherwise) are clean.
    """
    if not text or not text.strip():
        return ""

    # Remove script and style blocks entirely (with content)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.DOTALL)

    # Remove all remaining HTML/XML tags, including self-closing, with attributes, case insensitive
    text = re.sub(r'</?\s*[^>\s]+(?:\s+[^>]*?)?\s*/?>', ' ', text, flags=re.IGNORECASE)

    # Unescape all HTML entities (&amp; -> &, &lt; -> <, &nbsp; -> space, etc.)
    text = html.unescape(text)

    # Replace common entities that unescape might leave as \xa0 etc.
    text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')

    # Collapse all whitespace (newlines, tabs, multiple spaces) to single space
    text = re.sub(r'\s+', ' ', text).strip()

    # Remove other potential markup artifacts, keep letters, digits, basic punctuation for fragments
    # This is aggressive to kill any remaining < > / etc.
    text = re.sub(r'[<>]', '', text)
    text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\—\–\'\"«»\(\)\[\]\{\}…]', '', text, flags=re.UNICODE)

    # Final normalization
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def _normalize(text: str) -> str:
    # Схлопываем множественные пробелы, но сохраняем одиночные переносы строк
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Временно защитим одиночные \n
    text = re.sub(r"\n", " \n ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" \n ", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(p: str) -> List[str]:
    """Разбиваем параграф/блок на предложения, сохраняя базовые разделители."""
    if not p:
        return []
    # Разделители предложений + захват группы
    parts = re.split(r"([.!?])\s*", p)
    sents: List[str] = []
    i = 0
    while i < len(parts):
        chunk = parts[i].strip()
        if i + 1 < len(parts) and parts[i + 1] in ".!?":
            delim = parts[i + 1]
            s = (chunk + delim).strip()
            if s:
                sents.append(s)
            i += 2
        else:
            if chunk:
                sents.append(chunk)
            i += 1
    return sents


def _subsplit(sent: str) -> List[str]:
    """Дополнительные разрезы внутри предложения по запятым, тире и т.п."""
    if not sent:
        return []
    # Агрессивно режем по внутренним разделителям
    subs = re.split(r"[,;—–-]\s*", sent)
    out = []
    for s in subs:
        s = s.strip()
        if s:
            out.append(s)
    return out


def _bridges(sents: List[str]) -> List[str]:
    """Мосты: хвост предыдущего + голова следующего."""
    bridges = []
    for i in range(len(sents) - 1):
        a = sents[i]
        b = sents[i + 1]
        aw = a.split()
        bw = b.split()
        if len(aw) >= 3 and len(bw) >= 2:
            bridge = " ".join(aw[-3:] + bw[:3])
            if len(bridge) >= 10:
                bridges.append(bridge)
        # ещё один вариант моста подлиннее
        if len(aw) >= 4 and len(bw) >= 3:
            bridge2 = " ".join(aw[-4:] + bw[:3])
            if len(bridge2) >= 12:
                bridges.append(bridge2)
    return bridges


def _sliding_windows(text: str) -> List[str]:
    """Систематические грязные окна по всему тексту (детерминировано)."""
    # Берём чистый текст без лишних переносов для окон
    clean = re.sub(r"\s+", " ", text)
    words = [w for w in clean.split() if w]
    windows: List[str] = []
    if len(words) < 4:
        return windows
    step = 3
    win = 7
    for i in range(0, len(words) - 3, step):
        chunk = " ".join(words[i : i + win])
        if len(chunk) >= 12:
            windows.append(chunk)
    # дополнительные чуть меньшие окна со сдвигом
    win2 = 5
    for i in range(1, len(words) - 3, step + 1):
        chunk = " ".join(words[i : i + win2])
        if len(chunk) >= 10:
            windows.append(chunk)
    return windows


def cut_into_fragments(text: str) -> List[str]:
    if not text or not text.strip():
        return []

    norm = _normalize(text)
    if not norm:
        return []

    fragments: List[str] = []

    # 1. Работаем по абзацам
    paras = [p.strip() for p in norm.split("\n\n") if p.strip()]
    if not paras:
        paras = [norm]

    for p in paras:
        # Учитываем также строки внутри (полезно для поэзии/рэпа)
        lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
        for line in lines:
            if 8 <= len(line) <= 140:
                fragments.append(line)

        sents = _split_sentences(p)
        for s in sents:
            s = s.strip()
            if 8 <= len(s) <= 160:
                fragments.append(s)
            # подразрезы
            for sub in _subsplit(s):
                if 6 <= len(sub) <= 120:
                    fragments.append(sub)

        # мосты между предложениями этого параграфа
        for br in _bridges(sents):
            fragments.append(br)

    # 2. Глобальные скользящие окна (дают самые "дикие" обрывы)
    for w in _sliding_windows(norm):
        fragments.append(w)

    # 3. Финальная чистка + дедуп
    seen = set()
    result: List[str] = []
    for f in fragments:
        f = f.strip().strip(".,;:!?—–- \"'«»()[]{}")
        f = re.sub(r"\s+", " ", f).strip()
        if not f:
            continue
        # минимум 2 слова
        if len(f.split()) < 2:
            continue
        if len(f) < 7:
            continue
        if f not in seen:
            seen.add(f)
            result.append(f)

    return result
