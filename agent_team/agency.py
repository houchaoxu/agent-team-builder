"""Offline discovery and pinned, verified Agency-Agents role downloads.

The compact catalog is data, never a claim of native host availability.
"""
import copy
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .adapters import PLATFORMS, _platform
from .storage import project_lock, safe_path

REPOSITORY = "msitarzewski/agency-agents"
MAX_BYTES = 256 * 1024
DATA = Path(__file__).parent / "data" / "agency-index.json"
_STOP = set("a an the and or of to for in on with is are be you your this that from as by i we my me help want need please".split())
# Small, explicit bilingual task vocabulary; callers can supply further English terms.
_ALIASES = {
    "数据库": "database sql query indexing", "慢sql": "database query optimization indexing",
    "慢查询": "database query optimization indexing", "索引": "database indexing",
    "前端": "frontend react css", "后端": "backend api architecture",
    "全栈": "full stack developer", "架构": "architecture architect design",
    "接口": "api integration", "安全": "security vulnerability audit",
    "渗透": "penetration security testing", "漏洞": "vulnerability security", "审计": "audit security",
    "测试": "testing quality assurance",
    "回归": "regression testing", "性能": "performance optimization",
    "部署": "deployment devops infrastructure", "流水线": "ci cd devops automation",
    "运维": "devops infrastructure", "容器": "docker kubernetes",
    "营销": "marketing campaign", "增长": "growth marketing",
    "品牌": "brand branding", "社交媒体": "social media",
    "小红书": "xiaohongshu", "抖音": "douyin tiktok", "微信": "wechat",
    "视频": "video content", "文案": "copywriting content",
    "搜索优化": "seo search optimization", "搜索引擎": "seo search engine",
    "设计": "design", "用户体验": "ux experience", "无障碍": "accessibility",
    "产品": "product", "需求": "requirements analysis", "项目管理": "project management",
    "数据分析": "data analytics analysis", "机器学习": "machine learning",
    "人工智能": "ai intelligence", "大模型": "llm ai", "智能体": "agent orchestration",
    "游戏": "game development", "地图": "gis geospatial", "财务": "finance financial",
    "销售": "sales", "客服": "support customer", "研究": "research",
    "移动端": "mobile app", "安卓": "android", "苹果": "ios swift",
}


def load_index():
    """Read the packaged catalog without network or project side effects."""
    return json.loads(DATA.read_text(encoding="utf-8"))


def _tokens(text):
    return [word for word in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.casefold())
            if word not in _STOP]


def _query_tokens(query, terms):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty text")
    if terms is None:
        terms = []
    if not isinstance(terms, (list, tuple)) or any(not isinstance(term, str) for term in terms):
        raise ValueError("terms must be a list of strings")
    expanded = query.casefold() + " " + " ".join(terms).casefold()
    alias_text = re.sub(r"\s+", "", expanded)
    translations = " ".join(value for key, value in _ALIASES.items() if key in alias_text)
    return set(_tokens(expanded + " " + translations))


def rank_roles(roles, query, terms=None, limit=6, offset=0):
    """BM25 candidate retrieval, with explicit bilingual task expansion.

    This ranks text evidence, not semantic suitability or host availability.
    """
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("limit must be 1 through 20")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    requested = _query_tokens(query, terms)
    documents = []
    for role in roles:
        name = str(role.get("name", ""))
        text = " ".join([name] * 3 + [str(role.get("description", ""))] +
                        list(role.get("capabilities", [])) + list(role.get("deliverables", [])))
        documents.append(Counter(_tokens(text)))
    if not documents or not requested:
        return []
    average = sum(sum(doc.values()) for doc in documents) / len(documents) or 1
    frequencies = Counter(token for doc in documents for token in doc)
    ranked = []
    for role, doc in zip(roles, documents):
        score, matches = 0.0, []
        length = sum(doc.values())
        for token in sorted(requested & doc.keys()):
            count = doc[token]
            idf = math.log(1 + (len(documents) - frequencies[token] + .5) / (frequencies[token] + .5))
            score += idf * count * 2.2 / (count + 1.2 * (.25 + .75 * length / average))
            matches.append(token)
        if score > 0:
            ranked.append(dict(copy.deepcopy(role), retrieval_score=round(score, 6),
                               retrieval_evidence={"method": "local_bm25", "terms": matches}))
    return sorted(ranked, key=lambda item: (-item["retrieval_score"], item["id"]))[offset:offset + limit]


