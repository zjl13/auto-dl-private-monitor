"""AutoDL private-cloud sharing adapter; all quantities remain physical card counts."""
import copy

from common import MonitorError, get_path, integer, set_path, validate_payload


def optional_path(data, path):
    if path is None:
        return False, None
    try:
        return True, get_path(data, path)
    except MonitorError:
        return False, None


def adapt_private(items, config, fetch_stock=None):
    settings = config.get("availability", {})
    if settings.get("adapter") != "autodl_private":
        return items
    sharing = settings.get("sharing", "auto")
    definition = settings.get("free_definition", "exclusive")
    if sharing not in ("auto", "disabled", "enabled") or definition not in ("exclusive", "allocatable"):
        raise MonitorError("config_sharing", "sharing=auto/disabled/enabled；free_definition=exclusive/allocatable。")
    result = copy.deepcopy(items)
    for row in result:
        if get_path(row, settings.get("machine_type_path", "machine_type")) != "gpu":
            continue
        present, raw_capacity = optional_path(row, settings.get("capacity_path", "gpu_max_instance_num"))
        capacity = integer(raw_capacity) if present else None
        if sharing == "auto" and capacity is None:
            raise MonitorError("sharing_unknown", "无法自动识别多租开关；检查 capacity_path 或显式选择模式。")
        if sharing == "disabled" and capacity is not None and capacity > 1:
            raise MonitorError("sharing_mismatch", "主机实际启用了多租，与 sharing=disabled 不符；本轮不更新状态。")
        shared = sharing == "enabled" or (sharing == "auto" and capacity > 1)
        row["monitor_availability"] = {"sharing": shared, "definition": definition, "unit": "physical_cards"}
        if not shared:
            continue
        if fetch_stock is None:
            raise MonitorError("stock_required", "多租计数需要逐卡接口；请使用 API 模式并配置 stock 查询。")
        stock = settings["stock"]
        request = copy.deepcopy(stock["request"])
        target = request.setdefault(stock.get("location", "json"), {})
        set_path(target, stock["machine_parameter"], get_path(row, config["mapping"]["fields"]["id"]))
        data = fetch_stock(request)
        validate_payload(data, stock.get("success", config["api"].get("success")))
        cards = get_path(data, stock["items_path"])
        if not isinstance(cards, list):
            raise MonitorError("stock_schema", "逐卡接口必须返回完整的 GPU 数组。")
        if stock.get("total_path"):
            if integer(get_path(data, stock["total_path"])) != len(cards):
                raise MonitorError("stock_partial", "逐卡列表不完整，不能计算可用卡数。")
        elif not stock.get("complete_list_confirmed", False):
            raise MonitorError("stock_scope", "请确认逐卡接口一次返回全部卡，或配置 total_path。")
        if not cards and integer(get_path(row, config["mapping"]["fields"]["total"])) > 0:
            raise MonitorError("stock_empty", "主机存在 GPU，但逐卡列表为空；检查权限和完整性，本轮不更新。")
        seen, free, fully_idle = set(), 0, 0
        for card in cards:
            key = get_path(card, stock.get("id_path", "gpu_uuid"))
            if not isinstance(key, str) or not key or key in seen:
                raise MonitorError("stock_id", "逐卡列表存在无效或重复 GPU UUID。")
            seen.add(key)
            reserved = get_path(card, stock.get("reserved_path", "reserved"))
            if type(reserved) is not bool:
                raise MonitorError("stock_reserved", "reserved 必须是 JSON 布尔值；请适配实际响应类型。")
            if definition == "exclusive":
                has_bindings, bindings = optional_path(card, stock.get("bindings_path", "gpu_bindings"))
                has_legacy, legacy = optional_path(card, stock.get("legacy_instance_path", "instance_uuid"))
                if not has_bindings and not has_legacy:
                    raise MonitorError("stock_bindings", "缺少实例绑定字段，无法判定整卡完全空闲。")
                if has_bindings and bindings is not None and not isinstance(bindings, list):
                    raise MonitorError("stock_bindings", "gpu_bindings 必须是数组或 null。")
                unbound = not bindings and not legacy
                fully_idle += int(not reserved and unbound)
            free += int(not reserved)
        value = fully_idle if definition == "exclusive" else free
        set_path(row, config["mapping"]["fields"]["free"], value)
        set_path(row, config["mapping"]["fields"]["total"], len(cards))
        row["monitor_availability"]["source"] = "gpu_stock"
    return result
