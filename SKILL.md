---
name: copy-drift-check
description: 查「副本漂移」：同一文件名散落在多处、内容却不一致（同名不同内容 / copy drift）。凡「改了本体，别的副本漏没漏改」「某检查或报告的结论可疑，怀疑跑的是旧副本」「盘点 / 清理多份副本的目录」「给同步链做本体↔副本 md5 体检」「发布或删除前先核对副本」都用它。Detect copy drift - the same filename existing in several places with different contents; use when you changed one copy of a script/doc/config and need to prove no other copy was missed, when a check or report gives a suspicious or outdated result and you suspect it was run from a stale copy, when auditing or cleaning a layout that keeps multiple copies (repo copy vs installed copy vs per-project instance), when verifying a sync pipeline is actually in sync (authoritative copy vs mirror, by md5), or before publishing/deleting files in a duplicated layout. Also covers the two failure modes it exists to catch - a stale copy that still runs and still prints a confident but wrong conclusion, and the root cause of such misses, which is inventorying copies by known paths instead of searching by value.
agent_created: true
---

# 副本漂移检查

## 用途

找出「**同名文件散落多处、内容却不一致**」的情况，并给出每份的路径 / 体积 / mtime / md5，供判断哪一份是权威。
**只读**：不写盘、不删文件、不联网、不执行被扫描的文件。

## 背景（先读，否则会低估它）

**副本漂移是静默失败。** 一份旧副本照样能运行、照样打印结论，只是结论是错的 ——
没有报错、没有异常、退出码正常。两种典型形态：

| 形态 | 后果 |
|---|---|
| 副本缺了一整段检查逻辑 | 它给出的"通过"是**假绿**（例：校验器少了一整条规则，于是把内容被截断的产出当成合格） |
| 副本里留着已作废的判定值 | 照着它执行，会按**已经被推翻的阈值**改稿 |

**根因不是"忘了改某个路径"，而是盘点方式错了**：人按**已知目录**去核对，
而漂移只有按**"值"全仓搜**才搜得出来。所以这个脚本做的是"按值分组"，不是"按路径比对"。

⚠ 还有一条容易踩的：**"最新那份"≠"权威那份"**。真实案例 —— 某次合并时，
"在用的那份"记的其实是旧版本，反倒是"看起来像归档的那份"才是定稿。
⇒ 本脚本只**列出** mtime 与 md5，**不替你决定**哪份权威；决定前先找证据（实测产物 / 交付记录 / 发布日志）。

## 用法

### 1）扫一组根目录（主要用法）

```bash
python scripts/check_copy_drift.py --root <目录A> --root <目录B> --ext .py,.md
```

输出：漂移组（同名不同内容，逐份列路径/mtime/体积/md5）＋ 重复组（同内容多份，提示"改一处要同步其余"）。

### 2）声明「这两份必须逐字节一致」

```bash
python scripts/check_copy_drift.py --pair <权威> <副本>
```

改完一处、同步另一处之后的**复核动作**。比人眼看体积可靠。

### 3）机器可读

```bash
python scripts/check_copy_drift.py --root <目录> --json
```

### 退出码

| 码 | 含义 |
|---|---|
| **0** | 没发现漂移 |
| **1** | 发现了漂移（`--pair` 模式下＝两份不一致）⇒ 可直接挂进 CI / 预检链 |
| **2** | 用法或参数错误 |

## 常用参数

| 参数 | 说明 |
|---|---|
| `--root` | 要扫的根目录，**可重复** |
| `--ext .py,.md` | 只扫这些扩展名（**大目录先收窄，否则很慢**） |
| `--name GLOB` | 只看文件名匹配者（可重复） |
| `--ignore P` | 路径命中即跳过（子串或 glob，**可重复**）。这是**最重要**的参数，见下节 |
| `--min-size` / `--max-size` | 体积窗口（默认 **200 B** ~ 8 MiB）。⚠ 比 200 B 还小的 `.json` / `.ini` / `.txt` 会被**静默漏掉**，查小配置先加 `--min-size 0` |
| `--skip-ext` | 额外跳过的扩展名 |
| `--quiet` | 只给结论，不打重复组清单 |

