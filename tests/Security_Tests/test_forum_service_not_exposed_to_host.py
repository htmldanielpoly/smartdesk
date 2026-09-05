"""Security test — forum-service must not be reachable from outside Docker.

Verifies CRITICAL finding #1 from the code review: docker-compose.yml
publishes forum-service's port 8001 to the host via a "ports" mapping, even
though api-service/app/routers/forums.py's module docstring documents
forum-service as living only on the private Docker network, reachable
exclusively through the api-service gateway (the only service meant to be
publicly exposed).

PASS means: forum-service has no host-published "ports" entry for 8001 in
docker-compose.yml (using "expose" instead is fine — that documents the port
to other containers without publishing it to the host). FAIL means anyone who
can reach the host's network can hit forum-service directly on 8001, bypassing
the gateway and any protections that only live there.

Pure static-config test — reads docker-compose.yml directly, no running
stack required.
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def _forum_service_config() -> dict:
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    return compose["services"]["forum-service"]


def test_forum_service_ports_do_not_publish_8001_to_host():
    forum_service = _forum_service_config()
    published = forum_service.get("ports", [])

    exposes_8001 = any("8001" in str(mapping) for mapping in published)

    assert not exposes_8001, (
        "forum-service publishes port 8001 to the host via 'ports': "
        f"{published!r}. This contradicts the internal-only network "
        "assumption documented in api-service/app/routers/forums.py and lets "
        "any client that can reach the host bypass the api-service gateway "
        "entirely. Use 'expose' instead of 'ports' (or drop the mapping) so "
        "forum-service stays reachable only from other containers on the "
        "'smartdesk' network."
    )
