"""The automation engine's outcome contract, and the node that used to skip the tool registry.

Two defects motivated this file, both of the same family: a refusal that did not look like one.

1. `run_tool` reports a refusal by RETURNING `{"ok": False, ...}` — it does not raise. The engine
   only caught exceptions, so a node whose tool call was blocked was recorded as a successful step,
   the run finished "done", and the refusal text was handed to the next node as if it were data.
2. The `http_request` node called `netguard.fetch_checked` directly. The fetch itself was hardened,
   but because the call never entered `run_tool` it skipped the scope allow-list, the ADR-004
   deny-only hook, the approval gate's risk tiering, and the ADR-005 evidence layer.

The engine-level tests here are deliberately small and database-free so the rule itself is pinned
independently of PostgreSQL; `test_workflow_api.py` proves the same behaviour through a real run.
"""
import pytest

from backend.automation import engine
from backend.automation.nodes import HttpRequestConfig
from backend.automation.registry import get_node
from backend.tools import hooks


@pytest.fixture(autouse=True)
def _clean_hooks():
    hooks._clear()
    yield
    hooks._clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def unreachable_network(monkeypatch):
    """Make any direct trip to the network boundary an explicit test failure."""
    from backend.security import netguard

    async def _forbidden(*args, **kwargs):
        raise AssertionError("the node reached netguard without passing through run_tool")

    monkeypatch.setattr(netguard, "fetch_checked", _forbidden)


# --- 1. a refusal is a node failure, not a node result ------------------------------------------

def test_a_registry_refusal_is_read_as_a_node_failure():
    """The registry's refusal contract is `ok: False`. The engine has to honour it."""
    refusal = {"ok": False, "code": "approval_required",
               "error": "This action needs your approval."}

    assert engine._refusal(refusal) is not None


def test_the_refusal_message_names_the_code_and_the_reason():
    """A run's error is the only thing a user sees, so it has to carry both halves."""
    message = engine._refusal({"ok": False, "code": "policy_denied",
                               "error": "Blocked by the offline policy."})

    assert "policy_denied" in message
    assert "Blocked by the offline policy." in message


@pytest.mark.parametrize("output", [
    {"ok": True, "results": []},          # a tool that ran
    {"matched": True, "value": "x"},      # if_branch
    {"waited": 1.0},                      # delay
    {"text": "a model said something"},   # llm_prompt
    {},                                   # a node with nothing to say
])
def test_a_normal_node_output_is_not_a_failure(output):
    """Only an explicit `ok: False` is a refusal. Nodes that never speak the contract are fine."""
    assert engine._refusal(output) is None


def test_a_non_dict_output_is_not_a_failure():
    assert engine._refusal("just a string") is None
    assert engine._refusal(None) is None


# --- 2. http_request goes through the shared registry -------------------------------------------

def test_http_request_is_a_registered_tool():
    """It has to exist in the catalog before a node can be made to route through it."""
    from backend import tools

    catalog = {t["key"]: t for t in tools.list_tools()}

    assert "http_request" in catalog, "the node's capability is not registered as a tool"
    assert catalog["http_request"]["risk"] == "network"
    assert catalog["http_request"]["writes"] is False, "GET/HEAD only — it reads, it does not write"
    assert catalog["http_request"]["schema"].get("properties")


@pytest.mark.anyio
async def test_a_deny_hook_can_stop_the_http_request_node(unreachable_network):
    """The ADR-004 seam only sees calls that pass through run_tool.

    This is the sharpest proof that the node no longer has its own private route to the network:
    a policy that denies everything must be able to stop it before netguard is ever reached.
    """
    async def refuse(call):
        return f"{call.key} is blocked by policy."

    hooks.register_pre_execute("test-policy", refuse)
    node = get_node("http_request")

    out = await node.execute({}, HttpRequestConfig(url="https://example.com/data"))

    assert out["ok"] is False
    assert out["code"] == "policy_denied"


@pytest.mark.anyio
async def test_the_http_request_node_is_refused_when_out_of_scope(unreachable_network, monkeypatch):
    """A node may only call the one tool it declares, enforced in code and not by its own honesty."""
    from backend.automation import nodes

    original = nodes.run_tool

    async def _narrowed(key, args=None, **kwargs):
        return await original(key, args, **{**kwargs, "allowed": {"web_search"}})

    monkeypatch.setattr(nodes, "run_tool", _narrowed)
    node = get_node("http_request")

    out = await node.execute({}, HttpRequestConfig(url="https://example.com/data"))

    assert out["ok"] is False
    assert "allow-list" in out["error"]


@pytest.mark.anyio
async def test_a_permitted_http_request_still_returns_status_body_and_json(monkeypatch):
    """Routing through the registry must not change what the node gives downstream nodes."""
    from backend.features import team
    from backend.security import netguard

    class _Resp:
        status_code = 200
        text = '{"value": 42}'

        def json(self):
            return {"value": 42}

    seen: dict = {}

    async def _fetch(url, **kwargs):
        seen["url"] = url
        seen["method"] = kwargs.get("method")
        seen["max_bytes"] = kwargs.get("max_bytes")
        return _Resp()

    async def _solo():
        return False

    monkeypatch.setattr(netguard, "fetch_checked", _fetch)
    monkeypatch.setattr(team, "team_mode", _solo)
    node = get_node("http_request")

    out = await node.execute({}, HttpRequestConfig(url="https://example.com/data", method="get"))

    assert out["ok"] is True
    assert out["status"] == 200
    assert out["json"] == {"value": 42}
    assert out["body"] == '{"value": 42}'
    assert seen["method"] == "GET", "the method allow-list still normalises to GET/HEAD"
    assert seen["max_bytes"] == 2_000_000, "the hard byte cap must survive the move"


@pytest.mark.anyio
async def test_an_unsupported_method_is_still_narrowed_to_get(monkeypatch):
    """The old node silently downgraded anything that was not GET/HEAD. Keep that."""
    from backend.features import team
    from backend.security import netguard

    class _Resp:
        status_code = 204
        text = ""

        def json(self):
            raise ValueError("no body")

    seen: dict = {}

    async def _fetch(url, **kwargs):
        seen["method"] = kwargs.get("method")
        return _Resp()

    async def _solo():
        return False

    monkeypatch.setattr(netguard, "fetch_checked", _fetch)
    monkeypatch.setattr(team, "team_mode", _solo)
    node = get_node("http_request")

    out = await node.execute({}, HttpRequestConfig(url="https://example.com/x", method="DELETE"))

    assert seen["method"] == "GET"
    assert out["ok"] is True
    assert out["json"] is None
