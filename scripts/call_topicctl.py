import argparse
import os
import json

from subprocess import Popen, PIPE
from typing import Any, Mapping, Sequence

from package.notifier import notify

SENTRY_REGION = os.getenv("SENTRY_REGION", "unknown")


def _get_new_change_fields(topic: Mapping[str, Any]) -> Mapping[str, str]:
    configs = ""
    for config in topic["configEntries"]:
        configs += f"{config['name']}={config['value']}, "
    # TODO: implement replicaAssignments/replicationFactor/numPartitions in ChangesTracker
    partition_count = str(topic["numPartitions"])
    replication_factor = str(topic["replicationFactor"])
    return {
        "Configs": configs,
        "Partition Count": partition_count,
        "Replication Factor": replication_factor,
    }


def _get_update_change_fields(topic: Mapping[str, Any]) -> Mapping[str, str]:
    newConfigs = ""
    updatedConfigs = ""
    for config in topic["newConfigEntries"]:
        newConfigs += f"{config['name']}={config['value']}, "
    for config in topic["updatedConfigEntries"]:
        updatedConfigs += (
            f"{config['name']}: {config['current']} --> {config['updated']}, "
        )
    # TODO: implement replicaAssignments/replicationFactor/numPartitions in ChangesTracker
    partition_count = "FIXME"
    replication_factor = "FIXME"
    return {
        "New Configs": newConfigs,
        "Updated Configs": updatedConfigs,
        "Configs Missing from Topicctl": topic["missingKeys"],
        "Partition Count": partition_count,
        "Replication Factor": replication_factor,
    }


def _markdown_table_from_change(topic: Sequence[Mapping[str, Any]]) -> str:
    """
    Formats the list of changes as a markdown table
    """
    topic_name = topic["topic"]
    action = topic["action"]
    extra_fields = {}
    if action == "create":
        extra_fields = _get_new_change_fields(topic)
    elif action == "update":
        extra_fields = _get_update_change_fields(topic)
    else:
        raise AttributeError("Invalid action key, must be 'create' or 'update'")

    table = f"""|||
|:--------------------------:|-|
| **Topic Name**             |{topic_name}|
| **Action (create/update)** |{action}|"""
    for field in extra_fields:
        table += f"""
|         **{field}**        |{extra_fields[field]}|"""

    if topic["error"]:
        table = (
            "**Errors occurred while applying this topic. More changes may exist that were not applied.**\n"
            + table
        )

    return f"%%%\n{table}\n%%%"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-config", help="Path to topic file(s) to be applied")
    parser.add_argument("--cluster-config", help="Path to cluster file to be applied")
    parser.add_argument(
        "--dry-run",
        help="Print chnages without applying, still creates json blob of changes",
        action="store_true",
    )
    args = parser.parse_args(argv)
    topicctl_cmd = [
        "topicctl",
        "apply",
        args.topic_config,
        "--cluster-config",
        args.cluster_config,
        "--json-output",
    ]
    if args.dry_run:
        topicctl_cmd.append("--dry-run")
    p = Popen(
        topicctl_cmd,
        stdout=PIPE,
        text=True,
    )
    # read stdout from subprocess
    data = p.communicate()[0]
    if not data:
        exit()
    dataSplit = data.splitlines()
    for line in dataSplit:
        dataJson = json.loads(line)
        # add Dry run: to title if --dry-run used
        dry_run = "Dry run: " if dataJson["dryRun"] else ""
        tags = {
            "source": "topicctl",
            "source_category": "infra_tools",
            "sentry_region": SENTRY_REGION,
        }
        changes = (
            dataJson["newTopics"]
            if dataJson["newTopics"]
            else dataJson["updatedTopics"]
        )
        for change in changes:
            title = f"{dry_run}Topicctl ran apply on topic {change['topic']} in region {SENTRY_REGION}"
            text = _markdown_table_from_change(change)
            if len(text) > 3950:
                text = "Changes exceed 4000 character limit, check topicctl logs for details on changes"
            tags["topicctl_topic"] = change["topic"]
            notify(title=title, text=text, tags=tags, datadog_event=True)


if __name__ == "__main__":
    main()
