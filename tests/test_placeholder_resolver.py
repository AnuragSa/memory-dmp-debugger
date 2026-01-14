"""Test the placeholder resolver functionality."""

from dump_debugger.utils import detect_placeholders, resolve_command_placeholders
from dump_debugger.utils.placeholder_resolver import detect_malformed_thread_command


def test_placeholder_detection():
    """Test that placeholders are detected correctly."""
    # Should detect angle bracket placeholders
    assert detect_placeholders("!gcroot <address_of_sample_object>")
    assert detect_placeholders("!dumpheap -mt <MT_of_largest_objects>")
    assert detect_placeholders("!objsize <address_of_large_object>")
    
    # Should detect malformed thread placeholders
    assert detect_placeholders("~~[ThreadId]s; !clrstack")
    assert detect_placeholders("~~[OWNER_THREAD]e !clrstack")
    assert detect_placeholders("~~[thread]e !dso")
    
    # Should not detect valid OSID syntax (hex values are valid)
    assert not detect_placeholders("~~[d78]e !clrstack")
    assert not detect_placeholders("~~[3fc]s")
    assert not detect_placeholders("~~[abc123]e !clrstack")
    
    # Should not detect regular commands
    assert not detect_placeholders("!threads")
    assert not detect_placeholders("!analyze -v")
    assert not detect_placeholders("~8e !clrstack")
    
    print("✓ Placeholder detection tests passed")


def test_malformed_thread_detection():
    """Test detection of malformed thread placeholder syntax."""
    # Should detect malformed placeholders
    is_malformed, name = detect_malformed_thread_command("~~[ThreadId]s; !clrstack")
    assert is_malformed, "Should detect ThreadId as malformed"
    assert name == "ThreadId"
    
    is_malformed, name = detect_malformed_thread_command("~~[OWNER_THREAD]e !clrstack")
    assert is_malformed, "Should detect OWNER_THREAD as malformed"
    assert name == "OWNER_THREAD"
    
    is_malformed, name = detect_malformed_thread_command("~~[thread]e !dso")
    assert is_malformed, "Should detect thread as malformed"
    assert name == "thread"
    
    # Should NOT detect valid OSID (hex values)
    is_malformed, _ = detect_malformed_thread_command("~~[d78]e !clrstack")
    assert not is_malformed, "d78 is valid hex OSID"
    
    is_malformed, _ = detect_malformed_thread_command("~~[3fc]s")
    assert not is_malformed, "3fc is valid hex OSID"
    
    is_malformed, _ = detect_malformed_thread_command("~~[abc123]e !clrstack")
    assert not is_malformed, "abc123 is valid hex OSID"
    
    # Should NOT detect regular commands
    is_malformed, _ = detect_malformed_thread_command("!threads")
    assert not is_malformed
    
    is_malformed, _ = detect_malformed_thread_command("~8e !clrstack")
    assert not is_malformed
    
    print("✓ Malformed thread detection tests passed")


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


def test_thread_id_resolution():
    """Test that thread IDs are resolved correctly from !syncblk and !threads output."""
    # Mock evidence with !syncblk and !threads output
    evidence = [
        {
            'command': '!syncblk',
            'output': '''Index         SyncBlock MonitorHeld Recursion Owning Thread Info                  SyncBlock Owner
  470 00000254404d07a8           21         1 000002543dd83c70 d78  18   000002540a2692c0 Microsoft.Compiler.VisualBasic.VBCodeProvider
''',
            'evidence_type': 'inline'
        },
        {
            'command': '!threads',
            'output': '''
ThreadCount:      25
         DBG   ID OSID ThreadOBJ           State GC Mode     GC Alloc Context                  Domain           Count Apt
          18   12  d78 000002543dd83c70   20220 Preemptive  0000000000000000:0000000000000000 000002540a1b4000 0     MTA
           0    1 4d8c 000001f2a3b4c5d6   2a020 Preemptive  0000000000000000:0000000000000000 000002540a1b4000 0     MTA
''',
            'evidence_type': 'inline'
        }
    ]
    
    # Test 1: Thread placeholder in ~<num>e format - should use decimal DBG#
    # The DBG# from !syncblk is "18" (hex) = 24 decimal
    command1 = "~<OWNER_THREAD_ID>e !clrstack"
    resolved1, success1, msg1 = resolve_command_placeholders(command1, evidence)
    print(f"Command: {command1}")
    print(f"Resolved: {resolved1}")
    print(f"Success: {success1}, Message: {msg1}")
    # Should convert hex 18 to decimal 24
    assert success1, "Should resolve thread placeholder"
    assert "<OWNER_THREAD_ID>" not in resolved1, "Should not contain placeholder"
    
    # Test 2: Thread placeholder in ~~[osid]e format - should use hex OSID without 0x
    command2 = "~~[<OSID>]e !clrstack"
    resolved2, success2, msg2 = resolve_command_placeholders(command2, evidence)
    print(f"\nCommand: {command2}")
    print(f"Resolved: {resolved2}")
    print(f"Success: {success2}, Message: {msg2}")
    assert success2, "Should resolve OSID placeholder"
    assert "0x" not in resolved2 or "~~[0x" not in resolved2, "OSID in brackets should not have 0x prefix"
    assert "<OSID>" not in resolved2, "Should not contain placeholder"
    
    print("\n✓ Thread ID resolution tests passed")


