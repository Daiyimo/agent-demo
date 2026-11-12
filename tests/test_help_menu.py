"""帮助菜单的单一事实源 + 全命令面覆盖。

历史教训（2026-10-26）：文本菜单（admin._HELP_TEXT）与图片菜单
（help_render._SECTIONS）各写一份，图片菜单漏过 /词云、/发言榜、/memory、
/2fa 等一整批命令——用户问「词云怎么调用」而帮助里根本没有。现在两边都从
`help_menu.SECTIONS` 生成，并且这里用 AST 扫全部 `on_command` 注册面：
**新命令不进帮助菜单，这条用例就红**。
"""

import ast
import importlib
from pathlib import Path

import pytest

pytest.importorskip("nonebot")

_ADAPTER_DIR = Path(__file__).resolve().parent.parent / "plugins" / "qq_agent_adapter"


@pytest.fixture(scope="module")
def nb_driver():
    import nonebot

    nonebot.init(_env_file=None, superusers={"10000"})
    from nonebot import get_driver

    return get_driver()


def _registered_commands() -> dict[str, set[str]]:
    """AST 扫适配层全部 on_command：{主名: {主名, *aliases}}。"""
    out: dict[str, set[str]] = {}
    for path in sorted(_ADAPTER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "on_command"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                continue
            primary = str(node.args[0].value)
            names = {primary}
            for kw in node.keywords:
                if kw.arg == "aliases" and isinstance(kw.value, ast.Set):
                    for elt in kw.value.elts:
                        if isinstance(elt, ast.Constant):
                            names.add(str(elt.value))
            out[primary] = names
    return out


class TestHelpMenuSingleSource:
    @pytest.mark.usefixtures("nb_driver")
    def test_text_and_image_share_one_source(self):
        admin = importlib.import_module("plugins.qq_agent_adapter.admin")
        help_render = importlib.import_module("plugins.qq_agent_adapter.help_render")
        help_menu = importlib.import_module("plugins.qq_agent_adapter.help_menu")
        assert help_render._SECTIONS is help_menu.SECTIONS
        assert help_render._FOOTER is help_menu.FOOTER
        assert admin._HELP_TEXT == help_menu.render_text()

    def test_text_covers_every_menu_row(self):
        from plugins.qq_agent_adapter import help_menu

        text = help_menu.render_text()
        for head, rows in help_menu.SECTIONS:
            assert head in text
            for cmd, desc in rows:
                assert cmd in text, f"{cmd} 不在文本帮助里"
                assert desc in text, f"{desc} 不在文本帮助里"

    def test_group_stats_commands_listed(self):
        """用户入口：群统计三个入口必须在帮助里（否则只能靠口口相传）。"""
        from plugins.qq_agent_adapter import help_menu

        text = help_menu.render_text()
        # 命令面统一带 / 前缀（2026-10-26 撤掉免前缀入口后）
        for cmd in ("/词云", "/发言榜", "/help"):
            assert cmd in text, f"{cmd} 没进帮助菜单"
        assert "点评我一下" in text

    def test_help_states_prefix_requirement(self):
        """NoneBot 命令必须带 / 前缀（前缀 Trie），帮助不能宣称"带不带都行"。"""
        from plugins.qq_agent_adapter import help_menu

        text = help_menu.render_text()
        assert "带不带 / 都能触发" not in text
        assert "所有命令都带 / 前缀" in text


def _covered(primary: str, names: set[str], squashed: str, families) -> bool:
    """菜单是否覆盖了某条已注册命令（与 test_no_command_missing_from_help 同口径）。

    提到模块级是为了复用；紧凑族可能不止一个，判定遍历完全部族。

    L4（REVIEW-4d5c1b8..63f9444）：原实现在族循环内 ``return <布尔表达式>``，
    看着像「首个命中的族判 False 就短路」。**已穷举证伪**（3840 组前缀/子命令/
    文本组合，两种写法结论零分歧）：``squashed`` 判定是 substring 包含，而同一
    primary 的多个前缀必然互相嵌套，故「前面的族不命中」时后面的族也不可能
    命中。保留遍历形式只为可读性，**不要**据此加判别用例——造不出分歧输入。
    """
    from plugins.qq_agent_adapter import help_menu

    if any(name.replace(" ", "") in squashed for name in names):
        return True
    for prefix, subs in (families or help_menu.COMPACT_FAMILIES).items():
        if primary.startswith(prefix) and primary[len(prefix) :] in subs:
            sub = primary[len(prefix) :]
            if prefix in squashed and sub in squashed:
                return True
    return False


class TestEveryCommandInHelp:
    @pytest.mark.usefixtures("nb_driver")
    def test_no_command_missing_from_help(self):
        from plugins.qq_agent_adapter import help_menu

        text = help_menu.render_text()
        # 菜单允许紧凑写法（如「skill catalog / info / install …」而不是逐个
        # 「skill catalog / skill info / …」），故按去空白匹配；紧凑族按
        # 「前缀 + 子命令词都出现」判定（help_menu.COMPACT_FAMILIES）。
        squashed = text.replace(" ", "")
        missing = sorted(
            primary
            for primary, names in _registered_commands().items()
            if not _covered(primary, names, squashed, help_menu.COMPACT_FAMILIES)
        )
        assert not missing, f"这些已注册命令没进帮助菜单：{missing}"

    def test_help_registered_as_help(self):
        """主命令必须是 help（2026-10-26 用户要求）；aihelp 只能退为别名。

        否则会出现"菜单写 /help、实际注册的是 aihelp"的漂移——纯文本包含性
        断言抓不到（别名「帮助」仍在菜单里），必须按 AST 主名判定。
        """
        cmds = _registered_commands()
        assert "help" in cmds, "帮助命令必须注册为 help"
        assert "aihelp" not in cmds, "aihelp 只能是别名，不能是主命令"
        assert {"aihelp", "帮助"} <= cmds["help"]

    def test_command_surface_not_empty(self):
        """防 AST 扫空（ glob 路径错/签名变）导致上面的用例恒真。"""
        cmds = _registered_commands()
        assert len(cmds) >= 15, f"只扫到 {len(cmds)} 个命令，AST 扫描大概率失效"
        assert {"词云", "发言榜", "memory", "2fa", "reboot"} <= set(cmds)


class TestAdminSection:
    """帮助菜单按权限分区：superuser-only 命令不得混进普通节。

    历史（2026-11-05）：/2fa、/cron、/openclaw 按「web 登录 / 定时任务」的
    使用场景放在「常用」，但 handler 内都是 is_superuser 判定——普通用户
    照着菜单打只会被拒，菜单等于误导。
    """

    def test_admin_section_matches_admin_only(self):
        from plugins.qq_agent_adapter import help_menu

        sections = {head: {cmd for cmd, _ in rows} for head, rows in help_menu.SECTIONS}
        admin = sections[help_menu.ADMIN_SECTION]
        assert admin == set(help_menu.ADMIN_ONLY), (
            "管理节命令与 ADMIN_ONLY 不一致："
            f"缺 {sorted(set(help_menu.ADMIN_ONLY) - admin)}，"
            f"多 {sorted(admin - set(help_menu.ADMIN_ONLY))}"
        )

    def test_admin_only_commands_not_in_other_sections(self):
        from plugins.qq_agent_adapter import help_menu

        for head, rows in help_menu.SECTIONS:
            if head == help_menu.ADMIN_SECTION:
                continue
            leaked = [cmd for cmd, _ in rows if cmd in help_menu.ADMIN_ONLY]
            assert not leaked, f"这些 superuser-only 命令混进了「{head}」节：{leaked}"


def _superuser_gated_commands() -> set[str]:
    """AST：handler 内出现 is_superuser( 拒绝判定的整命令集合。

    M5（REVIEW-e079b8d..3a3ce4a）：单向锁只守「ADMIN_ONLY 不泄漏到普通
    节」——/reset 这类「handler 已收窄 superuser、菜单却列在常用节」的命令
    从反向漏掉。这里建「on_command 注册变量 → handler」映射反向扫。
    """
    out: set[str] = set()
    for path in sorted(_ADAPTER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        var_to_cmd: dict[str, str] = {}
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", "") == "on_command"
                and node.value.args
                and isinstance(node.value.args[0], ast.Constant)
            ):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name):
                    var_to_cmd[t.id] = str(node.value.args[0].value)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "handle"
                    and isinstance(dec.func.value, ast.Name)
                ):
                    continue
                var = dec.func.value.id
                if var not in var_to_cmd:
                    continue
                gated = any(
                    isinstance(n, ast.Call)
                    and (
                        getattr(n.func, "id", "") in ("is_superuser", "is_superuser_id")
                        or (
                            isinstance(n.func, ast.Attribute)
                            and n.func.attr in ("is_superuser", "is_superuser_id")
                        )
                    )
                    for n in ast.walk(node)
                )
                if gated:
                    out.add(var_to_cmd[var])
    return out


