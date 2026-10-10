"""``aauth-lab up | demo | timeline``"""

import argparse
import asyncio
import os
import subprocess
import sys
from urllib.parse import urlsplit

from aauth_lab.agent.client import Done
from aauth_lab.config import StepUpDelivery, Topology
from aauth_lab.person import PersonChoice
from aauth_lab.scenario import DemoOptions, run_demo
from aauth_lab.timeline import print_timeline


def _up(topology: Topology) -> None:
    roles = {
        "agent_provider": topology.agent_provider,
        "person_server": topology.person_server,
        "resource": topology.resource,
    }
    procs = []
    for factory, url in roles.items():
        port = str(urlsplit(url).port)
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "--factory",
                    f"aauth_lab.serve:{factory}",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    port,
                    "--log-level",
                    "warning",
                ],
                env=os.environ.copy(),
            )
        )
        print(f"  {factory:<15} {url}")
    print(f"\n  本人のダッシュボード: {topology.person_server}/\n  Ctrl+C で停止")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()


def _demo(topology: Topology, args: argparse.Namespace) -> None:
    topology.events_path.parent.mkdir(parents=True, exist_ok=True)
    topology.events_path.write_text("")
    options = DemoOptions(
        delivery=StepUpDelivery(args.delivery),
        person=PersonChoice(args.person),
        revoke_mission_before_delete=args.revoke_mission,
    )
    report = asyncio.run(run_demo(topology, options))
    print_timeline(topology.events_path)
    print("\n結果:")
    for label, outcome in report.steps:
        if isinstance(outcome, Done):
            print(f"  {label:<10} {outcome.status} {outcome.body}")
        else:
            print(f"  {label:<10} refused by {outcome.by}: {outcome.error} {outcome.detail or ''}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="aauth-lab")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="start agent provider, person server and resource")
    demo = sub.add_parser("demo", help="run scenario A against running servers")
    demo.add_argument(
        "--delivery",
        choices=[d.value for d in StepUpDelivery],
        default=StepUpDelivery.DEFERRED.value,
        help="how the resource delivers the step-up challenge (§6.5.1)",
    )
    demo.add_argument(
        "--person",
        choices=[c.value for c in PersonChoice],
        default=PersonChoice.APPROVE.value,
        help="what the person does at the step-up consent page",
    )
    demo.add_argument(
        "--revoke-mission",
        action="store_true",
        help="the person terminates the mission before the delete",
    )
    sub.add_parser("timeline", help="print the event log")
    args = parser.parse_args()

    topology = Topology.from_env()
    match args.command:
        case "up":
            _up(topology)
        case "demo":
            _demo(topology, args)
        case "timeline":
            print_timeline(topology.events_path)