def _normalize(card, index, platform):
    _platform(platform)
    return dict(copy.deepcopy(card), source="agency", prompt="", platforms=list(PLATFORMS),
                platform_compatible=True, status="installable", channel="agency",
                provenance={"channel": "agency", "definition_trust": .5},
                upstream={"repository": REPOSITORY, "revision": index["revision"],
                          "path": card["path"], "sha256": card["sha256"], "license": "MIT"})


def search_roles(query, terms=None, limit=6, offset=0, platform="generic", excluded_ids=None):
    index = load_index()
    excluded = set(excluded_ids or [])
    return rank_roles([_normalize(card, index, platform) for card in index["roles"] if card["id"] not in excluded],
                      query, terms, limit, offset)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Agency download redirects are not permitted")


def _download(url):
    try:
        with build_opener(_NoRedirect()).open(Request(url, headers={"User-Agent": "agent-team-builder"}), timeout=15) as response:
            data = response.read(MAX_BYTES + 1)
    except (URLError, OSError) as exc:
        raise ValueError("Agency role download failed; retry online or use a verified cached role: %s" % exc) from exc
    if len(data) > MAX_BYTES:
        raise ValueError("Agency role exceeds the 256 KB download limit")
    return data


def _validated_location(index, card):
    revision, path, digest = index.get("revision"), card.get("path"), card.get("sha256")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Agency index has an invalid pinned revision")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Agency index has an invalid content hash")
    if (not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+\.md", path)
            or PurePosixPath(path).is_absolute() or any(part in (".", "..", "") for part in path.split("/"))):
        raise ValueError("Agency index has an unsafe role path")
    return "https://raw.githubusercontent.com/%s/%s/%s" % (REPOSITORY, revision, path)


def _atomic_bytes(path, content):
    """Preserve upstream bytes and hashes on every platform, including Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch_role(root, role_id, platform="generic", offline=False):
    index = load_index()
    card = next((card for card in index["roles"] if card["id"] == role_id), None)
    if card is None:
        raise ValueError("Unknown Agency role: %s" % role_id)
    role = _normalize(card, index, platform)
    url = _validated_location(index, card)
    relative = ".agent-team/cache/agency/%s.md" % card["sha256"]
    with project_lock(root):
        cache = safe_path(root, relative)
        data = cache.read_bytes() if cache.is_file() and cache.stat().st_size <= MAX_BYTES else b""
        valid = hashlib.sha256(data).hexdigest() == card["sha256"]
        if not valid:
            if offline:
                raise ValueError("Agency role is missing or corrupt in the offline cache; fetch it online first")
            data = _download(url)
            if hashlib.sha256(data).hexdigest() != card["sha256"]:
                raise ValueError("Agency role SHA-256 verification failed; no content was cached")
            try:
                content = data.decode("utf-8")
            except UnicodeError as exc:
                raise ValueError("Agency role is not UTF-8 text") from exc
            # Recheck symlink containment immediately before atomic replacement.
            _atomic_bytes(safe_path(root, relative), data)
        else:
            content = data.decode("utf-8")
    # Carry attribution into standalone installed profiles too. Cache bytes remain
    # exactly the pinned upstream document; the license is appended only on return.
    license_text = (DATA.parent / "AGENCY-LICENSE.txt").read_text(encoding="utf-8").strip()
    prompt = content + "\n\n---\nAgency-Agents source: " + url + "\n\n" + license_text + "\n"
    role.update(prompt=prompt, source_path=str(cache))
    return role
