"""Startup banner rendering."""

from psychtool.config import Config
from psychtool.banner.banner import render_banner, _logo


def test_logo_file_nonempty():
    assert "psychtool" in _logo()


def test_plain_banner_contains_essentials():
    cfg = Config(data_tier="synthetic", model="m", base_url="u")
    out = render_banner(cfg, use_color=False)
    assert "psychtool" in out
    assert "data_tier: synthetic" in out
    assert "psychtool v" in out
    assert "init" in out and "dash" in out


def test_real_tier_shows_warning():
    cfg = Config(data_tier="real", model="m", base_url="u")
    out = render_banner(cfg, use_color=False)
    assert "data_tier: real" in out
    assert "网络调用已禁用" in out


def test_color_banner_contains_ansi():
    cfg = Config(data_tier="synthetic", model="m", base_url="u")
    out = render_banner(cfg, use_color=True)
    assert "\x1b[" in out


def test_plain_banner_has_no_ansi():
    cfg = Config(data_tier="synthetic", model="m", base_url="u")
    out = render_banner(cfg, use_color=False)
    assert "\x1b[" not in out
