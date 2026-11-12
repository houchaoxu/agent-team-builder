import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import pytest

from agent_team import agency


def test_real_index_is_compact_pinned_and_offline():
    with patch.object(agency, "build_opener", side_effect=AssertionError("network")):
        index = agency.load_index()
        assert len(index["roles"]) >= 280
        assert index["revision"] == "8ae6164602c95ca78828b148b9052460ee426885"
        for card in index["roles"]:
            assert card["id"].startswith("agency-") and len(card["id"]) <= 80
            assert sum(len(card[key]) for key in ("name", "description")) + sum(map(len, card["capabilities"])) <= 600
            assert card["path"].split("/")[0] not in ("skills", "examples", "integrations", "strategy")
            agency._validated_location(index, card)
        assert agency.search_roles("database query optimization")[0]["name"] == "Database Optimizer"


@pytest.mark.parametrize("query,expected", [
    ("帮我排查数据库慢查询", "Database Optimizer"),
    ("小红书营销增长", "Xiaohongshu Specialist"),
    ("搭建部署流水线", "DevOps Automator"),
    ("security penetration vulnerability audit", "Penetration Tester"),
])
def test_real_cross_language_retrieval(query, expected):
    roles = agency.search_roles(query)
    assert expected in [role["name"] for role in roles[:3]]
    for role in roles:
        assert role["source"] == "agency" and role["prompt"] == ""
        assert role["status"] == "installable" and role["platform_compatible"]
        assert role["provenance"]["channel"] == "agency"
        assert role["upstream"]["license"] == "MIT"


@pytest.mark.parametrize("query", ["帮我排查慢 SQL", "慢 SQL"])
def test_chinese_alias_with_spaced_sql(query):
    assert agency.search_roles(query)[0]["id"] == "agency-engineering-database-optimizer"


def test_no_irrelevant_roles_pagination_and_host_terms():
    assert agency.search_roles("zxqvvunlikelyterm") == []
    assert agency.search_roles("完全没有词条的量子猫") == []
    assert agency.search_roles("需求用自己的话表达", terms=["database", "query", "optimization"])[0]["name"] == "Database Optimizer"
    whole = agency.search_roles("security testing", limit=20)
    assert agency.search_roles("security testing", limit=4, offset=4) == whole[4:8]
    assert whole == agency.search_roles("security testing", limit=20)
    assert agency.rank_roles([], "query") == []


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 21}, {"limit": True}, {"offset": -1}, {"terms": "sql"}])
def test_search_argument_validation(kwargs):
    with pytest.raises(ValueError):
        agency.search_roles("database", **kwargs)


@pytest.fixture
def document(monkeypatch):
    content = b"---\r\nname: Test Role\r\n---\r\n\r\nFull role instructions.\r\n"
    digest = hashlib.sha256(content).hexdigest()
    card = {"id": "agency-test", "name": "Test Role", "description": "Test fixture",
            "capabilities": ["testing"], "deliverables": [], "path": "testing/test.md", "sha256": digest}
    index = {"revision": "a" * 40, "roles": [card]}
    monkeypatch.setattr(agency, "load_index", lambda: copy.deepcopy(index))
    return content, card, index


