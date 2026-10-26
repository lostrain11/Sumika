#!/usr/bin/env python3
"""Build Sumika's curated DSH plugin market index (format 1).

The output is a normal DSH plugin-market index. DSH's own Plugins page reads
it; this repository does not implement a second installer or a second market.

Run from the repository root:

    python -B tools/build_sumika_plugin_catalog.py

The command fetches the public community index at build time. Deployments use
the committed output; they never fetch or merge catalogs at runtime. Pass
``--source`` to use a local snapshot and ``--output`` to write elsewhere.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = "https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json"
DEFAULT_OUTPUT = ROOT / "ui" / "app" / "plugin-catalog.json"

# Curated entries. A fallback is used only when the public index does not list
# the package (GitHub-only plugins); it must pin an exact commit.
SELECTION = [
    {
        "name": "dsh-phone",
        "category": "life",
        "labels": ["sumika-reviewed", "sumika-experimental", "requires-android"],
        "title": {"zh": "手机", "en": "Phone"},
        "description": {
            "zh": "给 DSH 一台 Android 模拟器和 phone_* 工具，可在右侧栏查看并操作手机；仅作为可选的外部世界能力。",
            "en": "An Android emulator and phone_* tools for DSH, shown in the sidebar; optional external-world capability.",
        },
        "keywords": ["android", "phone", "emulator", "bilibili"],
        "fallback": {
            "version": "0.3.0",
            "publishTimestamp": 1792994143,
            "commit": "6f2baa8b1391e185ff885d47e40283ffe7dc80dd",
            "repository": "https://github.com/Thatgfsj/dsh-phone",
            "engines": {"dsh": ">=0.2.1-rc.2 <0.3.0"},
        },
    },
    {
        "name": "dsh-bili-scroll",
        "version": "2.1.0",
        "category": "life",
        "labels": ["sumika-reviewed", "read-only", "requires-bili-login", "requires-python"],
        "title": {"zh": "B站值班", "en": "Bilibili duty"},
        "description": {
            "zh": "按关键词浏览 B站、读字幕并写日报；默认只读；需要本机 Python 或 uv 建依赖环境。",
            "en": "Browse Bilibili by keyword, read subtitles and write a daily report; read-only by default and needs local Python or uv.",
        },
        "keywords": ["bilibili", "b站", "daily", "read-only"],
        "fallback": {
            "version": "2.1.0",
            "publishTimestamp": 1792835570,
            "source": {"type": "npm"},
            "engines": {"dsh": ">=0.1.7-rc.1"},
        },
    },
    {
        "name": "dsh-bili-interact",
        "category": "life",
        "labels": ["sumika-reviewed", "sumika-experimental", "writes-off", "requires-python"],
        "title": {"zh": "B站互动（写操作默认关）", "en": "Bilibili interactions (writes off)"},
        "description": {
            "zh": "为 B站值班补上点赞、收藏、关注、转发和动态；写操作默认关闭，有代码级每日上限。",
            "en": "Adds likes, favorites, follows, shares and dynamics to the Bilibili duty; writes are off by default with hard daily caps.",
        },
        "keywords": ["bilibili", "interaction", "write", "consent"],
        "fallback": {
            "version": "0.0.9",
            "publishTimestamp": 1792405002,
            "commit": "d7b2a55b0b43af0985a00da40d3abc4a71bcd305",
            "repository": "https://github.com/annasleepy/dsh-bili-interact",
            "engines": {},
        },
    },
    {
        "name": "dsh-fish",
        "category": "life",
        "labels": ["sumika-experimental", "requires-bili-login", "requires-python", "requires-ffmpeg"],
        "title": {"zh": "大肥鱼式生活", "en": "Fish-like life"},
        "description": {
            "zh": "事件流人格、记忆权重与遗忘、拒绝与反思、B站外部世界；仅作生活循环参考，不替代 Sumika 角色。",
            "en": "Event-sourced personality, weighted memory, refusal/reflection and Bilibili as an outside world; reference only, not Sumika's role.",
        },
        "keywords": ["life", "persona", "memory", "bilibili"],
        "fallback": {
            "version": "0.5.1",
            "publishTimestamp": 1792960470,
            "commit": "a0dac972e8867829e6c33a6d6b692aea868bed10",
            "repository": "https://github.com/ssamurias/dsh-fish",
            "engines": {},
        },
    },
    {
        "name": "@kenz1117/dsh-engram",
        "version": "0.10.0",
        "category": "memory",
        "labels": ["sumika-experimental", "local-only", "requires-build-approval"],
        "title": {"zh": "记忆宫殿（实验）", "en": "Engram memory (experimental)"},
        "description": {
            "zh": "本地 SQLite 长期记忆：FTS5 + 向量 RRF、证据门、SM-2 复习、巩固与衰减；原生依赖需要 pnpm 构建批准，暂作算法参考。",
            "en": "Local SQLite long-term memory with FTS5 + vector RRF, evidence gate, SM-2 review, consolidation and decay; native dependencies need pnpm build approval, currently a reference.",
        },
        "keywords": ["memory", "sqlite", "fts5", "rrf", "local"],
        "fallback": {
            "version": "0.10.0",
            "publishTimestamp": 1792810728,
            "source": {"type": "npm"},
            "engines": {"dsh": ">=0.1.2-alpha.2 <0.3.0-0"},
        },
    },
    {
        "name": "dsh-pet-live2d",
        "version": "3.3.3",
        "category": "pet",
        "labels": ["sumika-experimental"],
        "title": {"zh": "Live2D 桌宠", "en": "Live2D pet"},
        "description": {
            "zh": "Live2D 桌宠渲染与桌面悬浮窗口；仅作渲染器参考，Sumika 现有原生桌宠不替换。",
            "en": "Live2D pet rendering and a desktop overlay; renderer reference only, Sumika's native pet stays.",
        },
        "keywords": ["live2d", "desktop", "pet"],
        "fallback": {
            "version": "3.3.3",
            "publishTimestamp": 1792467609,
            "source": {"type": "npm"},
            "engines": {},
        },
    },
    {
        "name": "dshmarket",
        "version": "1.70.2",
        "category": "market",
        "labels": ["sumika-experimental"],
        "title": {"zh": "dsh-market（实验）", "en": "dsh-market (experimental)"},
        "description": {
            "zh": "社区插件市场 UI、搜索、主题与更新；与原生 Discover 重复，仅作为可选实验，不默认安装。",
            "en": "Community plugin market UI, search, themes and updates; overlaps native Discover and is optional.",
        },
        "keywords": ["market", "plugins", "themes"],
        "fallback": {
            "version": "1.70.2",
            "publishTimestamp": 1792861583,
            "source": {"type": "npm"},
            "engines": {},
        },
    },
]

CATEGORIES = {
    "life": {"title": {"zh": "生活与外部世界", "en": "Life & outside world"}},
    "memory": {"title": {"zh": "记忆", "en": "Memory"}},
    "pet": {"title": {"zh": "桌宠与形象", "en": "Pet & presence"}},
    "market": {"title": {"zh": "插件市场", "en": "Plugin market"}},
    "desktop": {"title": {"zh": "桌面与游戏", "en": "Desktop & games"}},
}

LABELS = {
    "sumika-reviewed": {"title": {"zh": "Sumika 已审核", "en": "Sumika reviewed"}},
    "sumika-experimental": {"title": {"zh": "实验", "en": "Experimental"}},
    "requires-android": {"title": {"zh": "需安卓模拟器", "en": "Requires Android"}},
    "requires-bili-login": {"title": {"zh": "需 B站登录", "en": "Requires Bilibili login"}},
    "requires-python": {"title": {"zh": "需 Python/uv", "en": "Requires Python/uv"}},
    "requires-ffmpeg": {"title": {"zh": "需 ffmpeg", "en": "Requires ffmpeg"}},
    "requires-build-approval": {"title": {"zh": "需批准构建脚本", "en": "Needs build approval"}},
    "read-only": {"title": {"zh": "只读优先", "en": "Read-only first"}},
    "writes-off": {"title": {"zh": "写操作默认关", "en": "Writes off"}},
    "local-only": {"title": {"zh": "纯本地", "en": "Local only"}},
}


def _localized(value):
    if isinstance(value, str):
        return {"zh": value, "en": value}
    if isinstance(value, dict):
        return {key: value[key] for key in ("zh", "en") if isinstance(value.get(key), str)}
    return None


def _version_key(value):
    # Mixed numeric/pre-release segments must sort without comparing int to str.
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part)
                 for part in re.split(r"[.+-]", value))


def _fetch(source):
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(source, headers={"User-Agent": "Sumika-plugin-catalog/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _fallback_plugin(item):
    fallback = item["fallback"]
    repository = fallback.get("repository")
    source = fallback.get("source")
    if source is None:
        if "commit" not in fallback or repository is None:
            raise ValueError(f"fallback needs a source: {item['name']}")
        source = {"type": "git", "url": repository, "commit": fallback["commit"]}
    plugin = {
        "name": item["name"],
        "title": item["title"],
        "description": item["description"],
        "metadata": {"category": item["category"], "keywords": item.get("keywords", []),
                     "labels": item.get("labels", []), "sortKeys": {}},
        "versions": [{
            "version": fallback["version"],
            "publishTimestamp": fallback.get("publishTimestamp", 0),
            "source": source,
            "engines": fallback.get("engines", {}),
        }],
    }
    if repository:
        plugin["repository"] = {"url": repository}
    homepage = fallback.get("homepage", repository)
    if homepage:
        plugin["homepage"] = homepage
    return plugin


def build(source):
    catalog = _fetch(source)
    if catalog.get("format") != 1 or not isinstance(catalog.get("plugins"), list):
        raise ValueError("source is not a format-1 plugin index")
    indexed = {entry.get("name"): entry for entry in catalog["plugins"] if isinstance(entry, dict)}
    plugins = []
    seen = set()
    for item in SELECTION:
        if item["name"] in seen:
            raise ValueError(f"duplicate selection: {item['name']}")
        seen.add(item["name"])
        original = indexed.get(item["name"])
        if original is None:
            if "fallback" not in item:
                raise ValueError(f"missing from source and no fallback: {item['name']}")
            plugin = _fallback_plugin(item)
        else:
            plugin = copy.deepcopy(original)
            plugin["title"] = item["title"]
            plugin["description"] = item["description"]
            plugin["metadata"] = {
                **(plugin.get("metadata") or {}),
                "category": item["category"],
                "keywords": item.get("keywords", []),
                "labels": item.get("labels", []),
                "sortKeys": {},
            }
            versions = sorted(plugin.get("versions") or [], key=lambda entry: _version_key(entry["version"]),
                              reverse=True)
            wanted = item.get("version")
            if wanted is not None:
                versions = [entry for entry in versions if entry["version"] == wanted]
            if not versions:
                if "fallback" not in item:
                    raise ValueError(f"no versions: {item['name']}")
                plugin = _fallback_plugin(item)
            else:
                plugin["versions"] = versions
        plugin["metadata"] = {
            "category": item["category"],
            "keywords": item.get("keywords", []),
            "labels": item.get("labels", []),
            "sortKeys": {},
        }
        plugins.append(plugin)
    return {
        "format": 1,
        "title": {"zh": "Sumika 精选插件", "en": "Sumika Curated Plugins"},
        "description": {
            "zh": "面向 Sumika 的 DSH 插件精选：生活、B站、记忆与桌宠。安装、兼容性和卸载仍由 DSH 原生 Discover 管理。",
            "en": "Curated DSH plugins for Sumika: life, Bilibili, memory and presence. Install, compatibility and removal stay in DSH Discover.",
        },
        "metadata": {
            "categories": CATEGORIES,
            "labels": LABELS,
            "sortKeys": {},
        },
        "plugins": plugins,
    }


def validate(document):
    if document.get("format") != 1:
        raise ValueError("format must be 1")
    names = [plugin.get("name") for plugin in document.get("plugins", [])]
    if not names or len(names) != len(set(names)):
        raise ValueError("plugin names must be non-empty and unique")
    categories = document.get("metadata", {}).get("categories", {})
    labels = document.get("metadata", {}).get("labels", {})
    for plugin in document["plugins"]:
        if plugin.get("metadata", {}).get("category") not in categories:
            raise ValueError(f"unknown category: {plugin.get('name')}")
        for label in plugin.get("metadata", {}).get("labels", []):
            if label not in labels:
                raise ValueError(f"unknown label: {label}")
        if not plugin.get("versions"):
            raise ValueError(f"no versions: {plugin.get('name')}")
        if len(plugin["versions"]) != len({entry["version"] for entry in plugin["versions"]}):
            raise ValueError(f"duplicate versions: {plugin.get('name')}")
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    document = validate(build(args.source))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({len(document['plugins'])} plugins)")


if __name__ == "__main__":
    main()
