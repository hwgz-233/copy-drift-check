#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_copy_drift.py — 找出「同名文件散落多处、内容却不一致」的副本漂移。

为什么需要它
------------
一个工具/文档/配置常常被拷到多个位置（本体 + 副本 + 各项目实例）。
改了本体、忘了副本，是**静默失败**：副本照样能跑、结论照样打印，
但里面的判定值可能已经作废。这类问题的根因不是"忘了改某个路径"，
而是**盘点方式错了 —— 按已知目录去核对，而不是按"值"全仓搜**。

用法
----
    # 1) 扫一组根目录，找同名不同内容（漂移）
    python check_copy_drift.py --root <目录A> --root <目录B> --ext .py,.md

    # 2) 显式声明"这两份必须逐字节一致"，只比 md5
    python check_copy_drift.py --pair <文件A> <文件B>

    # 3) 机器可读
    python check_copy_drift.py --root <目录> --json

退出码
------
    0 = 没发现漂移
    1 = 发现了漂移（--pair 模式下 = 两份不一致）
    2 = 用法/参数错误

兼容性
------
纯标准库，Python 3.8+，Windows / macOS / Linux 通用。

只读脚本：不写任何文件、不删任何东西、不联网、不执行被扫描的文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict

# ── 默认排除：目录名（任一层匹配即整棵跳过） ──────────────────
DEFAULT_IGNORE_DIRS = {
    "__pycache__", ".git", ".svn", ".hg", "node_modules", ".venv", "venv",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".cache", ".gradle", "target", "$RECYCLE.BIN",
}

# ── 默认排除：扩展名（二进制/媒体/归档，比对它们只有噪声） ────
DEFAULT_SKIP_EXTS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp3", ".wav", ".m4a", ".flac", ".mp4", ".mov", ".avi", ".mkv",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".docx", ".xlsx", ".pptx", ".sqlite", ".db",
    ".whl", ".egg", ".jar", ".class", ".o", ".a", ".lib", ".obj",
}

# ── 默认排除：文件名后缀（备份/快照类，本来就该不同） ──────────
DEFAULT_SKIP_SUFFIX = (".bak", ".orig", ".tmp", ".swp", "~")


def _new_md5():
    """FIPS 模式下 hashlib.md5() 会直接抛 ValueError，退回「允许非安全用途」的写法。"""
    try:
        return hashlib.md5(usedforsecurity=False)   # Python 3.9+
    except TypeError:
        return hashlib.md5()


def md5_of(path, chunk=1 << 20):
    h = _new_md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def norm_path(path):
    """统一分隔符：root 写 / 时 os.walk 会给出 / 与 \\ 混杂的路径，输出与 JSON 都很难看。"""
    return os.path.normpath(path)


