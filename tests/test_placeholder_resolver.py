"""Test the placeholder resolver functionality."""

from dump_debugger.utils import detect_placeholders, resolve_command_placeholders


def test_placeholder_detection():
    """Test that placeholders are detected correctly."""
    # Should detect placeholders
    assert detect_placeholders("!gcroot <address_of_sample_object>")
    assert detect_placeholders("!dumpheap -mt <MT_of_largest_objects>")
    assert detect_placeholders("!objsize <address_of_large_object>")
    
    # Should not detect placeholders
    assert not detect_placeholders("!threads")
    assert not detect_placeholders("!analyze -v")
    
    print("✓ Placeholder detection tests passed")


def test_placeholder_resolution():
    """Test that placeholders are resolved from evidence."""
    # Mock evidence with sample data
    evidence = [
        {
            'command': '!dumpheap -stat',
            'output': '''
MT    Count    TotalSize Class Name
00007ff8a1234567              5       120 System.String
00007ff8a2345678             10       240 System.Collections.Generic.List`1[[System.String]]
00007ff8a3456789            100     24000 MyApp.LargeObject
''',
            'evidence_type': 'inline'
        },
        {
            'command': '!dumpheap -type System.String',
            'output': '''
Address               MT     Size
000001f2a3b4c5d6 00007ff8a1234567       24     
000001f2a3b4c5e7 00007ff8a1234567       48
000001f2a3b4c5f8 00007ff8a1234567       36
''',
            'evidence_type': 'inline'
        }
    ]
    
    # Test 1: Resolve address placeholder
    command1 = "!gcroot <address>"
    resolved1, success1, msg1 = resolve_command_placeholders(command1, evidence)
    print(f"Command: {command1}")
    print(f"Resolved: {resolved1}")
    print(f"Success: {success1}, Message: {msg1}")
    assert success1, "Should resolve address placeholder"
    assert "0x" in resolved1, "Should have hex address"
    assert "<address>" not in resolved1, "Should not contain placeholder"
    
    # Test 2: Resolve MT placeholder
    command2 = "!dumpheap -mt <MT_of_largest_objects>"
    resolved2, success2, msg2 = resolve_command_placeholders(command2, evidence)
    print(f"\nCommand: {command2}")
    print(f"Resolved: {resolved2}")
    print(f"Success: {success2}, Message: {msg2}")
    assert success2, "Should resolve MT placeholder"
    assert "0x" in resolved2, "Should have hex MT"
    assert "<MT_of_largest_objects>" not in resolved2, "Should not contain placeholder"
    
    # Test 3: Command with no placeholders
    command3 = "!threads"
    resolved3, success3, msg3 = resolve_command_placeholders(command3, evidence)
    print(f"\nCommand: {command3}")
    print(f"Resolved: {resolved3}")
    print(f"Success: {success3}, Message: {msg3}")
    assert success3, "Should succeed with no placeholders"
    assert resolved3 == command3, "Should return original command"
    
    # Test 4: Unresolvable placeholder (no evidence)
    command4 = "!gcroot <address_of_object>"
    resolved4, success4, msg4 = resolve_command_placeholders(command4, [])
    print(f"\nCommand: {command4}")
    print(f"Resolved: {resolved4}")
    print(f"Success: {success4}, Message: {msg4}")
    assert not success4, "Should fail with no evidence"
    assert "<address_of_object>" in resolved4, "Should still contain unresolved placeholder"
    
    print("\n✓ Placeholder resolution tests passed")


if __name__ == "__main__":
    test_placeholder_detection()
    print()
    test_placeholder_resolution()
    print("\n✓ All tests passed!")
