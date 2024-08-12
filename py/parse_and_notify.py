#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from infra_event_notifier.datadog_notifier import DatadogNotifier

SENTRY_REGION = os.getenv("SENTRY_REGION", "unknown")


def make_markdown_table(
    headers: Sequence[str],
    content: Sequence[Sequence[str | int | None]],
    error: bool,
    error_message: str | None,
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

    if error:
        error_header = (
            "# ERROR - the following error occurred while processing this topic:\n"  # noqa
            f"{error_message}\n\n"
        )
        # if changes were still made before an error, report them
        if len(content) > 1:
            table = (
                error_header
                + "# The following changes were still made:\n\n"
                + table
            )
        else:
            table = error_header + "# No changes were made."

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
    error_message: str | None
    name: str

    def render_table(self) -> str:
        return make_markdown_table(
            headers=["Parameter", "Value"],
            content=[["Topic Name", self.name], *self.change_set],
            error=self.error,
            error_message=self.error_message,
        )

    @classmethod
    def build(cls, raw_content: Mapping[str, Any]) -> NewTopic:
        change_set = [["Action (create/update)", "create"]]
        if raw_content["numPartitions"]:
            change_set.extend(
                [["Partition Count", raw_content["numPartitions"]]]
            )
        if raw_content["replicationFactor"]:
            change_set.extend(
                [["Replication Factor", raw_content["replicationFactor"]]]
            )
        change_set += [
            [str(entry["name"]), str(entry["value"])]
            for entry in raw_content["configEntries"]
        ]
        # if nothing changed, report no changes
        if len(change_set) == 1:
            change_set = []
        return NewTopic(
            name=raw_content["topic"],
            dry_run=raw_content["dryRun"],
            error=raw_content["error"],
            error_message=raw_content["errorMessage"],
            change_set=change_set,
        )


@dataclass(frozen=True)
class UpdatedTopic(Topic):
    change_set: Sequence[Sequence[str | int | None]]
    dry_run: bool
    error: bool
    error_message: str | None
    name: str

    def render_table(self) -> str:
        return make_markdown_table(
            headers=["Parameter", "Old Value", "New Value"],
            content=self.change_set,
            error=self.error,
            error_message=self.error_message,
        )

    @classmethod
    def build(cls, raw_content: Mapping[str, Any]) -> UpdatedTopic:
        change_set = [["Action (create/update)", "update", ""]]

        if (
            raw_content["numPartitions"]
            and raw_content["numPartitions"]["current"]
            and raw_content["numPartitions"]["updated"]
        ):
            change_set.extend(
                [
                    [
                        "Partition Count",
                        raw_content["numPartitions"]["current"],
                        raw_content["numPartitions"]["updated"],
                    ]
                ]
            )

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
        if len(change_set) == 1:
            change_set = []

        return UpdatedTopic(
            name=raw_content["topic"],
            dry_run=raw_content["dryRun"],
            error=raw_content["error"],
            error_message=raw_content["errorMessage"],
            change_set=change_set,
        )


def main():
    token = os.getenv("DATADOG_API_KEY")
    assert token is not None, "No Datadog token in DATADOG_API_KEY env var"
    notifier = DatadogNotifier(datadog_api_key=token)

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
            "source_tool": "topicctl",
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

        notifier.send(title=title, body=text, tags=tags, alert_type="")
        print(f"{title}", file=sys.stderr)


if __name__ == "__main__":
    main()
