"""Skill 权限控制。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PermissionChecker:
    """按 superuser / user / group 控制 skill 可用性，支持通配符。

    M5（REVIEW-de09478..workdir）：superuser 集合不支持 ``"*"`` 通配。
    历史坑：env ``SUPERUSERS=*`` 会让 checker 对任何人放行（registry 层全部
    superuser 技能披露），而 handler 层 ``is_superuser`` 对所有人 fail-closed
    ——净效果=超级用户 schema 全披露 + 功能全瞎，且与「勿恢复任何形式
    superusers 通配」的 P0 决意相悖。现在 ``"*"`` 在构造期即被剔除并告警
    （按空集处理），"wildcard" 只保留给 group/user 技能名匹配（``*``、
    ``ns.*``）——那是另一维度，不受影响。

    **信任模型（"where" 轴）**：同一个 superuser 在私聊里是完整能力，
    在群里只应看到与公开（访客）面同级的工具——群是多人可见的场合，
    schema 一旦披露就等于把「管理员工具存在」告诉所有群友，且模型可能
    被群友诱导去调用。因此本类按 ``group_id`` 是否为空分档：

    * 私聊：superuser 全开；非 superuser 走原授权逻辑（主路径已由 ACL
      拦在门外，这里只作纵深）。
    * 群聊 + superuser：非 superuser 权限串的技能可见；``permission ==
      "superuser"`` 的技能**默认不可见**，只有 ``AGENT_GROUP_EXTRA_SKILLS``
      显式列出、且技能本身 ``read_only=True`` 时才可见（只读运维查询这类
      低风险工具）。
    * 群聊 + 非 superuser（访客）：**只**可见 ``guest=True`` 的技能，且仍受
      既有 group/user 级授权约束（如点歌群给 ``play_music`` 的授权）。公开
      技能的默认可见性（``default_permission``）只对私聊生效——群内访客面
      是 fail-closed 白名单，不是"public 即给群友"。
    """

    def __init__(
        self,
        superusers: set[str] | None = None,
        group_skills: dict[str, set[str]] | None = None,
        user_skills: dict[str, set[str]] | None = None,
        default_permission: str = "public",
        group_extra_skills: set[str] | None = None,
    ):
        self.superusers = set(superusers or [])
        if "*" in self.superusers:
            logger.warning(
                "[permissions] superusers 含 '*' 通配：已按空集剔除（勿恢复任何"
                "形式的 superusers 通配——P0 决意，REVIEW-de09478..workdir M5）"
            )
            self.superusers.discard("*")
        self.group_skills = {k: set(v) for k, v in (group_skills or {}).items()}
        self.user_skills = {k: set(v) for k, v in (user_skills or {}).items()}
        self.default_permission = default_permission
        # 群内 superuser 的**只读**额外工具（AGENT_GROUP_EXTRA_SKILLS）。
        # 名字集合由适配层解析/校验；这里的 read_only 判定在 is_allowed 里
        # 逐次复核（技能可能条件注册，注册顺序不稳定，不能只在启动期判一次）。
        self.group_extra_skills = set(group_extra_skills or ())

    def is_allowed(
        self,
        skill_name: str,
        user_id: str | None,
        group_id: str | None,
        skill_permission: str = "public",
        *,
        guest: bool = False,
        read_only: bool = False,
        owner: bool = False,
    ) -> bool:
        # cron agent_turn 以 owner 身份运行：jobs.json 是 owner 手写的主机配置，
        # 属可信指令，因此与私聊 owner 同权（AC D4 M2）。这条必须排在最前面——
        # 它绕过的正是「群聊收紧」这一层，而群聊收紧对 cron 不适用（cron 的
        # 会话是隔离的，没有第三方在场）。
        if owner:
            return True
        is_superuser = bool(user_id) and user_id in self.superusers

        if group_id:
            if is_superuser:
                if skill_permission != "superuser":
                    return True
                # 群内 owner 的 superuser 技能：仅白名单 + 只读，两条都满足
                return read_only and skill_name in self.group_extra_skills
            # 群内访客：只有访客面技能；superuser 级技能无论如何不给
            if skill_permission == "superuser" or not guest:
                return False
            return self._granted(skill_name, user_id, group_id, skill_permission)

        # 私聊
        if is_superuser:
            return True
        return self._granted(skill_name, user_id, group_id, skill_permission)

    def _granted(
        self,
        skill_name: str,
        user_id: str | None,
        group_id: str | None,
        skill_permission: str,
    ) -> bool:
        # user 级覆盖
        if user_id and user_id in self.user_skills:
            if self._matches(self.user_skills[user_id], skill_name):
                return True
        # group 级覆盖
        if group_id and group_id in self.group_skills:
            if self._matches(self.group_skills[group_id], skill_name):
                return True
        # 非 public 技能（如 superuser/restricted）：仅显式授权（超管/user/group
        # 配置）可见，不受 default_permission 影响——管理员工具的 schema 不再对
        # 普通用户暴露
        if skill_permission != "public":
            return False
        # 默认：仅 public
        return self.default_permission == "public"

    def _matches(self, allowed: set[str], skill_name: str) -> bool:
        if "*" in allowed:
            return True
        if skill_name in allowed:
            return True
        for pattern in allowed:
            if pattern.endswith(".*"):
                ns = pattern[:-2]
                if skill_name.startswith(f"{ns}."):
                    return True
        return False
