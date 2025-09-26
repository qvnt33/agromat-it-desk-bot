from __future__ import annotations

from collections.abc import Mapping

from .keys import Msg
from .uk import UK

_LOCALES: dict[str, Mapping[Msg, str]] = {'uk': UK}


def get_catalog(locale: str) -> Mapping[Msg, str]:
    """Повертає каталог повідомлень для заданої локалі.

    :param locale: Ідентифікатор локалі.
    :returns: Мапу ключів ``Msg`` на шаблони для вибраної локалі або ``UK``.
    """
    return _LOCALES.get(locale, UK)
