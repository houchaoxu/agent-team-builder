"""Conservative, standard-library-only updates for managed Skill installations.

Only stable releases of the fixed upstream repository are accepted. Checks never
interrupt normal work; installation changes require explicit approval. SHA-256
protects transport integrity, not independent publisher authenticity.
"""
import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

if os.name == "nt":
    import msvcrt
else:
    import fcntl

REPOSITORY = "houchaoxu/agent-team-builder"
MANIFEST_NAME = ".agent-team-install.json"
ASSET_NAME = "agent-team-runtime-skill.zip"
API_URL = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
INTERVAL = 7 * 86400
MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 2000
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _version(value):
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise ValueError("Expected a stable SemVer version X.Y.Z")
    return tuple(map(int, value.split(".")))


def _safe(path):
    path = Path(os.path.abspath(str(Path(path).expanduser())))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Symlink path is not supported: " + str(part))
    return path


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Invalid bundle path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts) or PurePosixPath(value).is_absolute() or ":" in value:
        raise ValueError("Unsafe bundle path: " + value)
    return value


def _manifest(skill):
    path = _safe(skill / MANIFEST_NAME)
    if not path.is_file():
        raise ValueError("Unmanaged installation: version 2.5 requires a one-time manual migration")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Installation manifest is too large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid installation manifest") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("repository") != REPOSITORY:
        raise ValueError("Unsupported installation manifest")
    _version(data.get("version"))
    installed_at = data.get("installed_at")
    if installed_at is not None and (isinstance(installed_at, bool) or not isinstance(installed_at, (int, float)) or not 0 <= installed_at < 1e12):
        raise ValueError("Invalid installation timestamp")
    files = data.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise ValueError("Invalid manifest file inventory")
    for relative, digest in files.items():
        _relative(relative)
        if relative == MANIFEST_NAME or any(p in (".cache", "__pycache__") for p in relative.split("/")):
            raise ValueError("Manifest includes mutable or reserved files")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid manifest digest")
    if not {"SKILL.md", "scripts/run.py"}.issubset(files):
        raise ValueError("Incomplete installation manifest")
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _verify(skill):
    skill = _safe(skill)
    manifest = _manifest(skill)
    actual = {}
    for root, dirs, files in os.walk(skill, followlinks=False):
        relative_root = Path(root).relative_to(skill)
        for name in list(dirs):
            relative = relative_root / name
            path = Path(root) / name
            if path.is_symlink():
                raise ValueError("Bundle contains a symlink: " + str(relative))
            if name in (".cache", "__pycache__"):
                dirs.remove(name)
        for name in files:
            relative = (relative_root / name).as_posix()
            path = Path(root) / name
            if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("Bundle contains a nonregular file: " + relative)
            if relative == MANIFEST_NAME:
                continue
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Bundle file is too large")
            actual[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != manifest["files"]:
        raise ValueError("Local files were modified, added or removed; installation is protected")
    return manifest


@contextmanager
def _lock(skill):
    skill = _safe(skill)
    lock = _safe(skill.parent / ("." + skill.name + ".update.lock"))
    try:
        stream = lock.open("a+b")
    except OSError as exc:
        raise ValueError("Update lock is inaccessible; preserve it and inspect permissions") from exc
    with stream:
        try:
            if os.name == "nt":
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another install/update operation is running; retry after it finishes") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    # Keep the inode: unlinking a lock file allows different processes to lock
    # different files at the same path. The OS releases locks on process exit.


def _timestamp(now):
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.timestamp()
    return float(now)


def _state(skill):
    path = _safe(skill / ".cache" / "update-state.json")
    try:
        if path.stat().st_size > 65536:
            return {"enabled": True}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"enabled": True}
        result = {"enabled": data.get("enabled", True) is not False}
        for key in ("last_checked", "snoozed_until"):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 1e12:
                result[key] = value
        for key in ("notified_version", "latest_version"):
            try:
                _version(data.get(key))
                result[key] = data[key]
            except ValueError:
                pass
        return result
    except (OSError, ValueError, UnicodeError):
        return {"enabled": True}


