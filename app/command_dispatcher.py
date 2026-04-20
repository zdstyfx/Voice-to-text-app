"""语音命令注册、匹配、分发框架"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Command:
    name: str
    keywords: List[str]
    handler: Callable[[Dict[str, Any]], Any]


@dataclass
class CommandResult:
    command_name: str
    success: bool
    message: str = ""


class CommandDispatcher:
    """命令注册、匹配、分发框架。"""

    def __init__(self) -> None:
        self._commands: List[Command] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(
            "start_transcribe",
            ["开始录音", "开始转写", "start recording"],
            lambda ctx: None,
        )
        self.register(
            "stop_transcribe",
            ["停止录音", "停止转写", "stop recording"],
            lambda ctx: None,
        )
        self.register(
            "exit_active",
            ["退出", "取消", "再见", "exit", "cancel"],
            lambda ctx: None,
        )

    def register(
        self,
        name: str,
        keywords: List[str],
        handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        self._commands.append(Command(name=name, keywords=keywords, handler=handler))

    def match(self, text: str) -> Optional[Command]:
        """关键词包含匹配，返回最长匹配命令或 None。"""
        text_lower = text.lower().strip()
        best: Optional[Command] = None
        best_len = 0
        for cmd in self._commands:
            for kw in cmd.keywords:
                if kw.lower() in text_lower and len(kw) > best_len:
                    best = cmd
                    best_len = len(kw)
        return best

    def execute(self, command: Command, context: Dict[str, Any]) -> CommandResult:
        try:
            command.handler(context)
            logger.info("Command executed: %s", command.name)
            return CommandResult(command_name=command.name, success=True)
        except Exception as exc:
            logger.error("Command '%s' failed: %s", command.name, exc)
            return CommandResult(
                command_name=command.name, success=False, message=str(exc)
            )
