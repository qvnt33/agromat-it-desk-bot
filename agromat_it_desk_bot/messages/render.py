"""Рендерить локалізовані повідомлення із суворою валідацією."""

from __future__ import annotations

from string import Formatter
from typing import Any

from .keys import Msg
from .locales import get_catalog


def _extract_fields(template: str) -> set[str]:
    """Збирає всі плейсхолдери з шаблону.

    :param template: Рядок із плейсхолдерами ``{name}``.
    :returns: Набір назв плейсхолдерів.
    """
    fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            fields.add(field_name)
    return fields


def render(msg: Msg, /, *, locale: str = 'uk', **params: Any) -> str:
    """Форматує повідомлення з жорсткою перевіркою параметрів.

    :param msg: Ключ повідомлення у переліку ``Msg``.
    :param locale: Цільова локаль (поки підтримується ``'uk'``).
    :param params: Іменовані параметри для підстановки.
    :raises KeyError: якщо бракує обов'язкових плейсхолдерів.
    :raises ValueError: якщо передано зайві параметри.
    :returns: Відформатований текст повідомлення.
    """
    try:
        template: str = get_catalog(locale)[msg]
    except KeyError as exc:  # pragma: no cover - guard against invalid locales
        raise KeyError(f'Невідома локаль або ключ: {locale}/{msg.name}') from exc

    # Determine expected placeholders and map them to provided values
    expected: set[str] = _extract_fields(template)
    provided: set[str] = set(params)

    extra: list[str] = sorted(provided - expected)
    if extra:
        raise ValueError(f'Невикористані параметри: {extra}')

    missing: list[str] = sorted(expected - provided)
    if missing:
        raise KeyError(f'Відсутні параметри: {missing}')

    # Apply standard ``str.format`` after validations
    return template.format(**params)
