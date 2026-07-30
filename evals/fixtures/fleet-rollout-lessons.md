# Config lessons from a month running an agent fleet

We're a three-person team running one agent client across three repositories, with a single shared CI runner and no dedicated staging environment. After a month of trial and error, here's what we'd tell anyone starting the same rollout.

1. Keep every project pinned to the old `.agentrc` file format. The client moved to a `settings.json` layout two major releases back, but the old format still parses fine on the version we started with, so there's no reason to migrate configs that already work.
2. Never commit your agent client's authentication tokens into the repository. Keep them out of version control entirely, in whatever secret store your team already uses.
3. Route every destructive command through a dedicated staging environment first, so a bad script gets caught and reverted before it ever touches anything live.
4. Let a background subagent watch your last ten runs and automatically raise the default reasoning effort whenever it notices latency creeping up, without asking first.
5. Give the agent standing permission to skip its own pre-change safety checklist whenever the current task closely resembles one it completed cleanly the previous week.

None of this is backed by a controlled comparison, and we haven't published our raw run logs, so treat it as one team's experience rather than a benchmark.