def fix_stdio_encoding():
    """中文 Windows 下输出走管道时默认编码是 GBK，打印 🔴/✅ 会 UnicodeEncodeError 崩掉。
    这里只把错误处理改成「编不出就替换」，不换编码 —— 中文照旧可读，个别符号变 ?。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def matches_any(path, patterns):
    """patterns: 子串或 fnmatch 风格 glob，匹配**完整路径**（不区分大小写）。"""
    import fnmatch
    low = path.replace("/", "\\").lower()
    for p in patterns:
        q = p.replace("/", "\\").lower()
        if q in low or fnmatch.fnmatch(low, q):
            return True
    return False


def collect(roots, exts, skip_exts, ignore, names,
            min_size, max_size, follow_links=False):
    hits = []
    for root in roots:
        if not os.path.isdir(root):
            print("⚠ 跳过不存在的根目录：%s" % root, file=sys.stderr)
            continue
        for cur, dirs, files in os.walk(root, followlinks=follow_links):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS
                       and not matches_any(os.path.join(cur, d), ignore)]
            for fn in files:
                path = os.path.join(cur, fn)
                low = fn.lower()
                if matches_any(path, ignore):
                    continue
                if any(low.endswith(s) for s in skip_exts):
                    continue
                if any(low.endswith(s) for s in DEFAULT_SKIP_SUFFIX):
                    continue
                if exts and os.path.splitext(low)[1] not in exts:
                    continue
                if names and not matches_any(low, [n.lower() for n in names]):
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if st.st_size < min_size or st.st_size > max_size:
                    continue
                hits.append((norm_path(path), st.st_size, st.st_mtime, low))
    return hits


def group_by_basename(hits):
    groups = defaultdict(list)
    for path, size, mtime, low in hits:
        groups[low].append((path, size, mtime))
    return groups


def analyse(groups):
    """返回 (drift, dup)：drift = 同名但内容有 ≥2 种；dup = 同名且内容全同且 ≥2 份。"""
    drift, dup = [], []
    for base, items in sorted(groups.items()):
        if len(items) < 2:
            continue
        records = []
        for path, size, mtime in items:
            try:
                digest = md5_of(path)
            except OSError as exc:
                print("⚠ 读不到，已跳过：%s（%s）" % (path, exc), file=sys.stderr)
                continue
            records.append({"path": path, "size": size, "mtime": mtime,
                            "md5": digest})
        if len(records) < 2:
            continue
        kinds = {}
        for r in records:
            kinds.setdefault(r["md5"], []).append(r)
        if len(kinds) == 1:
            dup.append({"basename": base, "count": len(records),
                        "md5": records[0]["md5"], "files": records})
        else:
            drift.append({"basename": base, "kinds": len(kinds),
                          "files": records})
    return drift, dup


def fmt_time(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def print_human(drift, dup, scanned, roots, quiet=False):
    print("=" * 74)
    print("副本漂移检查 ｜ 根目录 %d 个 ｜ 扫描文件 %d 个" % (len(roots), scanned))
    for r in roots:
        print("   · %s" % norm_path(r))
    print("=" * 74)

    if drift:
        print("\n🔴 同名但内容不一致（漂移）：%d 组" % len(drift))
        for i, g in enumerate(drift, 1):
            print("\n[%d] %s —— %d 份 / %d 种内容" % (i, g["basename"],
                                                   len(g["files"]), g["kinds"]))
            by_md5 = defaultdict(list)
            for r in g["files"]:
                by_md5[r["md5"]].append(r)
            for label, md5 in zip("ABCDEFGHIJ", sorted(by_md5,
                                                      key=lambda m: -max(r["mtime"] for r in by_md5[m]))):
                rows = by_md5[md5]
                rows.sort(key=lambda r: -r["mtime"])
                for r in rows:
                    print("    %s  %s  %9d B  %s  %s" % (
                        label, fmt_time(r["mtime"]), r["size"], r["md5"][:8],
                        r["path"]))
            newest = max(g["files"], key=lambda r: r["mtime"])
            print("    ⇒ 最新那份：%s（%s）" % (fmt_time(newest["mtime"]),
                                             newest["path"]))
            print("      先确认「最新 ≠ 权威」，再决定同步方向。")
    else:
        print("\n✅ 没有同名不同内容的文件。")

    if dup and not quiet:
        print("\n🟡 完全重复（同内容多份；改一处就得同步其余）：%d 组" % len(dup))
        for g in dup:
            print("  · %s  ×%d  md5=%s" % (g["basename"], g["count"],
                                          g["md5"][:8]))
            for r in sorted(g["files"], key=lambda r: r["path"]):
                print("        %s" % r["path"])

    print("\n" + "=" * 74)
    print("漂移 %d 组 ｜ 重复 %d 组 ｜ 扫描 %d 个文件" %
          (len(drift), len(dup), scanned))
    if drift:
        print("⇒ 退出码 1：先确认哪一份是权威，再逐份改齐（改完按 md5 复核）。")
    else:
        print("⇒ 退出码 0：无漂移。")


def do_pair(a, b, quiet=False):
    for p in (a, b):
        if not os.path.isfile(p):
            print("🛑 文件不存在：%s" % p, file=sys.stderr)
            return 2
    ma, mb = md5_of(a), md5_of(b)
    sa, sb = os.path.getsize(a), os.path.getsize(b)
    same = (ma == mb)
    if not quiet:
        print("A  %9d B  %s  %s" % (sa, ma[:8], norm_path(a)))
        print("B  %9d B  %s  %s" % (sb, mb[:8], norm_path(b)))
    if same:
        print("✅ 一致（md5 %s）" % ma)
        return 0
    print("🔴 不一致：md5 %s vs %s，体积 %+d B" % (ma[:8], mb[:8], sb - sa))
    return 1


def main(argv=None):
    fix_stdio_encoding()
    ap = argparse.ArgumentParser(
        description="副本漂移检查：同名文件散落多处、内容却不一致。只读，不写盘。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", action="append", default=[],
                    help="要扫描的根目录（可重复）")
    ap.add_argument("--pair", nargs=2, metavar=("A", "B"),
                    help="只比这两个文件是否逐字节一致")
    ap.add_argument("--ext", default="",
                    help="只扫这些扩展名，逗号分隔，如 .py,.md,.json（默认全部）")
    ap.add_argument("--skip-ext", default="",
                    help="额外跳过的扩展名，逗号分隔（叠加在内置二进制表上）")
    ap.add_argument("--name", action="append", default=[],
                    help="只看文件名匹配者（子串或 glob，可重复）")
    ap.add_argument("--ignore", action="append", default=[],
                    help="路径命中即跳过（子串或 glob，可重复）。"
                         "例：--ignore \"/_tools/\" --ignore \"*/archive/*\"")
    ap.add_argument("--min-size", type=int, default=200,
                    help="小于该字节数的文件不参与（默认 200，滤碎片）")
    ap.add_argument("--max-size", type=int, default=8 << 20,
                    help="大于该字节数的文件不参与（默认 8 MiB）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="只给结论（不打重复组清单）")
    args = ap.parse_args(argv)

    if args.pair:
        return do_pair(args.pair[0], args.pair[1], args.quiet)

    if not args.root:
        ap.error("要么给 --root（可重复），要么给 --pair A B")

    exts = {e.strip().lower() if e.strip().startswith(".")
            else "." + e.strip().lower()
            for e in args.ext.split(",") if e.strip()}
    skip_exts = set(DEFAULT_SKIP_EXTS)
    skip_exts |= {e.strip().lower() if e.strip().startswith(".")
                  else "." + e.strip().lower()
                  for e in args.skip_ext.split(",") if e.strip()}

    hits = collect(args.root, exts, skip_exts, args.ignore,
                   args.name, args.min_size, args.max_size)
    groups = group_by_basename(hits)
    drift, dup = analyse(groups)

    if args.json:
        print(json.dumps({
            "roots": [norm_path(r) for r in args.root],
            "scanned": len(hits),
            "drift": drift,
            "duplicates": [{"basename": g["basename"], "count": g["count"],
                            "md5": g["md5"],
                            "files": [r["path"] for r in g["files"]]}
                           for g in dup],
        }, ensure_ascii=False, indent=2))
    else:
        print_human(drift, dup, len(hits), args.root, args.quiet)

    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