内置已跳过：`__pycache__` / `.git` / `node_modules` / `venv` / `dist` / `build` 等目录；
二进制与媒体扩展名；`*.bak` / `*.orig` / `*.tmp` / `*~` 等备份后缀。

## 🔴 先排除「设计上就该不同」的，否则全是假阳性

这一条决定了工具好不好用。典型必须排除的：

| 情形 | 处理 |
|---|---|
| **按项目实例化的副本**（同一脚本拷到每个子项目、里面被改写了路径常量） | `--ignore "instances/"`、`--ignore "tools/"` |
| **冻结归档 / 历史快照**（明确不再维护，允许与现役不同） | `--ignore "archive/"`、`--ignore "2025-"` |
| **模板 vs 生成物**（模板里的占位符本来就不等于成品） | 用 `--ext` / `--name` 收窄，或排除生成物目录 |

`--ignore` 比的是**完整路径**：先按子串、再按 glob 试，不区分大小写，`/` 与 `\` 等价。

### 🔴 写法必须「不带前导斜杠」

**写 `archive/`，不要写 `/archive/`。** 后者在 **Git Bash / MSYS2 / Cygwin** 下会被 shell
**路径转换**改写成 `C:/.../PortableGit/versions/x.y.z/archive/`（MSYS 把 `/开头` 的参数当绝对路径），
于是永远匹配不上，**静默失效 —— 不报错、不警告，只是没排除**。实测四种写法：

| 写法 | Git Bash / MSYS |
|---|---|
| `--ignore "/archive/"` | ❌ 被改写，失效 |
| `--ignore "archive/"` | ✅ **推荐**，无前导斜杠不触发改写 |
| `--ignore "*/archive/*"` | ✅ glob 也安全 |
| `MSYS_NO_PATHCONV=1` ＋ `/archive/` | ✅ 可用，但不如直接不加斜杠省事 |
| `--ignore 'archive\'` | 视 shell 而定，不推荐 |

路径含空格时，命令行要加引号。

**只有把"该不同的"排除干净，"不该不同的"才会跳出来。**

## 判读要点

1. 先看**漂移组数量**，再看每一组里"最新那份"是谁 —— 但别默认它权威（见上）。
2. **同一组里若有一份明显短很多**（比如 1/2 体积），大概率是它缺了后来加的整段逻辑 ⇒ 优先怀疑它。
3. 重复组不是问题，是**提示**：这些位置存在副本关系，改一处就得同步其余，**并在文档里登记**（否则下次没人知道有副本）。
4. 想在流程里用：把退出码 1 当"阻断"，并且**先把 ignore 列表固化进脚本调用处**，否则假阳性会让人很快放弃这条检查。

## 自检（改动脚本后请重跑）

本脚本已用「**造出能失败的条件**」验证过两条路径都会报红，不是"跑通就算数"：

- 造两份同名同内容 → 报 `无漂移`、退出码 0；
- 改掉其中一份 → 报 `1 组漂移`、退出码 1；
- `--pair` 同内容 → 0；不同内容 → 1（并打印体积差）；
- 不给 `--root` 也不给 `--pair` → 退出码 2；
- 中文 Windows 下 `PYTHONIOENCODING=gbk` 走管道 → 不崩（修之前报 `UnicodeEncodeError`）；
- Python 3.10 / 3.13 均跑过。

若你改了判定逻辑，**必须重造一遍"该红"的条件**再收工。

## 资源

- `scripts/check_copy_drift.py` — 主脚本（纯标准库，Python 3.8+，三平台通用）
- `README.md` — 面向新用户的使用说明（安装、上手、参数、常见坑）
