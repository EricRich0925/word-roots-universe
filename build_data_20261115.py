#!/usr/bin/env python3
"""网站 DATA 生成器（2026-11-15 网站同步施工）.

由侦察报告 recon-20261115.md 逆向的变换规则实现；DATA 生成脚本原先不存在，
本文件为新写生成器，留在目录里供复核与下次同步复用。

变换规则（重建法验证，见 --verify-old）：
  WORDS：按轨道顺序依次读入，同词首次出现者胜出（音标/释义/拆解取首次），
         掩码按位或；tier whole->0/base->1/root->2；frq null->999999；
         释义取 translation 首个 ';' 或 '；' 段并截断至 42 字符（2026-11-16 用户批准改规则：同时按全角分号切段）；按 frq 升序稳定排序。
  TRACKS：total=该路线词条数；dec=该路线 root+base 词条数。
  ROOTS：顺序原样取当前 DATA（规则未定，不得重排）；字段按词根键映射新内容；
         ex=[word, phonetic, gloss_cn, sentence_en, sentence_cn]；
         n=经 ALIAS 映射到该词根的 tier-2 词数；
         fam=按 WORDS 顺序前 10 个该词根 tier-2 词 [word, 释义截断 20 字符]。
  AFFIX：roots-content.affixes 逐字复制。
  序列化：json.dumps(ensure_ascii=False, separators=(',', ':'))，顶层键序
         roots/affix/tracks/words，DATA 独占单行。

用法：
  python3 build_data_20261115.py --verify-old
      用 data/ 旧快照重建旧 DATA，与当前 index.html 第 559 行载荷逐字节比对。
  python3 build_data_20261115.py --build-new --out /tmp/new_data_line.txt
      生成新 DATA，写出单行 `const DATA = {...};`（含末尾换行）。

文案来源（协调者定稿，一字不改）：
  gaokao/cet4/cet6 intro 见下 TRACK_COPY；其余 5 条 intro 与全部旧 label
  直接取自当前 DATA（逐字复制，不重打）。短语见 PHRASES（与
  ~/workspace/word-roots/gaokao/phrases-placement.md §3 表格逐字一致，
  由 verify_build_20261115.py 独立解析 md 表格比对）。
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORD_ROOTS = Path.home() / "workspace" / "word-roots"
INDEX = HERE / "index.html"

OLD_ORDER = ["beginner", "cet4", "cet6", "ky", "ielts", "abroad", "ecommerce"]
NEW_ORDER = ["beginner", "gaokao", "cet4", "cet6", "ky", "ielts", "abroad", "ecommerce"]

TIER_MAP = {"whole": 0, "base": 1, "root": 2}

# 协调者定稿文案（verbatim）。cet6 intro = 旧 intro 删“独有”与括号分句。
GAOKAO_LABEL = "高考备考"
GAOKAO_INTRO = (
    "按新课标附录词汇表编排，共 2993 个词（另有 6 条附录短语），"
    "其中 441 个可用词根词缀拆解，适合正在备考高考的高中生。"
)
CET4_INTRO = "四级路线仅含高考词表之外的新增词汇，与高考路线零重复；备考四级需先学高考路线。"
CET6_INTRO = "覆盖六级词汇 1940 个，适合已通过四级、正在冲刺六级的学生。"

# phrases-placement.md §3 表格 verbatim：[短语, 释义, 星级]
PHRASES = [
    ["according to", "按照；根据", "—"],
    ["bean curd", "豆腐", "★★"],
    ["due to", "由于；因为", "★"],
    ["mobile phone", "手机；移动电话", "—"],
    ["ought to", "应该；应当", "★"],
    ["physical education", "体育", "—"],
]

EXPECTED_TOTALS = {
    "beginner": 1134, "gaokao": 2993, "cet4": 1914, "cet6": 1940,
    "ky": 4786, "ielts": 4944, "abroad": 371, "ecommerce": 248,
}
EXPECTED_DEC = {
    "beginner": 964, "gaokao": 441, "cet4": 478, "cet6": 486,
    "ky": 927, "ielts": 874, "abroad": 23, "ecommerce": 20,
}

EXPECTED_MANUAL_ALIAS = {
    "ced": "ceed/cess", "cay": "cad/cas", "mov": "mob/mot", "tang": "tact",
    "brie": "brev", "fals": "fall", "grac": "grat", "simul": "simil",
    "sacr": "sanct", "prin": "prim", "corp": "corpor", "flect": "flex",
}


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_index_lines():
    with open(INDEX, encoding="utf-8") as f:
        return f.read().split("\n")


def current_data():
    """按内容锚点取当前 DATA 载荷并解析（不依赖绝对行号）。"""
    for line in read_index_lines():
        if line.startswith("const DATA = ") and line.endswith("};"):
            return json.loads(line[len("const DATA = "):-1]), line
    fail("anchor not found: DATA line")


def current_data_payload_str():
    for line in read_index_lines():
        if line.startswith("const DATA = ") and line.endswith("};"):
            return line[len("const DATA = "):-1]
    fail("anchor not found: DATA line")


def parse_manual_alias():
    """从 index.html 的 Object.assign(ALIAS,{...}) 行解析 12 个人工别名。"""
    for line in read_index_lines():
        if "Object.assign(ALIAS," in line:
            pairs = re.findall(r"([A-Za-z]+):'([^']+)'", line)
            alias = dict(pairs)
            if alias != EXPECTED_MANUAL_ALIAS:
                fail(f"manual ALIAS mismatch: parsed={alias}")
            if len(pairs) != 12:
                fail(f"manual ALIAS count {len(pairs)} != 12")
            return alias
    fail("anchor not found: ALIAS line")


def build_alias(root_keys, manual_alias):
    """与站内 JS 568-569 行同一构造：词根分形映射 + 人工别名覆盖。"""
    alias = {}
    for key in root_keys:
        for part in key.split("/"):
            alias[part.strip()] = key
    alias.update(manual_alias)
    return alias


def build_words(track_order, track_entries):
    """首次胜出去重 + 掩码或 + frq 稳定排序。返回 (words, first_win_map)。"""
    first = {}  # word -> [word, phonetic, gloss42, frq, tier, prefix, root, root_meaning, suffix, mask]
    order = []
    for idx, tid in enumerate(track_order):
        bit = 1 << idx
        for e in track_entries[tid]:
            w = e["word"]
            dec = e["decomposition"]
            if w not in first:
                gloss = re.split(r"[;；]", e["translation"], maxsplit=1)[0][:42]
                first[w] = [
                    w,
                    e["phonetic"],
                    gloss,
                    e["frq"] if e["frq"] is not None else 999999,
                    TIER_MAP[dec["tier"]],
                    dec["prefix"],
                    dec["root"],
                    dec["root_meaning_cn"],
                    dec["suffix"],
                    bit,
                ]
                order.append(w)
            else:
                first[w][9] |= bit
    words = [first[w] for w in order]
    words.sort(key=lambda r: r[3])  # 稳定排序：同 frq 保持首次出现顺序
    return words, first


def build_tracks(track_order, track_entries, label_intro):
    tracks = []
    for tid in track_order:
        entries = track_entries[tid]
        dec = sum(1 for e in entries if e["decomposition"]["tier"] in ("root", "base"))
        label, intro = label_intro[tid]
        t = {"id": tid, "label": label, "intro": intro,
             "total": len(entries), "dec": dec}
        if tid == "gaokao" and PHRASES is not None and label_intro.get("__phrases__"):
            t["phrases"] = [list(p) for p in PHRASES]
        tracks.append(t)
    return tracks


def build_roots(root_order, roots_content, words, alias):
    src = {r["root"]: r for r in roots_content["roots"]}
    if set(src) != set(root_order):
        fail(f"roots key set mismatch: src-only={sorted(set(src)-set(root_order))} "
             f"order-only={sorted(set(root_order)-set(src))}")
    counts = {k: 0 for k in root_order}
    fams = {k: [] for k in root_order}
    for w in words:
        if w[4] != 2:
            continue
        canon = alias.get(w[6])
        if canon is None:
            fail(f"tier-2 word {w[0]!r} root form {w[6]!r} not in ALIAS")
        counts[canon] += 1
        if len(fams[canon]) < 10:
            fams[canon].append([w[0], w[2][:20]])
    roots = []
    for key in root_order:
        s = src[key]
        roots.append({
            "r": key,
            "cn": s["meaning_cn"],
            "en": s["meaning_en"],
            "o": s["origin"],
            "h": s["hook"],
            "ex": [[e["word"], e["phonetic"], e["gloss_cn"],
                    e["sentence_en"], e["sentence_cn"]] for e in s["examples"]],
            "fam": fams[key],
            "n": counts[key],
        })
    return roots


def build_affix(roots_content):
    # 逐字复制，键序固定为 form/type/meaning_cn/note_cn。
    return [{"form": a["form"], "type": a["type"],
             "meaning_cn": a["meaning_cn"], "note_cn": a["note_cn"]}
            for a in roots_content["affixes"]]


def build_data(track_order, track_entries, roots_content, label_intro, root_order, alias):
    words, _ = build_words(track_order, track_entries)
    data = {
        "roots": build_roots(root_order, roots_content, words, alias),
        "affix": build_affix(roots_content),
        "tracks": build_tracks(track_order, track_entries, label_intro),
        "words": words,
    }
    return data


def dump_payload(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def verify_old():
    old_data, _ = current_data()
    root_order = [r["r"] for r in old_data["roots"]]
    manual = parse_manual_alias()
    alias = build_alias(root_order, manual)

    track_entries = {}
    for tid in OLD_ORDER:
        track_entries[tid] = load_json(HERE / "data" / "wordlists" / f"{tid}.json")
    rc = load_json(HERE / "data" / "roots-content.json")
    label_intro = {t["id"]: (t["label"], t["intro_cn"]) for t in rc["tracks"]}
    if list(label_intro) != OLD_ORDER:
        fail(f"old roots-content tracks order {list(label_intro)} != {OLD_ORDER}")

    rebuilt = build_data(OLD_ORDER, track_entries, rc, label_intro, root_order, alias)
    rebuilt_payload = dump_payload(rebuilt)
    current_payload = current_data_payload_str()
    print(f"rebuilt payload bytes: {len(rebuilt_payload.encode('utf-8'))}")
    print(f"current payload bytes: {len(current_payload.encode('utf-8'))}")
    if rebuilt_payload != current_payload:
        # 定位首个差异，便于诊断（不输出整行）。
        a, b = rebuilt_payload, current_payload
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        print(f"first diff at char {i}:")
        print(f"  rebuilt: ...{a[max(0,i-80):i+120]!r}")
        print(f"  current: ...{b[max(0,i-80):i+120]!r}")
        fail("rebuilt old DATA is NOT byte-identical to current DATA payload")
    print("VERIFY-OLD PASS: rebuilt old DATA is byte-identical to current DATA payload.")
    print(f"  tracks={len(rebuilt['tracks'])} roots={len(rebuilt['roots'])} "
          f"affix={len(rebuilt['affix'])} words={len(rebuilt['words'])}")
    return 0


def build_new(out_path):
    old_data, _ = current_data()
    root_order = [r["r"] for r in old_data["roots"]]
    manual = parse_manual_alias()
    alias = build_alias(root_order, manual)

    wl = load_json(WORD_ROOTS / "wordlists.json")
    track_order = list(wl["tracks"].keys())
    if track_order != NEW_ORDER:
        fail(f"wordlists.json track order {track_order} != {NEW_ORDER}")
    track_entries = wl["tracks"]
    rc = load_json(WORD_ROOTS / "roots-content.json")

    # 旧 label/intro 取自当前 DATA（逐字复制）；gaokao/cet4/cet6 用定稿文案。
    old_tracks = {t["id"]: t for t in old_data["tracks"]}
    label_intro = {}
    for tid in NEW_ORDER:
        if tid == "gaokao":
            label_intro[tid] = (GAOKAO_LABEL, GAOKAO_INTRO)
        elif tid == "cet4":
            label_intro[tid] = (old_tracks["cet4"]["label"], CET4_INTRO)
        elif tid == "cet6":
            label_intro[tid] = (old_tracks["cet6"]["label"], CET6_INTRO)
        else:
            label_intro[tid] = (old_tracks[tid]["label"], old_tracks[tid]["intro"])
    label_intro["__phrases__"] = True

    data = build_data(NEW_ORDER, track_entries, rc, label_intro, root_order, alias)

    # 生成器内断言（期望值来自施工简报；失败即停）。
    for t in data["tracks"]:
        if t["total"] != EXPECTED_TOTALS[t["id"]]:
            fail(f"total {t['id']}: {t['total']} != {EXPECTED_TOTALS[t['id']]}")
        if t["dec"] != EXPECTED_DEC[t["id"]]:
            fail(f"dec {t['id']}: {t['dec']} != {EXPECTED_DEC[t['id']]}")
    if sum(EXPECTED_TOTALS.values()) != 18330:
        fail("expected totals do not sum to 18330")
    if len(data["words"]) != 8627:
        fail(f"WORDS {len(data['words'])} != 8627")
    from collections import Counter
    tier = Counter(w[4] for w in data["words"])
    if (tier[0], tier[1], tier[2]) != (6840, 1047, 740):
        fail(f"tier dist whole/base/root = {tier[0]}/{tier[1]}/{tier[2]} != 6840/1047/740")
    if len(data["roots"]) != 137 or [r["r"] for r in data["roots"]] != root_order:
        fail("ROOTS count/order mismatch")
    gk = [t for t in data["tracks"] if t["id"] == "gaokao"][0]
    if gk.get("phrases") != PHRASES:
        fail("gaokao phrases mismatch")
    # reflection 首次胜出：须为 beginner 版 root/re+flex+ion（未决项，不得修）。
    by_word = {w[0]: w for w in data["words"]}
    refl = by_word["reflection"]
    if not (refl[4] == 2 and refl[5] == "re" and refl[6] == "flex" and refl[8] == "ion"):
        fail(f"reflection winner unexpected: {refl}")
    mov = by_word["movement"]
    if not (mov[4] == 1 and mov[6] == "move" and mov[8] == "ment"):
        fail(f"movement winner unexpected: {mov}")

    payload = dump_payload(data)
    line = f"const DATA = {payload};"
    if "\n" in line or "\r" in line:
        fail("DATA line is not single-line")
    out = Path(out_path)
    out.write_text(line + "\n", encoding="utf-8")
    print(f"BUILD-NEW OK: wrote {out} ({len(line.encode('utf-8'))} bytes, no LF)")
    print(f"  tracks={len(data['tracks'])} roots={len(data['roots'])} "
          f"affix={len(data['affix'])} words={len(data['words'])}")
    print(f"  gaokao phrases={len(gk['phrases'])}; reflection={refl[4:9]}; movement={mov[4:9]}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-old", action="store_true")
    ap.add_argument("--build-new", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.verify_old:
        return verify_old()
    if args.build_new:
        if not args.out:
            fail("--build-new requires --out")
        return build_new(args.out)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
