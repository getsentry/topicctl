#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from infra_event_notifier.jira_notifier import JiraNotifier

SENTRY_REGION = os.getenv("SENTRY_REGION", "unknown")


def make_markdown_table(
    headers: Sequence[str], content: Sequence[Sequence[str | int | None]]
) -> str:
    """
    Creates a markdown table given a sequence of Sequences of cells.
    """

    def make_row(row: Sequence[str | int | None]) -> str:
        content = "|".join((str(col) for col in row))
        return f"|{content}|\n"

    assert all(
        len(row) == len(headers) for row in content
    ), "Invalid table format."

    line = "-" * len(headers)
    rows = [make_row(r) for r in content]
    table = f"{make_row(headers)}{make_row(line)}{''.join(rows)}"

    return f"%%%\n{table}%%%"


@dataclass(frozen=True)
class Topic(ABC):
    name: str

    @abstractmethod
    def render_table(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class NewTopic(Topic):
    change_set: Sequence[Sequence[str | int | None]]
    dry_run: bool
    error: bool
    name: str

    def render_table(self) -> str:
        return make_markdown_table(
            headers=["Parameter", "Value"],
            content=[["Topic Name", self.name], *self.change_set],
        )

    @classmethod
    def build(cls, raw_content: Mapping[str, Any]) -> NewTopic:
        return NewTopic(
            name=raw_content["topic"],
            dry_run=raw_content["dryRun"],
            error=False,
            change_set=[
                ["Action (create/update)", "create"],
                ["Partition Count", raw_content["numPartitions"]],
                ["Replication Factor", raw_content["replicationFactor"]],
            ]
            + [
                [str(entry["name"]), str(entry["value"])]
                for entry in raw_content["configEntries"]
            ],
        )


@dataclass(frozen=True)
class UpdatedTopic(Topic):
    change_set: Sequence[Sequence[str | int | None]]
    dry_run: bool
    error: bool
    name: str

    def render_table(self) -> str:
        return make_markdown_table(
            headers=["Parameter", "Old Value", "New Value"],
            content=self.change_set,
        )

    @classmethod
    def build(cls, raw_content: Mapping[str, Any]) -> UpdatedTopic:
        change_set = [
            ["Action (create/update)", "update", ""],
            [
                "Partition Count",
                raw_content["numPartitions"]["current"]
                if raw_content["numPartitions"]
                else None,
                raw_content["numPartitions"]["updated"]
                if raw_content["numPartitions"]
                else None,
            ],
        ]

        if raw_content["newConfigEntries"]:
            change_set.extend(
                [
                    [str(entry["name"]), "", str(entry["value"])]
                    for entry in raw_content["newConfigEntries"] or []
                ]
            )

        if raw_content["updatedConfigEntries"]:
            change_set.extend(
                [
                    [
                        str(entry["name"]),
                        str(entry["current"]),
                        str(entry["updated"]),
                    ]
                    for entry in raw_content["updatedConfigEntries"]
                ]
            )

        if raw_content["missingKeys"]:
            change_set.extend(
                [
                    [str(entry), "", "REMOVED"]
                    for entry in raw_content["missingKeys"] or []
                ]
            )
        if raw_content["replicaAssignments"]:
            assignments = raw_content["replicaAssignments"]
            change_set.extend(
                [
                    [
                        f"Partition {p['partition']} assignments",
                        str(p["currentReplicas"]),
                        str(p["updatedReplicas"]),
                    ]
                    for p in assignments
                ]
            )

        return UpdatedTopic(
            name=raw_content["topic"],
            dry_run=raw_content["dryRun"],
            error=raw_content["error"],
            change_set=change_set,
        )


def main():
    api_key = os.getenv("JIRA_API_KEY")
    assert api_key is not None, "No Jira API token in JIRA_API_KEY env var"
    proj_id = os.getenv("JIRA_PROJECT_ID")
    assert proj_id is not None, "No Jira Project ID in JIRA_PROJECT_ID env var"
    api_url = os.getenv("JIRA_API_URL")
    assert api_url is not None, "No Jira API URL in JIRA_API_URL env var"
    user_email = os.getenv("JIRA_USER_EMAIL")
    assert (
        user_email is not None
    ), "No Jira user email in JIRA_USER_EMAIL env var"

    notifier = JiraNotifier(
        jira_api_key=api_key,
        jira_project=proj_id,  # Must be the id of the project, not the name
        jira_url=api_url,
        jira_user_email=user_email,
    )

    for line in sys.stdin:
        topic = json.loads(line)
        action = topic["action"]
        topic_content = (
            NewTopic.build(topic)
            if action == "create"
            else UpdatedTopic.build(topic)
        )

        tags = {
            "source": "topicctl",
            "source_category": "infra_tools",
            "sentry_region": SENTRY_REGION,
        }

        dry_run = "Dry run: " if topic_content.dry_run else ""
        title = (
            f"{dry_run}Topicctl ran apply on topic {topic_content.name} "
            f"in region {SENTRY_REGION}"
        )
        text = topic_content.render_table()
        if len(text) > 3950:
            text = (
                "Changes exceed 4000 character limit, "
                "check topicctl logs for details on changes"
            )
        tags["topicctl_topic"] = topic_content.name
        notifier.send(
            title, text, tags, issue_type="Task", update_text_body=True
        )
        print(f"{title}", file=sys.stderr)


if __name__ == "__main__":
    main()
