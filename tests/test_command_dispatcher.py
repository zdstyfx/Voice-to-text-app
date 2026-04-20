"""Tests for CommandDispatcher."""
from app.command_dispatcher import CommandDispatcher


def test_match_start_transcribe():
    d = CommandDispatcher()
    cmd = d.match("开始录音")
    assert cmd is not None
    assert cmd.name == "start_transcribe"


def test_match_stop_transcribe():
    d = CommandDispatcher()
    cmd = d.match("停止转写")
    assert cmd is not None
    assert cmd.name == "stop_transcribe"


def test_match_exit():
    d = CommandDispatcher()
    for text in ["退出", "取消", "再见", "exit", "cancel"]:
        cmd = d.match(text)
        assert cmd is not None, f"Should match: {text}"
        assert cmd.name == "exit_active"


def test_no_match():
    d = CommandDispatcher()
    cmd = d.match("今天天气怎么样")
    assert cmd is None


def test_register_custom_command():
    d = CommandDispatcher()
    d.register("greet", ["你好", "hello"], lambda ctx: "hi")
    cmd = d.match("你好啊")
    assert cmd is not None
    assert cmd.name == "greet"


def test_execute_success():
    d = CommandDispatcher()
    d.register("test_cmd", ["测试"], lambda ctx: ctx.get("value"))
    cmd = d.match("测试一下")
    result = d.execute(cmd, {"value": 42})
    assert result.success is True
    assert result.command_name == "test_cmd"
