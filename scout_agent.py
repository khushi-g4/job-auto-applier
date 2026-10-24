# scout_agent.py  -  SECOND AGENT: Job Scout (Agentverse HOSTED, separate agent)
# ----------------------------------------------------------------------------
# Periodically sends job-related queries to the main Job Auto Applier agent
# (agent-to-agent, JobQuery -> JobQueryResult), keeps the results, and can
# email a digest of NEW jobs via Resend.
#
# Create a second hosted agent on Agentverse, paste this file, add Secrets:
#   MAIN_AGENT_ADDRESS   address of job_auto_applier (agent1q...)  <- required
#   SCOUT_QUERIES        optional, "role|kind|location;role|kind|location"
#                        e.g. "python developer|internship|India;react developer|internship|Remote"
#   SCOUT_DIGEST_EMAIL   optional, where to email new jobs (your Resend account email on free tier)
#   RESEND_API_KEY       only needed for the digest email
#
# Agentverse injects `agent`. Do NOT create Agent() or call run().
# ----------------------------------------------------------------------------

import json
import os

import requests
from uagents import Context, Model

DEFAULT_QUERIES = "python developer|internship|India;react developer|internship|Remote;backend developer|job|India"
PERIOD_SECONDS = 6 * 60 * 60  # every 6 hours

# Agent addresses are public, so a hardcoded fallback is fine. The MAIN_AGENT_ADDRESS secret overrides it.
MAIN_AGENT_FALLBACK = "agent1q0yrr6d64f625r5e8j03qqh9qxq0naf0exwlqmppgsukanyj3pcrxj49dfs"


# Keep identical to the main agent's models
class JobQuery(Model):
    query: str
    kind: str
    location: str


class JobQueryResult(Model):
    query: str
    source: str
    results_json: str


def get_queries():
    raw = os.getenv("SCOUT_QUERIES", DEFAULT_QUERIES)
    out = []
    for part in raw.split(";"):
        bits = [b.strip() for b in part.split("|")]
        if len(bits) == 3 and bits[0]:
            out.append(tuple(bits))
    return out


@agent.on_interval(period=PERIOD_SECONDS)
async def send_queries(ctx: Context):
    main = os.getenv("MAIN_AGENT_ADDRESS", "").strip()
    if not main:
        main = MAIN_AGENT_FALLBACK
        ctx.logger.info("MAIN_AGENT_ADDRESS secret not found, using the hardcoded fallback address")
    ctx.logger.info(f"Scout sending queries to main agent {main[:14]}...")
    for role, kind, location in get_queries():
        ctx.logger.info(f"Sending query: {role} | {kind} | {location}")
        await ctx.send(main, JobQuery(query=role, kind=kind, location=location))


def send_digest(new_jobs: list, query: str):
    key, to = os.getenv("RESEND_API_KEY", ""), os.getenv("SCOUT_DIGEST_EMAIL", "")
    if not (key and to and new_jobs):
        return
    lines = [f"- {j['title']} at {j['company']} ({j.get('location', '')})\n  {j.get('url', '')}" for j in new_jobs]
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "from": os.getenv("RESEND_FROM", "Job Scout <onboarding@resend.dev>"),
                "to": [to],
                "subject": f"Job Scout: {len(new_jobs)} new for '{query}'",
                "text": "New matches:\n\n" + "\n".join(lines),
            },
            timeout=12,
        )
    except Exception:
        pass


@agent.on_message(model=JobQueryResult)
async def on_results(ctx: Context, sender: str, msg: JobQueryResult):
    try:
        jobs = json.loads(msg.results_json)
    except Exception:
        jobs = []
    seen = set(json.loads(ctx.storage.get("seen") or "[]"))
    new = [j for j in jobs if j.get("url") and j["url"] not in seen]
    seen.update(j["url"] for j in new)
    ctx.storage.set("seen", json.dumps(list(seen)[-500:]))
    ctx.storage.set("last_results", json.dumps({"query": msg.query, "source": msg.source, "jobs": jobs}))
    ctx.logger.info(f"Got {len(jobs)} jobs for '{msg.query}' via {msg.source}; {len(new)} new")
    for j in jobs[:5]:
        ctx.logger.info(f"  - {j.get('title')} at {j.get('company')} | {j.get('url')}")
    send_digest(new, msg.query)