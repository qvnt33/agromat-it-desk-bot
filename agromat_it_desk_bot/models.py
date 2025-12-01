"""Містить pydantic-моделі для вхідних webhook-пейлоадів YouTrack."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


class IssuePayload(BaseModel):
    """Описує основні поля задачі, що надходять у webhook.

    :param idReadable: Людиночитний ID задачі.
    :param id: Внутрішній ID задачі.
    :param summary: Заголовок задачі.
    :param description: Опис задачі.
    :param status: Значення статусу з webhook.
    :param state: Альтернативне поле статусу.
    :param assignee: Виконавець задачі.
    :param author: Автор задачі.
    :param reporter: Репортер задачі.
    :param createdBy: Створювач задачі.
    :param customFields: Кастомні поля у форматі YouTrack.
    :param url: Посилання на задачу.
    """

    model_config = ConfigDict(extra='allow', populate_by_name=True)

    idReadable: str | None = None  # noqa: N815
    id: str | None = None
    summary: str | None = None
    description: str | None = None
    status: Any = None  # noqa: ANN401
    state: Any = None  # noqa: ANN401
    assignee: Any = None  # noqa: ANN401
    author: Any = None  # noqa: ANN401
    reporter: Any = None  # noqa: ANN401
    createdBy: Any = None  # noqa: ANN401,N815
    customFields: list[dict[str, object]] | None = None  # noqa: N815
    url: str | None = None


class YouTrackWebhookPayload(BaseModel):
    """Описує базовий webhook-пейлоад від YouTrack.

    :param issue: Вкладена задача (якщо є).
    """

    model_config = ConfigDict(extra='allow')

    issue: IssuePayload | None = None

    def issue_mapping(self) -> Mapping[str, object]:
        """Повертає словникове представлення задачі для подальшої обробки.

        :returns: Дані задачі як ``Mapping`` без ``None`` полів.
        """
        if self.issue is not None:
            return self.issue.model_dump(mode='python', exclude_none=True)
        return self.model_dump(mode='python', exclude_none=True)


class YouTrackUpdatePayload(YouTrackWebhookPayload):
    """Описує webhook-пейлоад для оновлення задачі.

    :param changes: Список змінених полів у задачі.
    """

    changes: list[str] | None = None
