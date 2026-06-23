import subprocess

from autoresearch import process


def test_windows_no_window_kwargs_empty_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(process.os, "name", "posix")

    assert process.windows_no_window_kwargs() == {}


def test_windows_no_window_kwargs_combines_creationflags(monkeypatch) -> None:
    monkeypatch.setattr(process.os, "name", "nt")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    kwargs = process.windows_no_window_kwargs(creationflags=0x00000200)

    assert kwargs == {"creationflags": 0x08000200}
