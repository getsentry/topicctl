import os
import json

from pprint import pprint
from subprocess import Popen, PIPE

DD_API_BASE = "https://api.datadoghq.com"

DATADOG_API_KEY = os.getenv("DATADOG_API_KEY") or os.getenv("DD_API_KEY")
assert DATADOG_API_KEY, "Please set either DATADOG_API_KEY or DD_API_KEY env var."

p = Popen(['topicctl', 'apply', 'examples/local-cluster/topics/topic-default.yaml', '--json-output', '--dry-run'], stdout=PIPE, text=True)

# read stdout from subprocess
data = p.communicate()[0]
dataJson = json.loads(data)
pprint(dataJson)
