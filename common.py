"""Shared configuration and strict response handling. Python 3.10+."""
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


class MonitorError(Exception):
    def __init__(self, code, message, retry_after=0):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


class StateLock:
    """OS-owned non-blocking lock; automatically released on process exit."""
    def __init__(self, path):
        self.path = Path(str(path) + ".lock")
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise MonitorError("state_locked", "同一状态文件已有监控进程运行；请避免重复启动。") from None
        return self

    def __exit__(self, *_):
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise MonitorError("config_file", "JSON 文件不可读或格式错误；请检查文件。") from None


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def expand(obj, variables=None):
    variables = variables or {}
    if isinstance(obj, dict):
        return {k: expand(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand(v, variables) for v in obj]
    if not isinstance(obj, str):
        return obj

    def replace(match):
        key = match.group(1)
        value = variables.get(key, os.environ.get(key))
        if value is None or value == "":
            raise MonitorError("missing_variable", f"缺少配置变量：{key}")
        return str(value)
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, obj)


def get_path(obj, path):
    if path in ("", "$", None):
        return obj
    try:
        for key in path.split("."):
            obj = obj[int(key)] if isinstance(obj, list) else obj[key]
        return obj
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise MonitorError("schema", "响应字段缺失；检查字段路径及登录状态。") from None


def set_path(obj, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        obj = obj.setdefault(key, {})
    obj[keys[-1]] = value


def origin(url):
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise MonitorError("config_url", "需要不含账号密码的绝对 HTTP(S) 地址。")
    return f"{p.scheme}://{p.hostname.lower()}:{p.port or (443 if p.scheme == 'https' else 80)}"


def integer(value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value).strip()):
        raise MonitorError("schema", "GPU 数量必须是非负整数，不能缺失或包含单位。")
    return int(str(value).strip())


def validate_payload(data, rule):
    if rule and rule.get("path"):
        value = get_path(data, rule["path"])
        if value in rule.get("auth_values", []):
            raise MonitorError("auth", "会话失效或没有权限；重新登录并检查租户/私有云范围。")
        if value not in rule["values"]:
            raise MonitorError("api_business", "接口返回非成功业务状态；检查接口与账号权限。")


def parse_json_response(status, body, headers):
    if status in (401, 403):
        raise MonitorError("auth", "会话失效或没有权限；更新 Cookie/Token 或重新登录。")
    if 300 <= status < 400:
        raise MonitorError("redirect", "接口返回重定向；核对最终接口地址和登录状态。")
    if status == 429:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        wait = 0
        value = headers.get("Retry-After", headers.get("retry-after", "0"))
        try:
            wait = max(0, float(value))
        except (ValueError, TypeError):
            try:
                wait = max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
        raise MonitorError("rate_limit", "接口限流；等待后重试。", wait)
    if not 200 <= status < 300:
        raise MonitorError(f"http_{status}", f"接口 HTTP {status}；本轮数据不参与状态比较。")
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        raise MonitorError("not_json", "接口未返回 JSON；可能进入登录页或地址不正确。") from None


def normalize(items, mapping):
    """A record is either one resource pool/machine, or one physical GPU card."""
    result = {}
    fields = mapping["fields"]
    for raw in items:
        if any(get_path(raw, path) not in allowed for path, allowed in mapping.get("include_values", {}).items()):
            continue
        row = {k: get_path(raw, v) for k, v in fields.items() if v is not None}
        if "monitor_availability" in raw:
            row["availability"] = raw["monitor_availability"]
        if any(row.get(k) is None or str(row[k]).strip() == "" for k in ("id", "model")):
            raise MonitorError("schema", "每条记录必须有稳定 ID 和 GPU 型号。")
        row["id"], row["model"] = str(row["id"]).strip(), str(row["model"]).strip()
        row["status"] = str(row.get("status", ""))
        row["region"] = str(row.get("region", ""))
        if mapping.get("mode", "counts") == "cards":
            if "status" not in fields or fields["status"] is None:
                raise MonitorError("config", "cards 模式必须配置 status 字段。")
            idle = row["status"].casefold() in [str(s).casefold() for s in mapping["idle_values"]]
            # Optional extra predicates for fully unbound physical cards.
            idle = idle and all(get_path(raw, path) in values
                                for path, values in mapping.get("idle_require", {}).items())
            row["free"] = int(idle)
            row["total"] = 1
        else:
            row["free"] = integer(row.get("free"))
            row["total"] = integer(row["total"]) if "total" in row else None
        if row["total"] is not None and row["free"] > row["total"]:
            raise MonitorError("schema", "空闲卡数大于总卡数；请检查字段含义。")
        if row["id"] in result:
            raise MonitorError("duplicate_id", "出现重复资源 ID；检查分页、重复行或改用唯一 ID。")
        result[row["id"]] = row
    return result


def select_snapshot(rows, filters):
    selected, totals, eligible = {}, {}, {}
    mode = filters.get("model_match", "contains")
    if mode not in ("contains", "exact", "regex"):
        raise MonitorError("config", "model_match 只支持 contains/exact/regex。")
    for key, row in rows.items():
        model = row["model"]
        patterns = filters.get("models", [])
        def matches(pattern):
            if mode == "regex":
                return bool(re.search(pattern, model, re.I))
            if mode == "exact":
                return pattern.casefold() == model.casefold()
            return pattern.casefold() in model.casefold()
        if patterns and not any(matches(p) for p in patterns):
            continue
        if filters.get("regions") and row["region"] not in filters["regions"]:
            continue
        # Keep zero/low-free rows in the snapshot to detect transitions back to zero.
        selected[key] = row
        allowed = filters.get("allowed_statuses", [])
        usable = not allowed or row["status"] in allowed
        enough = row["free"] >= filters.get("min_free_per_resource", 1)
        if filters.get("only_free", True):
            enough = enough and row["free"] > 0
        if usable and enough:
            eligible[key] = row
            group = model.casefold()
            totals[group] = totals.get(group, 0) + row["free"]
    available = any(n >= filters.get("min_total_free_per_model", 1) for n in totals.values())
    return {"resources": selected, "eligible": eligible, "free_by_model": totals, "available": available}