def test_fetch_cache_offline_and_repair(tmp_path, document, monkeypatch):
    content, card, _ = document
    requests = []
    def download(url):
        requests.append(url)
        return content
    monkeypatch.setattr(agency, "_download", download)
    role = agency.fetch_role(tmp_path, card["id"])
    assert role["prompt"].encode().startswith(content)
    assert "Copyright (c) 2025 AgentLand Contributors" in role["prompt"]
    assert "Permission is hereby granted" in role["prompt"]
    assert "https://raw.githubusercontent.com/msitarzewski/agency-agents/" in role["prompt"]
    assert role["upstream"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert requests == ["https://raw.githubusercontent.com/msitarzewski/agency-agents/" + "a" * 40 + "/testing/test.md"]
    cache = Path(role["source_path"])
    assert cache.read_bytes() == content
    assert agency.fetch_role(tmp_path, card["id"], offline=True)["prompt"] == role["prompt"]
    assert len(requests) == 1
    cache.write_text("corrupt")
    with pytest.raises(ValueError, match="offline cache"):
        agency.fetch_role(tmp_path, card["id"], offline=True)
    assert agency.fetch_role(tmp_path, card["id"])["prompt"] == role["prompt"]
    assert len(requests) == 2


def test_missing_cache_and_bad_download(tmp_path, document, monkeypatch):
    _, card, _ = document
    with pytest.raises(ValueError, match="offline cache"):
        agency.fetch_role(tmp_path, card["id"], offline=True)
    monkeypatch.setattr(agency, "_download", lambda url: b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        agency.fetch_role(tmp_path, card["id"])
    assert not list((tmp_path / ".agent-team").rglob("*.md"))
    with pytest.raises(ValueError, match="Unknown"):
        agency.fetch_role(tmp_path, "unrecognized")


@pytest.mark.parametrize("path", ["../escape.md", "/absolute.md", "testing/../../escape.md", "https://evil/a.md", "testing/a%20.md", "testing\\a.md", "testing//a.md"])
def test_reject_unsafe_upstream_path(tmp_path, document, path, monkeypatch):
    _, card, index = document
    index["roles"][0]["path"] = path
    monkeypatch.setattr(agency, "_download", lambda _: pytest.fail("unsafe download"))
    with pytest.raises(ValueError, match="unsafe role path"):
        agency.fetch_role(tmp_path, card["id"])


def test_cache_symlink_escape(tmp_path, document):
    _, card, _ = document
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (tmp_path / ".agent-team").mkdir()
    (tmp_path / ".agent-team/cache").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes project"):
        agency.fetch_role(tmp_path, card["id"])


def test_downloader_limits_timeout_redirect_and_errors(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, count):
            assert count == agency.MAX_BYTES + 1
            return b"x" * count
    class Opener:
        def open(self, request, timeout):
            assert timeout == 15
            return Response()
    monkeypatch.setattr(agency, "build_opener", lambda handler: Opener())
    with pytest.raises(ValueError, match="256 KB"):
        agency._download("https://raw.githubusercontent.com/example")
    with pytest.raises(ValueError, match="redirects"):
        agency._NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil")
    monkeypatch.setattr(agency, "build_opener", lambda _: (_ for _ in ()).throw(URLError("offline")))
    with pytest.raises(ValueError, match="download failed"):
        agency._download("https://raw.githubusercontent.com/example")


@pytest.mark.parametrize("field,value", [("revision", "main"), ("sha256", "../x")])
def test_invalid_pin_rejected(tmp_path, document, field, value):
    _, card, index = document
    if field == "revision":
        index[field] = value
    else:
        card[field] = value
    with pytest.raises(ValueError, match="invalid"):
        agency.fetch_role(tmp_path, card["id"])


def test_maintainer_build_only_roles_and_reuses_unchanged_cards(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts/build_agency_index.py"
    spec = importlib.util.spec_from_file_location("build_agency_index", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout = tmp_path / "checkout"
    (checkout / "engineering").mkdir(parents=True)
    role = "---\nname: Example\ndescription: Database specialist\n---\n## Query optimization\nLong prompt body"
    (checkout / "engineering/example.md").write_text(role)
    (checkout / "engineering/README.md").write_text("Not an agent")
    (checkout / "engineering/skills").mkdir()
    (checkout / "engineering/skills/skill.md").write_text(role)
    (checkout / "examples").mkdir()
    (checkout / "examples/example.md").write_text(role)
    (checkout / "LICENSE").write_text("MIT License fixture")
    monkeypatch.setattr(module.subprocess, "check_output", lambda args, **kw: "a" * 40 if args[-1] == "HEAD" else "")
    output = tmp_path / "data/index.json"
    module.build(checkout, output)
    first = json.loads(output.read_text())
    assert len(first["roles"]) == 1
    assert first["roles"][0]["capabilities"] == ["engineering", "Query optimization"]
    monkeypatch.setattr(module, "compact", lambda *args: pytest.fail("unchanged card was reparsed"))
    module.build(checkout, output)
    assert json.loads(output.read_text()) == first
    assert (output.parent / "AGENCY-LICENSE.txt").read_text() == "MIT License fixture"
