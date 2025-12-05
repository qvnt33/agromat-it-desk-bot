"""Public API of messages package: keys, renderer, and raw templates."""

from __future__ import annotations

from .keys import Msg
from .locales import get_catalog
from .render import render


def get_template(msg: Msg, /, locale: str = 'uk') -> str:
    """Return message template by key.

    :param msg: Item of ``Msg`` enum.
    :param locale: Locale name.
    :returns: Unformatted template text.
    """
    return get_catalog(locale)[msg]


__all__: list[str] = ['Msg', 'render', 'get_template']
