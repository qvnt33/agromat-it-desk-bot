"""Render localized messages with strict validation."""

from __future__ import annotations

from string import Formatter
from typing import Any

from .keys import Msg
from .locales import get_catalog


def _extract_fields(template: str) -> set[str]:
    """Collect all placeholders from template.

    :param template: String with placeholders ``{name}``.
    :returns: Set of placeholder names.
    """
    fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            fields.add(field_name)
    return fields


def render(msg: Msg, /, *, locale: str = 'uk', **params: Any) -> str:
    """Format message with strict parameter validation.

    :param msg: Message key in ``Msg`` enum.
    :param locale: Target locale (currently ``'uk'``).
    :param params: Named parameters for substitution.
    :raises KeyError: if required placeholders are missing.
    :raises ValueError: if extra parameters are provided.
    :returns: Formatted message text.
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
