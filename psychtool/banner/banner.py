"""Colorful startup banner (presentation layer; may import rich)."""

from __future__ import annotations

from importlib.resources import files
from io import StringIO

from rich.console import Console

from psychtool import __version__
from psychtool.config import Config

LOGO_NAME = "logo.txt"
COMMANDS = "init · import · claims · draft · review · export · eval · judge · dash"


def _logo() -> str:
    return files("psychtool.banner").joinpath(LOGO_NAME).read_text(encoding="utf-8")


def render_banner(config: Config, *, use_color: bool = True) -> str:
    if config.data_tier == "real":
        tier = "data_tier: real  —  网络调用已禁用（仅本地端点）"
        warn = "⚠ 真实数据档：模型流量仅限本地端点"
    else:
        tier = "data_tier: synthetic  —  仅虚构材料"
        warn = ""
    version = f"psychtool v{__version__}"

    if not use_color:
        parts = [_logo(), "", version, tier]
        if warn:
            parts.append(warn)
        parts += ["", COMMANDS]
        return "\n".join(parts)

    console = Console(file=StringIO(), force_terminal=True, color_system="standard", width=90)
    console.print("[bold cyan]" + _logo() + "[/]")
    console.print("[bold]" + version + "[/]")
    console.print("[bold green]" + tier + "[/]" if config.data_tier != "real" else "[bold red]" + tier + "[/]")
    if warn:
        console.print("[red]" + warn + "[/]")
    console.print("[dim]" + COMMANDS + "[/]")
    return console.file.getvalue()
