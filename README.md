# copy-drift-check

> 找出「**同名文件散落多处、内容却不一致**」的副本漂移（copy drift），逐份列出路径 / 体积 / mtime / md5，供你判断哪一份是权威。

Python 3.8+ ｜ 纯标准库、零依赖 ｜ Windows / macOS / Linux ｜ **只读**（不写盘、不删文件、不联网、不执行被扫描的文件）

---

## 它解决什么问题

一个脚本 / 文档 / 配置常被拷到多个位置：本体、部署目录、每个子项目的实例副本。
改了本体、忘了副本，是**静默失败** —— 副本照旧能跑、照旧打印结论，**只是结论是错的**：
没有报错、没有异常、退出码正常。两种典型形态：

| 形态 | 后果 |
|---|---|
| 副本缺了一整段检查逻辑 | 它给出的"通过"是**假绿**：校验器少了一整条规则，于是把内容被截断的产出当成合格 |
| 副本里留着已作废的判定值 | 照着它执行，会按**已经被推翻的阈值**改稿 |

**根因不是"忘了改某个路径"，而是盘点方式错了**：人按**已知目录**去核对，而漂移只有按**"值"全仓搜**才搜得出来。
所以这个脚本做的是「**按 basename 分组、比内容**」，不是「按已知路径逐对比对」——你不会漏掉自己没想到的那个副本。

---

## 30 秒上手

```bash
git clone <本仓库地址> copy-drift-check
cd copy-drift-check

# 1) 扫一组根目录（最常用）
python scripts/check_copy_drift.py --root /path/to/项目A --root /path/to/部署目录 --ext .py,.md

# 2) 声明「这两份必须逐字节一致」——改完一处、同步另一处之后的复核动作
python scripts/check_copy_drift.py --pair /path/to/本体.py /path/to/副本.py

# 3) 机器可读（喂给 CI / 其他脚本）
python scripts/check_copy_drift.py --root /path/to/项目 --json
```

Windows 下把 `python` 换成 `py -3` 或解释器全路径即可，命令其余部分不变。

### 示例输出（路径已简化）

```
==========================================================================
副本漂移检查 ｜ 根目录 2 个 ｜ 扫描文件 4 个
   · /srv/app/src
   · /srv/deploy
==========================================================================

🔴 同名但内容不一致（漂移）：1 组

[1] config.py —— 3 份 / 2 种内容
    A  2026-08-14 09:31       1842 B  3f9a1c2d  /srv/app/src/config.py
    B  2026-08-11 17:02       1507 B  7b2e40aa  /srv/deploy/config.py
    ⇒ 最新那份：2026-08-14 09:31（/srv/app/src/config.py）
      先确认「最新 ≠ 权威」，再决定同步方向。

🟡 完全重复（同内容多份；改一处就得同步其余）：1 组
  · util.py  ×2  md5=a1b2c3d4
        /srv/app/src/util.py
        /srv/deploy/util.py

==========================================================================
漂移 1 组 ｜ 重复 0 组 ｜ 扫描 4 个文件
⇒ 退出码 1：先确认哪一份是权威，再逐份改齐（改完按 md5 复核）。
```

---

## 退出码

| 码 | 含义 |
|---|---|
| **0** | 没发现漂移 |
| **1** | 发现了漂移（`--pair` 模式下＝两份不一致）⇒ 可直接挂进 CI / 预检链当"阻断" |
| **2** | 用法或参数错误 |

---

## 参数

| 参数 | 说明 |
|---|---|
| `--root DIR` | 要扫的根目录，**可重复** |
| `--pair A B` | 只比这两个文件是否逐字节一致（与 `--root` 二选一） |
| `--ext .py,.md` | 只扫这些扩展名。**大目录先收窄，否则很慢** |
| `--name GLOB` | 只看文件名匹配者，可重复 |
| `--ignore P` | 路径命中即跳过（子串或 glob，**可重复**）。**最重要的参数，见下节** |
| `--min-size` / `--max-size` | 体积窗口（默认 **200 B** ~ 8 MiB） |
| `--skip-ext` | 额外跳过的扩展名（叠加在内置二进制表上） |
| `--json` | 输出 JSON |
| `--quiet` | 只给结论，不打重复组清单 |

**内置已跳过**：`__pycache__` / `.git` / `node_modules` / `.venv` / `dist` / `build` 等目录；
二进制与媒体扩展名；`*.bak` / `*.orig` / `*.tmp` / `*~` 等备份后缀。

---

## ⚠️ 最重要的一步：先把「设计上就该不同」的排除掉

这一步决定了工具好不好用。不排除，结果全是假阳性，人很快就会放弃这条检查。

| 情形 | 处理 |
|---|---|
| **按项目实例化的副本**（同一脚本拷到每个子项目、里面改写了路径常量） | `--ignore "instances/"`、`--ignore "tools/"` |
| **冻结归档 / 历史快照**（明确不再维护，允许与现役不同） | `--ignore "archive/"`、`--ignore "2025-"` |
| **模板 vs 生成物**（模板里的占位符本来就不等于成品） | 用 `--ext` / `--name` 收窄，或排除生成物目录 |