def _save_state(skill, state):
    path = _safe(skill / ".cache" / "update-state.json")
    path.parent.mkdir(exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".update-state-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_status(skill, now=None):
    """Read local preferences and installation metadata without network or writes."""
    skill = _safe(skill)
    state = _state(skill)
    try:
        installed = _manifest(skill)["version"]
    except (OSError, ValueError) as exc:
        return dict(state, status="unmanaged", notify=False, error=str(exc), next="Reinstall once to create a managed manifest")
    status = "disabled" if not state["enabled"] else "snoozed" if state.get("snoozed_until", 0) > _timestamp(now) else "current"
    return dict(state, status=status, notify=False, installed_version=installed,
                next_check_at=state.get("last_checked", _manifest(skill).get("installed_at", 0)) + INTERVAL)


def configure_updates(skill, enabled=None, snooze_days=None, now=None):
    """Persist preferences; 0 resumes reminders and 1..365 snoozes them."""
    skill = _safe(skill)
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    if snooze_days is not None and (isinstance(snooze_days, bool) or not isinstance(snooze_days, int) or not 0 <= snooze_days <= 365):
        raise ValueError("snooze_days must be an integer from 0 to 365")
    if enabled is None and snooze_days is None:
        return update_status(skill, now)
    _manifest(skill)
    with _lock(skill):
        state = _state(skill)
        if enabled is not None:
            state["enabled"] = enabled
        if snooze_days is not None:
            state["snoozed_until"] = _timestamp(now) + snooze_days * 86400 if snooze_days else 0
        _save_state(skill, state)
    return update_status(skill, now)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, initial, assets):
        self.initial = initial
        self.assets = assets

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        allowed = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
                or (self.assets and parsed.hostname not in allowed)
                or (not self.assets and newurl != self.initial)
                or (parsed.hostname == "github.com" and parsed.path != urllib.parse.urlsplit(self.initial).path)):
            raise ValueError("Refused untrusted release redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url, limit, assets=False):
    request = urllib.request.Request(url, headers={"User-Agent": "agent-team-builder-updater", "Accept": "application/vnd.github+json" if not assets else "application/octet-stream"})
    opener = urllib.request.build_opener(_Redirects(url, assets))
    with opener.open(request, timeout=5) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise ValueError("Release response exceeds size limit")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Release response exceeds size limit")
        return data


def _release():
    data = json.loads(_download(API_URL, 1024 * 1024).decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or data.get("draft") is not False or data.get("prerelease") is not False:
        raise ValueError("Release is not stable")
    tag = data.get("tag_name", "")
    version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else tag
    _version(version)
    url = "https://github.com/" + REPOSITORY + "/releases/tag/" + tag
    if data.get("html_url") != url:
        raise ValueError("Release URL does not match the fixed upstream repository")
    base = "https://github.com/" + REPOSITORY + "/releases/download/" + tag + "/"
    assets = {}
    inventory = data.get("assets")
    if not isinstance(inventory, list):
        raise ValueError("Invalid release assets")
    for asset in inventory:
        if not isinstance(asset, dict):
            raise ValueError("Invalid release asset")
        name = asset.get("name")
        if name in (ASSET_NAME, ASSET_NAME + ".sha256"):
            if name in assets or asset.get("browser_download_url") != base + name:
                raise ValueError("Release asset URL does not match the fixed upstream repository")
            assets[name] = base + name
    if len(assets) != 2:
        raise ValueError("Stable release is missing the Skill archive or checksum")
    notes = data.get("body")
    return {"version": version, "url": url, "assets": assets,
            "release_notes": notes[:2000] if isinstance(notes, str) else ""}


def check_updates(skill, force=False, now=None):
    """Check at most weekly, including failures; force bypasses all preferences.

    Each new version is notified once. Network/state errors become unavailable.
    """
    try:
        skill = _safe(skill)
        result = update_status(skill, now)
        if result["status"] == "unmanaged":
            return result
        with _lock(skill):
            state = _state(skill)
            stamp = _timestamp(now)
            base = {"installed_version": result["installed_version"]}
            if not force:
                if not state["enabled"]:
                    return dict(base, status="disabled", notify=False, next="Enable updates to resume checks")
                if state.get("snoozed_until", 0) > stamp:
                    return dict(base, status="snoozed", notify=False, snoozed_until=state["snoozed_until"], next="Wait or explicitly check with --force")
                baseline = state.get("last_checked", _manifest(skill).get("installed_at"))
                if isinstance(baseline, (int, float)) and stamp - baseline < INTERVAL:
                    return dict(base, status="skipped", notify=False, latest_version=state.get("latest_version"), next_check_at=baseline + INTERVAL)
            state["last_checked"] = stamp
            try:
                release = _bounded_release()
            except Exception as exc:
                _save_state(skill, state)
                return dict(base, status="unavailable", notify=False, error=str(exc), next_check_at=stamp + INTERVAL,
                            next="Continue the task; retry after the weekly cooldown or explicitly force a check")
            latest = release["version"]
            state["latest_version"] = latest
            available = _version(latest) > _version(base["installed_version"])
            notify = available and state.get("notified_version") != latest
            if notify:
                state["notified_version"] = latest
            _save_state(skill, state)
            return dict(base, status="update_available" if available else "current", latest_version=latest,
                        notify=notify, url=release["url"], release_notes=release["release_notes"],
                        next_check_at=stamp + INTERVAL, next="Offer a conversational upgrade preview" if available else None)
    except Exception as exc:
        return {"status": "unavailable", "notify": False, "error": str(exc), "next": "Continue the task; inspect update permissions later"}


def _extract(payload, destination, version):
    total = 0
    seen = set()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if len(archive.infolist()) > MAX_FILES:
            raise ValueError("Release archive contains too many entries")
        for entry in archive.infolist():
            name = entry.filename[:-1] if entry.is_dir() else entry.filename
            _relative(name)
            if name in seen:
                raise ValueError("Release archive contains duplicate paths")
            seen.add(name)
            parts = name.split("/")
            if parts[0] != "agent-team-runtime" or (len(parts) == 1 and not entry.is_dir()):
                raise ValueError("Unexpected release archive root")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("Release archive contains a link or special file")
            if any(part in (".cache", "__pycache__") for part in parts[1:]):
                raise ValueError("Release archive includes mutable cache files")
            total += entry.file_size
            if total > MAX_BYTES or entry.flag_bits & 1:
                raise ValueError("Release archive is too large or encrypted")
            target = destination.joinpath(*parts[1:])
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("xb") as output:
                    copied = 0
                    while True:
                        chunk = source.read(65536)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > entry.file_size or copied > MAX_BYTES:
                            raise ValueError("Release archive size mismatch")
                        output.write(chunk)
    manifest = _verify(destination)
    if manifest["version"] != version:
        raise ValueError("Release archive version does not match release metadata")


def _probe(skill, version):
    result = subprocess.run([sys.executable, "-E", str(skill / "scripts/run.py"), "--version"],
                            cwd=str(skill), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=15)
    if result.returncode or not re.search(r"(?<![0-9.])" + re.escape(version) + r"(?![0-9.])", result.stdout.strip()):
        raise ValueError("Staged runtime version check failed: " + result.stderr[-1000:])


def _backup_root(skill):
    root = _safe(skill.parent / ("." + skill.name + ".backups"))
    root.mkdir(exist_ok=True)
    return root


def _replace(skill, stage):
    """Move existing install aside, then restore it if stage activation fails."""
    root = _backup_root(skill)
    backup_id = uuid.uuid4().hex
    backup = root / backup_id
    cache = _safe(skill / ".cache")
    if cache.exists() and not (stage / ".cache").exists():
        if not cache.is_dir():
            raise ValueError("Cache root must be a directory")
        shutil.copytree(cache, stage / ".cache", symlinks=True)
    installed = _verify(skill)  # Recheck after staging, before moving installed files.
    metadata = _manifest(stage)
    for field in ("scope", "platform"):
        if field in installed:
            metadata[field] = installed[field]
    metadata["installed_at"] = time.time()
    (stage / MANIFEST_NAME).write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    skill.rename(backup)
    try:
        stage.rename(skill)
    except BaseException:
        backup.rename(skill)
        raise
    return backup_id


def upgrade(skill, approved=False):
    """Preview fixed-upstream metadata, or verify/stage/swap when approved."""
    skill = _safe(skill)
    with (_lock(skill) if approved else nullcontext()):
        installed = _verify(skill)
        release = _release()
        result = {"status": "preview", "installed_version": installed["version"],
                  "latest_version": release["version"], "url": release["url"],
                  "release_notes": release["release_notes"], "path": str(skill),
                  "next": "Apply existing user authorization with approved=True"}
        if _version(release["version"]) <= _version(installed["version"]):
            return dict(result, status="current", next=None)
        if not approved:
            return result
        checksum = _download(release["assets"][ASSET_NAME + ".sha256"], 4096, assets=True).decode("ascii").strip()
        match = re.fullmatch(r"([0-9a-fA-F]{64})(?:[ \t]+\*?" + re.escape(ASSET_NAME) + r")?", checksum)
        if not match:
            raise ValueError("Invalid release checksum file")
        payload = _download(release["assets"][ASSET_NAME], MAX_BYTES, assets=True)
        if hashlib.sha256(payload).hexdigest() != match.group(1).lower():
            raise ValueError("Release archive SHA-256 mismatch")
        stage = Path(tempfile.mkdtemp(prefix="." + skill.name + ".stage-", dir=str(skill.parent)))
        try:
            _extract(payload, stage, release["version"])
            cache = _safe(skill / ".cache")
            if cache.exists():
                if not cache.is_dir():
                    raise ValueError("Cache root must be a directory")
                shutil.copytree(cache, stage / ".cache", symlinks=True)
            _probe(stage, release["version"])
            backup_id = _replace(skill, stage)
            return dict(result, status="upgraded", backup_id=backup_id, next=None)
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def rollback(skill, backup_id, approved=False):
    """Restore a validated local backup while retaining current preferences/cache."""
    skill = _safe(skill)
    if not isinstance(backup_id, str) or not re.fullmatch(r"[0-9a-f]{32}", backup_id):
        raise ValueError("Invalid backup id")
    with (_lock(skill) if approved else nullcontext()):
        installed = _verify(skill)
        backup = _safe(skill.parent / ("." + skill.name + ".backups") / backup_id)
        saved = _verify(backup)
        result = {"status": "preview", "installed_version": installed["version"],
                  "target_version": saved["version"], "backup_id": backup_id,
                  "path": str(skill), "next": "Apply existing user authorization with approved=True"}
        if not approved:
            return result
        stage = Path(tempfile.mkdtemp(prefix="." + skill.name + ".stage-", dir=str(skill.parent)))
        try:
            shutil.copytree(backup, stage, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".cache", "__pycache__"))
            _verify(stage)
            # Validate data only; rollback does not execute old downloaded code.
            replacement_backup_id = _replace(skill, stage)
            return dict(result, status="rolled_back", backup_id=replacement_backup_id,
                        restored_backup_id=backup_id, next=None)
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def _bounded_release():
    # urllib timeouts apply to individual socket operations. Bound the complete
    # automatic metadata check too, so a slow trickle never delays user work.
    box = []
    def fetch():
        try:
            box.append((True, _release()))
        except Exception as exc:
            box.append((False, exc))
    worker = threading.Thread(target=fetch, daemon=True)
    worker.start()
    worker.join(5)
    if not box:
        raise TimeoutError("Release check exceeded five seconds")
    success, value = box[0]
    if not success:
        raise value
    return value


def main(argv=None, skill=None):
    """Machine-readable entry point used by both bundled and source runners."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check")
    check.add_argument("--force", action="store_true")
    actions.add_parser("status")
    configure = actions.add_parser("configure")
    configure.add_argument("--enabled", choices=("true", "false"))
    configure.add_argument("--snooze-days", type=int)
    apply = actions.add_parser("apply")
    apply.add_argument("--approve", action="store_true")
    restore = actions.add_parser("rollback")
    restore.add_argument("backup_id")
    restore.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        if skill is None:
            from .installer import skill_source
            skill = skill_source()
        if args.action == "check":
            result = check_updates(skill, force=args.force)
        elif args.action == "status":
            result = update_status(skill)
        elif args.action == "configure":
            result = configure_updates(skill, enabled=None if args.enabled is None else args.enabled == "true", snooze_days=args.snooze_days)
        elif args.action == "apply":
            result = upgrade(skill, approved=args.approve)
        else:
            result = rollback(skill, args.backup_id, approved=args.approve)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
