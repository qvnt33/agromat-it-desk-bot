"""Contains pydantic models for incoming YouTrack webhook payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


class IssuePayload(BaseModel):
    """Describes core issue fields received in a webhook.

    :param idReadable: Human-readable issue ID.
    :param id: Internal issue ID.
    :param summary: Issue title.
    :param description: Issue description.
    :param status: Status value from webhook.
    :param state: Alternate status field.
    :param assignee: Issue assignee.
    :param author: Issue author.
    :param reporter: Issue reporter.
    :param createdBy: Issue creator.
    :param customFields: Custom fields in YouTrack format.
    :param url: Issue link.
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
    """Describes base webhook payload from YouTrack.

    :param issue: Nested issue if present.
    """

    model_config = ConfigDict(extra='allow')

    issue: IssuePayload | None = None

    def issue_mapping(self) -> Mapping[str, object]:
        """Return mapping representation of issue for further processing.

        :returns: Issue data as ``Mapping`` without ``None`` fields.
        """
        if self.issue is not None:
            return self.issue.model_dump(mode='python', exclude_none=True)
        return self.model_dump(mode='python', exclude_none=True)


class YouTrackUpdatePayload(YouTrackWebhookPayload):
    """Describes webhook payload for issue update.

    :param changes: List of changed fields in issue.
    """

    changes: list[str] | None = None
