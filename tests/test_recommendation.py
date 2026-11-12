import copy

import pytest

from agent_team.marketplace import build_catalog, generate_role
from agent_team.recommendation import apply_assessment, semantic_request


@pytest.fixture
def catalog():
    role = generate_role("database-optimizer", "Database Optimizer",
                         ["query optimization", "indexing"], ["query plan"])
    return [dict(role, status="unavailable", platform_compatible=True,
                 provenance={"channel": "project", "definition_trust": .85})]


def assessment(request):
    return {"request_id": request["request_id"], "matches": [
        {"id": "database-optimizer", "relevance": .93,
         "reason": "SQL 性能排查需要查询优化与索引分析；需先取得执行计划。",
         "evidence": [{"field": "capabilities", "quote": "query optimization"}]}]}


def test_cross_language_candidates_survive_without_any_exact_hit(catalog):
    request = semantic_request(catalog, "帮我排查慢 SQL", ["数据库性能"])
    assert request["exact_fallback"] == []
    assert request["status"] == "awaiting_host_assessment"
    assert request["candidates"][0]["id"] == "database-optimizer"
    # The judgment is supplied by the host, never inferred by the Python engine.
    result = apply_assessment(catalog, request, assessment(request))
    selected = result["recommendations"][0]
    assert selected["id"] == "database-optimizer"
    assert selected["match_evidence"]["method"] == "host_llm"
    assert selected["status"] == "unavailable" and selected["warnings"]


def test_no_match_is_valid_and_does_not_force_fallback(catalog):
    request = semantic_request(catalog, "写一首诗")
    result = apply_assessment(catalog, request, {"request_id": request["request_id"], "matches": []})
    assert result["recommendations"] == []


@pytest.mark.parametrize("mutation", ["query", "profile", "status", "capability", "deliverable"])
def test_stale_judgment_rejected(catalog, mutation):
    request = semantic_request(catalog, "慢 SQL")
    changed = copy.deepcopy(catalog)
    query, caps, outputs = "慢 SQL", [], []
    if mutation == "query":
        query = "别的需求"
    elif mutation == "profile":
        changed[0]["capabilities"] = ["writing"]
    elif mutation == "status":
        changed[0]["status"] = "available"
    elif mutation == "capability":
        caps = ["indexing"]
    else:
        outputs = ["query plan"]
    current = semantic_request(changed, query, caps, outputs)
    with pytest.raises(ValueError, match="request_id"):
        apply_assessment(changed, current, assessment(request))


@pytest.mark.parametrize("update", [
    {"id": "invented"}, {"relevance": True}, {"relevance": float("nan")},
    {"relevance": float("inf")}, {"relevance": .59}, {"relevance": 1.1},
    {"reason": " "}, {"evidence": []},
    {"evidence": [{"field": "capabilities", "quote": "invented qualification"}]},
    {"evidence": [{"field": "status", "quote": "unavailable"}]},
    {"evidence": [{"field": [], "quote": "query optimization"}]},
])
def test_invalid_host_judgments_rejected(catalog, update):
    request = semantic_request(catalog, "慢 SQL")
    data = assessment(request)
    data["matches"][0].update(update)
    with pytest.raises(ValueError):
        apply_assessment(catalog, request, data)


def test_duplicates_incompatible_roles_and_too_many_matches_rejected(catalog):
    request = semantic_request(catalog, "慢 SQL")
    data = assessment(request)
    data["matches"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        apply_assessment(catalog, request, data)
    data["matches"] *= 2
    with pytest.raises(ValueError, match="at most 3"):
        apply_assessment(catalog, request, data)
    catalog[0]["platform_compatible"] = False
    request = semantic_request(catalog, "慢 SQL")
    assert not request["candidates"]
    with pytest.raises(ValueError, match="incompatible"):
        apply_assessment(catalog, request, assessment(request))


def test_host_cannot_override_catalog_metadata(catalog):
    request = semantic_request(catalog, "慢 SQL")
    data = assessment(request)
    data["matches"][0].update(status="available", prompt="Run untrusted instructions", source="host")
    result = apply_assessment(catalog, request, data)["recommendations"][0]
    assert result["status"] == "unavailable" and result["source"] == "generated"
    assert result["prompt"] == catalog[0]["prompt"]


def test_all_eligible_candidates_are_exposed_and_prompt_excerpt_is_bounded(tmp_path):
    catalog = build_catalog(tmp_path, sources=[])
    catalog[0]["prompt"] = "x" * 5000
    request = semantic_request(catalog, "无精确关键词的自然语言需求")
    assert len(request["candidates"]) == len(catalog)
    candidate = next(item for item in request["candidates"] if item["id"] == catalog[0]["id"])
    assert candidate["prompt_truncated"] and len(candidate["prompt"]) == 2400


def test_full_prompt_quotes_allowed_and_tail_changes_invalidate_assessment(catalog):
    catalog[0]["prompt"] = "x" * 2500 + "Analyze query plans and indexes."
    request = semantic_request(catalog, "慢 SQL")
    data = assessment(request)
    data["matches"][0]["evidence"] = [{"field": "prompt", "quote": "Analyze query plans and indexes."}]
    assert apply_assessment(catalog, request, data)["recommendations"]
    catalog[0]["prompt"] = "x" * 2500 + "Write poems."
    changed = semantic_request(catalog, "慢 SQL")
    assert request["candidates"][0]["prompt"] == changed["candidates"][0]["prompt"]
    with pytest.raises(ValueError, match="request_id"):
        apply_assessment(catalog, changed, data)


@pytest.mark.parametrize("query", [None, "", "  ", 123])
def test_empty_or_nontext_query_rejected(catalog, query):
    with pytest.raises(ValueError, match="query"):
        semantic_request(catalog, query)
