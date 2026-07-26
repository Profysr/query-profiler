# tests/conftest.py
def pytest_collection_modifyitems(items):
    """
    Automatically applies @pytest.mark.django or @pytest.mark.core
    based on the file path of the test.
    """
    for item in items:
        test_path = str(item.fspath)
        
        if "tests/core" in test_path:
            item.add_marker("core")
        elif "tests/adapters/django" in test_path:
            item.add_marker("django")
        elif "tests/adapters/sqlalchemy" in test_path:
            item.add_marker("sqlalchemy")