def test_import_autoresearch_package() -> None:
    import autoresearch

    assert autoresearch.__version__


def test_import_autoresearch_config() -> None:
    from autoresearch.config import ConfigParser, SystemConfig

    assert SystemConfig().knowledge_base.vault_path
    assert ConfigParser()