`--ignore` 比的是**完整路径**：先按子串、再按 glob 试，不区分大小写，`/` 与 `\` 等价。

### 🔴 写法必须「不带前导斜杠」

**写 `archive/`，不要写 `/archive/`。** 后者在 **Git Bash / MSYS2 / Cygwin** 下会被 shell 的
**路径转换**悄悄改写成 `C:/.../PortableGit/versions/x.y.z/archive/`（MSYS 把 `/` 开头的参数当绝对路径），
于是永远匹配不上 —— **静默失效：不报错、不警告，只是没排除**。

| 写法 | Git Bash / MSYS |
|---|---|
| `--ignore "/archive/"` | ❌ 被改写，失效 |
| `--ignore "archive/"` | ✅ **推荐** |
| `--ignore "*/archive/*"` | ✅ 安全（glob 不触发改写） |
| `MSYS_NO_PATHCONV=1` ＋ `/archive/` | ✅ 可用 |

cmd / PowerShell 下不受影响，但统一写**不带前导斜杠**最省心。

### ⚠️ 别拿它扫一整个混合目录

`--root` 指向一个装着多种无关文件的大目录时，会出现大量**假阳性** ——
比如把一堆不相干的 `SKILL.md`、`README.md` 判成"漂移组"（它们本来就该各不相同）。

这个工具的正确姿势是**收窄到"同一个工具的若干份副本"**：

```bash
# 好：只看这一组副本
--root ./src --root ./deploy --name "sync.py"

# 好：先用扩展名收窄，再排除不该比的
--root ./repo --ext .py --ignore "fixtures/"

# 差：裸扫大目录，噪声淹没有用信号
--root ~/.workbuddy/skills
```

> **只有把"该不同的"排除干净，"不该不同的"才会跳出来。**

---

## 常见坑

**1）比 200 B 还小的文件会被静默漏掉。**
默认 `--min-size 200` 是为了滤掉碎片。但 `.json` / `.ini` / `.env` / 小 `.txt` 常常不足 200 B ——
查这类配置请显式加 `--min-size 0`。这是最容易"跑了但等于没查"的一个坑。

**2）中文 Windows 下输出重定向到文件时，控制台编码是 GBK。**
脚本已做保护（编不出的符号替换成 `?`，不再崩溃）。想让 emoji 正常显示：

```bash
chcp 65001                     # cmd 里切到 UTF-8
export PYTHONIOENCODING=utf-8  # 或 Git Bash / Linux / macOS
```

**3）"最新那份" ≠ "权威那份"。**
真实案例：某次合并时，"在用的那份"记的其实是旧版本，反倒是"看起来像归档的那份"才是定稿。
脚本**只列出** mtime 与 md5，**不替你决定**哪份权威 —— 决定前先找证据（实测产物 / 交付记录 / 发布日志）。

**4）"重复组"不是问题，是提示。**
同内容多份说明这些位置存在副本关系：改一处就得同步其余，**并且要在文档里登记**，否则下次没人知道有副本。

**5）同一组里若有一份明显短很多（比如 1/2 体积），优先怀疑它** —— 大概率缺了后来加的整段逻辑。

---

## 装成 AI agent 的 skill（可选）

本目录本身就是一个 skill，直接整个文件夹丢进 skill 目录即可：

```
<skill 目录>/copy-drift-check/
├── SKILL.md              # 给 agent 看的：何时用、怎么判读
├── README.md             # 本文档，给人看的
└── scripts/check_copy_drift.py
```

- WorkBuddy / Claude Code 用户级：放进 `~/.workbuddy/skills/`
- 项目级（随仓库共享给团队）：放进 `<项目>/.workbuddy/skills/`

**注意**：目录名要与 `SKILL.md` 里 `name:` 字段一致（都是 `copy-drift-check`）。
装好后对 agent 说「查一下副本漂移」「改了本体，别的副本漏没漏改」「发布前先核对副本」即可触发。

## 挂进 CI / 预检链

```bash
python scripts/check_copy_drift.py \
    --root ./src --root ./deploy \
    --ext .py,.md,.json \
    --ignore "archive/" --ignore "fixtures/" \
    --quiet
# 退出码 1 视为阻断
```

**请把 ignore 列表固化进调用处**（脚本、Makefile、CI 配置），别每次靠脑子想 —— 否则假阳性会让人很快放弃这条检查。

---

## 它不做什么（边界）

- **不替你决定哪份权威**，只列证据。
- **只按文件名分组**：不同名但内容相同的文件不会被配对。
- **不区分大小写**地合并同名文件：Linux 上 `Makefile` 与 `makefile` 会被并进同一组（Windows / macOS 上它们本就是同一个文件）。
- 不写盘、不删文件、不联网、不执行被扫描的文件。

---

## 自检（改动脚本后请重跑）

本脚本用「**造出能失败的条件**」验证过，不是"跑通就算数"：

```bash
cd scripts
mkdir -p /tmp/t/a /tmp/t/b
printf 'x%.0s' {1..300} > /tmp/t/a/tool.py
cp /tmp/t/a/tool.py /tmp/t/b/tool.py
python check_copy_drift.py --root /tmp/t/a --root /tmp/t/b --ext .py   # 期望：无漂移，退出码 0
printf '\n# changed\n' >> /tmp/t/b/tool.py
python check_copy_drift.py --root /tmp/t/a --root /tmp/t/b --ext .py   # 期望：1 组漂移，退出码 1
python check_copy_drift.py --pair /tmp/t/a/tool.py /tmp/t/b/tool.py    # 期望：不一致，退出码 1
python check_copy_drift.py --pair /tmp/t/a/tool.py /tmp/t/a/tool.py    # 期望：一致，退出码 0
```

**改动判定逻辑后，必须重造一遍"该红"的条件再收工。**

---

## License

MIT © 2026 [hwgz-233](https://github.com/hwgz-233)
