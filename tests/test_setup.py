"""Test that project setup is working correctly."""



def test_package_imports():
    """Verify all main dependencies can be imported."""
    # Core dependencies

    # Our package
    import trading_system

    assert trading_system.__version__ == "0.1.0"


def test_dev_dependencies():
    """Verify dev dependencies are available."""
