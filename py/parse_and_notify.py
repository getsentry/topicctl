#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from infra_event_notifier.datadog_notifier import (
    DatadogNotifier,
    SlackNotifier,
)

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


def make_slack_message(
    headers: Sequence[str],
    content: Sequence[Sequence[str | int | None]],
    error: bool,
    error_message: str | None,
) -> str:
    """
    Formats an ASCII table for slack message since slack's
    markdown support is lacking
    """

    def make_row(
        row: Sequence[str | int | None], max_len: Sequence[int]
    ) -> str:
        content = "|".join(
            (
                " " + str(col).ljust(max_len[i]) + " "
                for i, col in enumerate(row)
            )
        )
        return f"|{content}|\n"

    assert all(
        len(row) == len(headers) for row in content
    ), "Invalid table format."
    # get max length of columns
    num_cols = len(headers)
    max_len = [len(h) for h in headers]
    for i in range(num_cols):
        for row in content:
            max_len[i] = max(max_len[i], len(str(row[i])))
    # 2 * len(headers) to account for the whitespace added in each row
    line = ["-" * (sum(max_len) + 2 * len(headers))]
    rows = [make_row(r, max_len) for r in content]
    table = (
        f"```{make_row(headers, max_len)}"
        + f"{make_row(line, max_len)}"
        + f"{''.join(rows)}```"
    )

    if error:
        error_header = (
            "*ERROR - the following error occurred while processing this topic:*\n"  # noqa
            f"{error_message}\n\n"
        )
        # if changes were still made before an error, report them
        if len(content) > 1:
            table = (
                error_header
                + "*The following changes were still made:*\n\n"
                + table
            )
        else:
            table = error_header + "*No changes were made.*"

    return f"{table}"


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
    dd_token = os.getenv("DATADOG_API_KEY")
    slack_secret = os.getenv("KAFKA_CONTROL_PLANE_WEBHOOK_SECRET")
    slack_url = os.getenv("ENG_PIPES_URL")
    assert dd_token is not None, "No Datadog token in DATADOG_API_KEY env var"
    assert (
        slack_secret is not None
    ), "No HMAC secret in KAFKA_CONTROL_PLANE_WEBHOOK_SECRET env var"
    dd_notifier = DatadogNotifier(datadog_api_key=dd_token)
    slack_notifier = SlackNotifier(
        eng_pipes_key=slack_secret, eng_pipes_url=slack_url
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
        dd_table = topic_content.render_table()
        slack_table = topic_content.render_slack_msg()
        if len(dd_table) > 3950 or len(slack_table) > 2950:
            dd_table = (
                "Changes exceed character limit, "
                "check topicctl logs for details on changes"
            )
            slack_table = dd_table
        tags["topicctl_topic"] = topic_content.name

        dd_notifier.send(title=title, body=dd_table, tags=tags, alert_type="")
        slack_notifier.send(title=title, body=slack_table)
        print(f"{title}", file=sys.stderr)


if __name__ == "__main__":
    main()
