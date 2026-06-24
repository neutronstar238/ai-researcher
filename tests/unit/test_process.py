from autoresearch import process


class _FakeSubprocess:
    CREATE_NO_WINDOW = 0x08000000


def test_windows_no_window_kwargs_empty_off_windows() -> None:
    assert process.windows_no_window_kwargs(os_name="posix") == {}


def test_windows_no_window_kwargs_combines_creationflags() -> None:
    kwargs = process.windows_no_window_kwargs(
        creationflags=0x00000200,
        os_name="nt",
        subprocess_module=_FakeSubprocess,
    )

    assert kwargs == {"creationflags": 0x08000200}