class TestSuperuserGatedReverseLock:
    """反向锁：handler 收窄 superuser 的命令必须出现在管理节。

    M5：59a31cb 只加了单向锁（ADMIN_ONLY 不得泄漏），/reset 的 handler
    早已是 superuser-only 却仍在「常用」节；「定时提醒」自然语言入口在
    reminder_* 收窄 superuser 后同样误导。两处均已修，此锁防复发。

    静态 AST 分不清「整命令拒绝」与「子命令级分权」（kb 的删除、skill 的
    install、usage 的明细都是 handler 内 is_superuser，但整命令对普通用户
    可用）——故用两张显式清单：整命令级必须在管理节；子命令级允许在普通节。
    **新出现的 gated 命令不登记即红**（逼人归类，而不是静默漏掉）。
    """

    WHOLE_COMMAND_ONLY = {
        "/2fa",
        "/cron",
        "/openclaw",
        "/push",
        "/nudge",
        "/growth",
        "/model",
        "/reboot",
        "/reset",
        "/update",
    }
    # 子命令级分权：整命令可用、部分子命令 superuser-only（紧凑族/子命令形态）
    SUBCOMMAND_GATED = {
        "kb",
        "persona",
        "usage",
        "skillcatalog",
        "skillinfo",
        "skillinstall",
        "skilllist",
        "skilluninstall",
        "skills",
    }

    def test_whole_command_list_is_live(self):
        """防恒真：清单里每条都得在 AST 扫出的 gated 集合里坐实。"""
        gated = _superuser_gated_commands()
        stale = [c for c in self.WHOLE_COMMAND_ONLY if c.lstrip("/") not in gated]
        assert not stale, f"清单里有 handler 已不收窄的命令（漂移）：{stale}"

    def test_gated_commands_all_in_admin_section(self):
        from plugins.qq_agent_adapter import help_menu

        sections = {head: {cmd for cmd, _ in rows} for head, rows in help_menu.SECTIONS}
        admin = sections[help_menu.ADMIN_SECTION]
        leaked = sorted(cmd for cmd in self.WHOLE_COMMAND_ONLY if cmd not in admin)
        assert not leaked, f"这些 superuser-only 命令没在管理节：{leaked}"

    def test_new_gated_command_must_be_registered(self):
        """新增未归类的 gated 命令 → 红（归类到上面两张表之一）。"""
        gated = _superuser_gated_commands()
        assert gated, "反向锁扫空了——AST 映射大概率失效（恒真陷阱）"
        unclassified = sorted(
            c
            for c in gated
            if f"/{c}" not in self.WHOLE_COMMAND_ONLY and c not in self.SUBCOMMAND_GATED
        )
        assert not unclassified, (
            "这些命令 handler 收窄了 superuser 但没归类"
            f"（整命令级→WHOLE_COMMAND_ONLY，子命令级→SUBCOMMAND_GATED）：{unclassified}"
        )