def test_malformed_thread_resolution():
    """Test that malformed thread placeholders like ~~[ThreadId] get resolved."""
    # Evidence with thread info from !syncblk and !threads
    evidence = [
        {
            'command': '!syncblk',
            'output': '''Index         SyncBlock MonitorHeld Recursion Owning Thread Info                  SyncBlock Owner
  470 00000254404d07a8           21         1 000002543dd83c70 d78  18   000002540a2692c0 Microsoft.Compiler.VisualBasic.VBCodeProvider
''',
            'evidence_type': 'inline'
        },
        {
            'command': '!threads',
            'output': '''
ThreadCount:      25
         DBG   ID OSID ThreadOBJ           State GC Mode     GC Alloc Context                  Domain           Count Apt
          18   12  d78 000002543dd83c70   20220 Preemptive  0000000000000000:0000000000000000 000002540a1b4000 0     MTA
''',
            'evidence_type': 'inline'
        }
    ]
    
    # Test resolving ~~[ThreadId]s; !clrstack - should convert to ~<decimal>s or ~~[hex]
    command = "~~[ThreadId]s; !clrstack"
    resolved, success, msg = resolve_command_placeholders(command, evidence)
    print(f"Command: {command}")
    print(f"Resolved: {resolved}")
    print(f"Success: {success}, Message: {msg}")
    
    assert success, "Should resolve malformed ThreadId placeholder"
    assert "~~[ThreadId]" not in resolved, "Should not contain original placeholder"
    # Should be converted to either ~24s (DBG# 18 hex = 24 decimal) or ~~[d78]s (OSID)
    assert "~" in resolved, "Should have thread prefix"
    
    print("\n✓ Malformed thread resolution tests passed")


def test_thread_registry():
    """Test the thread registry for OSID to managed ID lookups."""
    from dump_debugger.utils.thread_registry import get_thread_registry, ThreadRegistry
    
    print("Testing thread registry...")
    
    # Get the singleton registry
    registry = get_thread_registry()
    
    # Clear any existing data
    registry.clear()
    
    # Register some test threads
    registry.register_thread(dbg_id=0, managed_id=1, osid="4d8c", apartment="MTA")
    registry.register_thread(dbg_id=6, managed_id=2, osid="1234", apartment="MTA", special="Finalizer")
    registry.register_thread(dbg_id=9, managed_id=12, osid="d78", apartment="STA")
    
    # Test lookup by OSID
    info = registry.get_by_osid("4d8c")
    assert info is not None, "Should find thread by OSID"
    assert info.managed_id == 1, "Should have correct managed ID"
    assert info.dbg_id == 0, "Should have correct DBG ID"
    
    # Test lookup with 0x prefix (should be normalized)
    info = registry.get_by_osid("0xd78")
    assert info is not None, "Should find thread by OSID with 0x prefix"
    assert info.managed_id == 12, "Should have correct managed ID"
    
    # Test lookup by DBG ID
    info = registry.get_by_dbg_id(6)
    assert info is not None, "Should find thread by DBG ID"
    assert info.managed_id == 2, "Should have correct managed ID"
    assert info.special == "Finalizer", "Should have special designation"
    
    # Test lookup by managed ID
    info = registry.get_by_managed_id(12)
    assert info is not None, "Should find thread by managed ID"
    assert info.osid == "d78", "Should have correct OSID"
    
    # Test format_thread_id
    formatted = registry.format_thread_id("4d8c")
    assert formatted == "Thread 1", f"Should format as 'Thread 1', got '{formatted}'"
    
    formatted = registry.format_thread_id("1234", include_details=True)
    assert formatted == "Thread 2 (Finalizer)", f"Should format with details, got '{formatted}'"
    
    # Test format for unknown OSID
    formatted = registry.format_thread_id("ffff")
    assert "OSID 0xffff" in formatted, f"Should include OSID for unknown thread, got '{formatted}'"
    
    # Test format from DBG ID
    formatted = registry.format_thread_id_from_dbg(9)
    assert formatted == "Thread 12", f"Should format as 'Thread 12', got '{formatted}'"
    
    # Test thread count
    assert registry.thread_count == 3, "Should have 3 registered threads"
    assert registry.is_populated(), "Should be populated"
    
    print("  ✓ All thread registry tests passed")


if __name__ == "__main__":
    test_placeholder_detection()
    print()
    test_malformed_thread_detection()
    print()
    test_placeholder_resolution()
    print()
    test_thread_id_resolution()
    print()
    test_malformed_thread_resolution()
    print()
    test_thread_registry()
    print("\n✓ All tests passed!")
