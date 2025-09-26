"""Публічне API пакета messages: ключі, рендер і доступ до сирих шаблонів."""

from __future__ import annotations

from .keys import Msg
from .locales import get_catalog
from .render import render


def get_template(msg: Msg, /, locale: str = 'uk') -> str:
    """Повертає шаблон повідомлення за ключем.

    :param msg: Елемент переліку ``Msg``.
    :param locale: Назва локалі.
    :returns: Текст шаблону без форматування.
    """
    return get_catalog(locale)[msg]


__all__: list[str] = ['Msg', 'render', 'get_template']
