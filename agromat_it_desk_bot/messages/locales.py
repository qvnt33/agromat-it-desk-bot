from __future__ import annotations

from collections.abc import Mapping

from .keys import Msg
from .uk import UK

_LOCALES: dict[str, Mapping[Msg, str]] = {'uk': UK}


def get_catalog(locale: str) -> Mapping[Msg, str]:
    """Returns the message directory for the given locale.

    :param locale: Locale identifier.
    :returns: Map of ``Msg`` keys to templates for the selected locale or ``UK``.
    """
    return _LOCALES.get(locale, UK)
