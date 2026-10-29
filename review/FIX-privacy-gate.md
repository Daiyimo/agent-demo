# FIX：隐私门禁（脱敏纪律的 CI 闸门）——Phase 6/7

> 立案：2026-10-29 公开仓库全历史脱敏整改（方案 B）。脱敏本身（Phase 0–4）已完成并 force push：
> `main` 从 348 个提交重写为同数量新 SHA，14 个真实标识（12 个账号/群号/内网地址 + 4 个测试夹具
> 里的真实 QQ）全部替换为占位号，旧分支与本地历史随后清理。
>
> 本记录只覆盖 **Phase 6/7**：把「下次别再提交进去」变成 CI 门禁 + 文档纪律。脱敏执行过程与
> 替换映射留在整改方案里（不进仓库：真实值本身就是隐私）。

## 1. 从 X 改为 Y（语义变化）

| # | 从 | 改为 | 理由 |
|---|---|---|---|
| 1 | `data/workspace/cron/jobs.json` 入库带**真实任务**（真实群号 + 宿主路径） | 只入库**模板**：`group:123456789` 占位号 + `<你的脚本>` 字面量，示例条目 `enabled:false` | 该文件在 `.gitignore` 里有 `!data/workspace/cron/` 例外、必须随仓库走；含真实号就必然泄漏，模板同样可用 |
| 2 | `.gitignore` 的 `data/privacy/` 整目录忽略 | `data/privacy/*` + `!data/privacy/id-hashes.txt` | 块名单必须随仓库走（CI 要读），但它只存 SHA-256；`real-ids.txt` 仍被忽略 |
| 3 | 隐私纪律只有文档约定 | 新增 `scripts/check_privacy.py` + CI `Privacy scan` 步骤（在 Lint 之前） | 「约定」在 348 个提交里被违反过 23 次；要有闸门，且要**早**失败（1~2 秒 vs 跑完 5 分钟测试） |

## 2. 门禁设计（为什么不存真实值）

- **规则 A（哈希块名单）**：扫描 `git ls-files` 全部入库内容，把「5~12 位连续数字」与「点分
  IPv4」当候选 token，逐个 SHA-256 与 `data/privacy/id-hashes.txt` 比对。命中即失败。
  仓库里**没有任何真实值**，门禁自己不是新的泄漏点；改动真实值清单只需本机
  `data/privacy/real-ids.txt`（gitignore）→ `--sync` 重生成哈希。
- **规则 B（形态检查，窄范围）**：只在 `data/workspace/**` 与 `config/**`（运行期配置）里
  拦 9~11 位连续数字，唯一例外是 `PLACEHOLDER_TOKENS`（模板占位号）。范围窄是刻意的——
  文档/测试里合法的长数字（时间戳、十进制 IP 的 SSRF 用例）不该被误伤。
- **命中值一律不回显**：只报「文件:行号 + 规则」。CI 日志对公开仓库是公开的，回显等于把
  要防的东西发到页面上。
- **失败语义**：退出码 1（CI 门禁）；块名单缺失 → stderr 告警但只在规则 B 上放行（不 fail-open
  到完全关闭，也不静默）。

## 3. 验证（本次实测，Windows 本机）

```
$ python scripts/check_privacy.py
[ok] 隐私门禁通过：358 个文件，16 条块名单            # 退出码 0

# AC1 规则 A：把某个值的哈希加进块名单 + 造一个含该值的入库文件
[fail] 隐私门禁：1 处问题（359 个文件）
  - docs/_tmp_privacy_probe.md:1: 命中哈希块名单（编号已隐去）……
exit=1                                                # 且输出里不含该值（断言 = False）

# AC2 规则 B：把模板占位号改成真实形态的 10 位数字
[fail] 隐私门禁：1 处问题（358 个文件）
  - data/workspace/cron/jobs.json:22: 运行期配置里出现 9~11 位数字……（值已隐去）
exit=1                                                # 还原后回到 exit=0

$ python -m pytest -q tests/test_privacy_gate.py
14 passed                                             # 14 条，Linux/Windows 通用

$ python -m ruff check … && python -m ruff format --check …
All checks passed! / 241 files already formatted
```

**变异复核（4/4 被抓，改坏→必红→反向还原）**：

| 变异 | 用例 |
|---|---|
| `_TOKEN_RE` 去掉点分 IPv4 分支 | `test_dotted_ipv4_is_covered` 红 |
| 占位号白名单跳行改成 `if False` | `test_placeholder_group_in_template_is_allowed` 红 |
| 规则 B 去掉 scope 判断（全仓库生效） | `test_scope_is_narrow` 红 |
| `main` 忽略 problems 一律 return 0 | `test_leaked_value_fails_via_main` 红 |

## 4. 同步的文档

- `.gitignore`：`data/privacy/` 例外口径 + `cron/` 入库只允许模板；
- `AGENTS.md` §4「配置」行（脱敏纪律 + 门禁说明）、§5 坑表（公开仓库泄漏只能重写全历史，
  以及 `--replace-text` 漏 commit message 的坑）、§7 交付前清单（新增门禁命令）；
- `BACKLOG.md` 计数块：92→93 文件 / 3586→3600 收集 / 3513→3527 通过（新增 14 条用例；
  按 `check_review_docs.py` 的口径做**算术更新**——本机 Windows 跑不出 Linux 的
  skipped/failed 分布，故不能 `--write-stats`，数字由「原块 + 新增条数」推出，
  CI 的 `--check-stats` 是最终裁决）；
- 本文件 + `review/REVIEW-WORKFLOW.md` §9.1 索引。

## 5. 未做 / 剩余项（明确交接）

1. **Phase 5（GitHub 侧）未做**：旧 SHA 仍可直接访问；若曾有 fork 或缓存，只能向 GitHub
   Support 提工事清除。本机网络无法完成，由用户执行。
2. **pre-commit 钩子未接线**：方案里可选；目前只有 CI 拦（本地靠 §7 清单自觉）。
   若要接，`.pre-commit-config.yaml` 加一条 `check_privacy.py` 即可（未验证过 Windows 下的钩子行为）。
3. **`real-ids.txt` 留在本机工作树**（被 gitignore）：`--sync` 需要它；删除后块名单无法再生，
   但已有 `id-hashes.txt` 仍能拦。是否保留由用户定。
4. 门禁只覆盖**入库内容**，不扫运行时产物（`data/archive`、日志）——那是另一条纪律
   （`.gitignore` + 备份策略），不在本闸门范围内。
5. **`data/privacy/id-hashes.txt` 必须真的入库**（`.gitignore` 已开 `!` 例外）：漏提交时
   CI 只打一条 stderr 告警、规则 A 形同关闭，剩下的规则 B 覆盖面窄得多。首次提交请用
   `git add data/privacy/id-hashes.txt` 显式确认（它是个「非忽略的新文件」，`git add -A`
   也会带上，但别指望「被忽略的目录里居然有个文件要提交」这件事被记住）。
