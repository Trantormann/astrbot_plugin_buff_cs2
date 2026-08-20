"""指令解析：枪名 / 皮肤名 / 磨损级别。

支持示例：
  /buff ak 燃料喷射器 久经
  /buff AK-47 燃料喷射器 fn
  /buff awp 二西莫夫            （未写磨损 -> 由调用方列出磨损让用户选）
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 磨损中文名 -> 磨损档位（数字越小磨损越低/品相越好）
WEAR_ORDER = ["崭新出厂", "略有磨损", "久经沙场", "破损不堪", "战痕累累"]

WEAR_ALIASES = {
    "崭新出厂": "崭新出厂",
    "崭新": "崭新出厂",
    "新": "崭新出厂",
    "fn": "崭新出厂",
    "factorynew": "崭新出厂",
    "略有磨损": "略有磨损",
    "略有": "略有磨损",
    "mw": "略有磨损",
    "minimalwear": "略有磨损",
    "久经沙场": "久经沙场",
    "久经": "久经沙场",
    "ft": "久经沙场",
    "fieldtested": "久经沙场",
    "破损不堪": "破损不堪",
    "破损": "破损不堪",
    "ww": "破损不堪",
    "wellworn": "破损不堪",
    "战痕累累": "战痕累累",
    "战痕": "战痕累累",
    "bs": "战痕累累",
    "battlescarred": "战痕累累",
}

# 武器别名：规范化 key -> (内部类型, 展示名)
WEAPON_ALIASES: dict[str, tuple[str, str]] = {
    # 步枪
    "ak47": ("weapon_ak47", "AK-47"),
    "ak": ("weapon_ak47", "AK-47"),
    "awp": ("weapon_awp", "AWP"),
    "m4a1": ("weapon_m4a1_silencer", "M4A1 消音版"),
    "m4a1s": ("weapon_m4a1_silencer", "M4A1 消音版"),
    "m4a1消音版": ("weapon_m4a1_silencer", "M4A1 消音版"),
    "m4a4": ("weapon_m4a1", "M4A4"),
    "m4": ("weapon_m4a1", "M4A4"),
    "aug": ("weapon_aug", "AUG"),
    "sg553": ("weapon_sg556", "SG 553"),
    "sg": ("weapon_sg556", "SG 553"),
    "famas": ("weapon_famas", "法玛斯"),
    "法玛斯": ("weapon_famas", "法玛斯"),
    "galil": ("weapon_galilar", "加利尔 AR"),
    "galilar": ("weapon_galilar", "加利尔 AR"),
    "加利尔": ("weapon_galilar", "加利尔 AR"),
    "ssg08": ("weapon_ssg08", "SSG 08"),
    "ssg": ("weapon_ssg08", "SSG 08"),
    "scout": ("weapon_ssg08", "SSG 08"),
    "scar20": ("weapon_scar20", "SCAR-20"),
    "scar": ("weapon_scar20", "SCAR-20"),
    "g3sg1": ("weapon_g3sg1", "G3SG1"),
    # 手枪
    "沙漠之鹰": ("weapon_deagle", "沙漠之鹰"),
    "沙鹰": ("weapon_deagle", "沙漠之鹰"),
    "deagle": ("weapon_deagle", "沙漠之鹰"),
    "de": ("weapon_deagle", "沙漠之鹰"),
    "usp": ("weapon_usp_silencer", "USP 消音版"),
    "usps": ("weapon_usp_silencer", "USP 消音版"),
    "格洛克": ("weapon_glock", "格洛克 18 型"),
    "格洛克18": ("weapon_glock", "格洛克 18 型"),
    "glock": ("weapon_glock", "格洛克 18 型"),
    "p2000": ("weapon_hkp2000", "P2000"),
    "p250": ("weapon_p250", "P250"),
    "fn57": ("weapon_fiveseven", "FN57"),
    "57": ("weapon_fiveseven", "FN57"),
    "fiveseven": ("weapon_fiveseven", "FN57"),
    "r8": ("weapon_revolver", "R8 左轮手枪"),
    "r8左轮": ("weapon_revolver", "R8 左轮手枪"),
    "左轮": ("weapon_revolver", "R8 左轮手枪"),
    "tec9": ("weapon_tec9", "Tec-9"),
    "tec": ("weapon_tec9", "Tec-9"),
    "双持贝瑞塔": ("weapon_elite", "双持贝瑞塔"),
    "双持": ("weapon_elite", "双持贝瑞塔"),
    "cz75": ("weapon_cz75a", "CZ75 自动手枪"),
    "cz": ("weapon_cz75a", "CZ75 自动手枪"),
    "电击枪": ("weapon_zeus", "电击枪"),
    "zeus": ("weapon_zeus", "电击枪"),
    # 微型冲锋枪
    "mp9": ("weapon_mp9", "MP9"),
    "mac10": ("weapon_mac10", "MAC-10"),
    "mac": ("weapon_mac10", "MAC-10"),
    "ump45": ("weapon_ump45", "UMP-45"),
    "ump": ("weapon_ump45", "UMP-45"),
    "p90": ("weapon_p90", "P90"),
    "mp7": ("weapon_mp7", "MP7"),
    "pp野牛": ("weapon_bizon", "PP-野牛"),
    "野牛": ("weapon_bizon", "PP-野牛"),
    "bizon": ("weapon_bizon", "PP-野牛"),
    "mp5": ("weapon_mp5sd", "MP5-SD"),
    "mp5sd": ("weapon_mp5sd", "MP5-SD"),
    # 霰弹枪
    "xm1014": ("weapon_xm1014", "XM1014"),
    "xm": ("weapon_xm1014", "XM1014"),
    "mag7": ("weapon_mag7", "MAG-7"),
    "mag": ("weapon_mag7", "MAG-7"),
    "截短霰弹枪": ("weapon_sawedoff", "截短霰弹枪"),
    "截短": ("weapon_sawedoff", "截短霰弹枪"),
    "sawedoff": ("weapon_sawedoff", "截短霰弹枪"),
    "新星": ("weapon_nova", "新星"),
    "nova": ("weapon_nova", "新星"),
    # 机枪
    "m249": ("weapon_m249", "M249"),
    "negev": ("weapon_negev", "内格夫"),
    "内格夫": ("weapon_negev", "内格夫"),
    # 刀
    "匕首": ("knife", "匕首"),
    "刀": ("knife", "匕首"),
    "爪子刀": ("knife", "爪子刀"),
    "m9刺刀": ("knife", "M9 刺刀"),
    "m9": ("knife", "M9 刺刀"),
    "蝴蝶刀": ("knife", "蝴蝶刀"),
    "蝴蝶": ("knife", "蝴蝶刀"),
    "折叠刀": ("knife", "折叠刀"),
    "刺刀": ("knife", "刺刀"),
    "熊刀": ("knife", "熊刀"),
    "短剑": ("knife", "短剑"),
    "锯齿爪刀": ("knife", "锯齿爪刀"),
    "锯齿": ("knife", "锯齿爪刀"),
    "海豹短刀": ("knife", "海豹短刀"),
    "流浪者匕首": ("knife", "流浪者匕首"),
    "流浪者": ("knife", "流浪者匕首"),
    "骷髅匕首": ("knife", "骷髅匕首"),
    "骷髅": ("knife", "骷髅匕首"),
    "求生匕首": ("knife", "求生匕首"),
    "求生": ("knife", "求生匕首"),
    "穿肠刀": ("knife", "穿肠刀"),
    "猎杀者匕首": ("knife", "猎杀者匕首"),
    "猎杀者": ("knife", "猎杀者匕首"),
    "弯刀": ("knife", "弯刀"),
    "鲍伊猎刀": ("knife", "鲍伊猎刀"),
    "鲍伊": ("knife", "鲍伊猎刀"),
    "系绳匕首": ("knife", "系绳匕首"),
    "系绳": ("knife", "系绳匕首"),
    "暗影双匕": ("knife", "暗影双匕"),
    "暗影": ("knife", "暗影双匕"),
    "廓尔喀刀": ("knife", "廓尔喀刀"),
    "廓尔喀": ("knife", "廓尔喀刀"),
    "折刀": ("knife", "折刀"),
    # 手套
    "手套": ("hands", "手套"),
    "运动手套": ("hands", "运动手套"),
    "专业手套": ("hands", "专业手套"),
    "摩托手套": ("hands", "摩托手套"),
    "驾驶手套": ("hands", "驾驶手套"),
    "手部束带": ("hands", "手部束带"),
    "九头蛇手套": ("hands", "九头蛇手套"),
    "血猎手套": ("hands", "血猎手套"),
    "狂牙手套": ("hands", "狂牙手套"),
}


@dataclass
class ParsedCommand:
    weapon_internal: str
    weapon_name: str
    skin: str
    wear: str | None = None  # 中文磨损名，未指定为 None
    stat_trak: bool = False  # 是否查询 StatTrak™ 计数器版本
    error: str | None = None


# StatTrak™ 计数器关键词（用于指定查询暗金版本）
STAT_ALIASES = {"stat", "stattrak", "statrak", "暗金", "计数器", "sst"}


def _norm(s: str) -> str:
    """规范化用于匹配：转小写、去掉空白与连字符/下划线。"""
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
    return "".join(out)


def _resolve_wear(token: str) -> str | None:
    return WEAR_ALIASES.get(_norm(token))


def parse_command(text: str) -> ParsedCommand:
    """解析 /buff 后的参数。"""
    text = (text or "").strip()
    if not text:
        return ParsedCommand("", "", "", error="用法：/buff [枪名] [皮肤名] [磨损]\n例如：/buff ak 燃料喷射器 久经")
    tokens = text.split()

    # 1. 提取磨损（匹配到的首个 token，从尾部优先）
    wear = None
    wear_idx = -1
    for i in range(len(tokens) - 1, -1, -1):
        w = _resolve_wear(tokens[i])
        if w:
            wear = w
            wear_idx = i
            break
    rest = [t for j, t in enumerate(tokens) if j != wear_idx]

    # 1.5 提取 StatTrak 关键词
    stat_trak = False
    stat_indices = {j for j, t in enumerate(rest) if _norm(t) in STAT_ALIASES}
    if stat_indices:
        stat_trak = True
        rest = [t for j, t in enumerate(rest) if j not in stat_indices]

    if not rest:
        return ParsedCommand("", "", "", error="用法：/buff [枪名] [皮肤名] [磨损]\n例如：/buff ak 燃料喷射器 久经")

    # 2. 从头部尽量长地匹配枪名
    matched = None
    for i in range(len(rest), 0, -1):
        key = _norm(" ".join(rest[:i]))
        if key in WEAPON_ALIASES:
            matched = (i, key)
            break
    if not matched:
        return ParsedCommand(
            "",
            "",
            "",
            error="没认出枪名。支持 AK/AWP/M4/沙鹰/蝴蝶刀/手套 等，先写枪名再写皮肤，例如：/buff ak 燃料喷射器 久经",
        )
    consume, key = matched
    weapon_internal, weapon_name = WEAPON_ALIASES[key]
    skin_tokens = rest[consume:]
    skin = " ".join(skin_tokens).strip()
    if not skin:
        return ParsedCommand(
            weapon_internal,
            weapon_name,
            "",
            wear=wear,
            stat_trak=stat_trak,
            error="还差皮肤名，例如：/buff ak 燃料喷射器 久经",
        )
    return ParsedCommand(weapon_internal, weapon_name, skin, wear=wear, stat_trak=stat_trak)


def extract_wear_from_name(name: str) -> str | None:
    """从商品名提取磨损中文名。

    兼容两种命名：AK-47 | 燃料喷射器 (久经沙场)
              以及 AK-47 | 燃料喷射器 (久经沙场) (StatTrak™)
    """
    if not name:
        return None
    for w in WEAR_ORDER:
        if f"({w})" in name:
            return w
    return None
