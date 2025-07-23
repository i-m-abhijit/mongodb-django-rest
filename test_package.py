#!/usr/bin/env python3
"""
Simple test script to verify the mongodb-rest package works correctly.
"""


def test_imports():
    """Test that all main components can be imported."""
    try:
        # Test main imports
        from mongodb import connect, disconnect, Document, DocumentSerializer
        print("✓ Main imports successful")

        # Test submodule imports
        from mongodb.connection import connect as connect_func
        from mongodb.document import Document as DocumentClass
        from mongodb.rest_framework.serializers import DocumentSerializer as SerializerClass
        print("✓ Submodule imports successful")

        # Test that __all__ is properly defined
        import mongodb
        print(f"✓ Available exports: {mongodb.__all__}")

        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


def test_basic_functionality():
    """Test basic functionality without requiring a MongoDB connection."""
    try:
        from mongodb.connection import _check_db_name

        # Test valid database name
        _check_db_name("test_db")
        print("✓ Database name validation works")

        # Test invalid database name
        try:
            _check_db_name("invalid.db")
            print("✗ Should have failed for invalid database name")
            return False
        except ValueError:
            print("✓ Database name validation correctly rejects invalid names")

        return True
    except Exception as e:
        print(f"✗ Functionality test error: {e}")
        return False


if __name__ == "__main__":
    print("Testing mongodb-rest package...")
    print("=" * 50)

    success = True
    success &= test_imports()
    success &= test_basic_functionality()

    print("=" * 50)
    if success:
        print("🎉 All tests passed! Package is working correctly.")
    else:
        print("❌ Some tests failed. Check the output above.")
