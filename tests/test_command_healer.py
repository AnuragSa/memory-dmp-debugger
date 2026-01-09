"""Test the command healer functionality."""

from dump_debugger.utils.command_healer import CommandHealer


def test_healer():
    """Test various healing scenarios."""
    
    print("=== Command Healer Tests ===\n")
    
    # Test with LLM-based healing
    print("Testing with LLM-powered dynamic healing:")
    print("-" * 50)
    healer_llm = CommandHealer(use_llm=True)
    
    # Test 1: Thread syntax error
    print("\nTest 1: Thread syntax error (LLM)")
    cmd1 = "~~[0]e !clrstack"
    error1 = "Illegal thread error in '~~[0]e !clrstack'"
    healed1 = healer_llm.heal_command(cmd1, error1)
    print(f"  Original: {cmd1}")
    print(f"  Error: {error1}")
    print(f"  Healed: {healed1}\n")
    
    # Test 2: Data model to SOS
    print("Test 2: Data model command failing (LLM)")
    cmd2 = "dx @$curprocess.Threads"
    error2 = "Unable to bind name 'Threads'"
    healed2 = healer_llm.heal_command(cmd2, error2)
    print(f"  Original: {cmd2}")
    print(f"  Error: {error2}")
    print(f"  Healed: {healed2}\n")
    
    # Test 3: Invalid object address
    print("Test 3: Invalid object address (LLM)")
    cmd3 = "!do 0x00007ffcade9b218"
    error3 = "Object 0x00007ffcade9b218 not found or invalid"
    context3 = {
        'previous_evidence': [
            {
                'command': '!dumpheap -type SqlConnection',
                'output': '''
Address               MT     Size
00000280b384e7c0 00007ffcade9b218       96
00000280b384e820 00007ffcade9b188       24
00000280b384e900 00007ffcade9b158      120
'''
            }
        ]
    }
    healed3 = healer_llm.heal_command(cmd3, error3, context3)
    print(f"  Original: {cmd3}")
    print(f"  Error: {error3}")
    print(f"  Healed: {healed3}\n")
    
    # Test with pattern-based fallback
    print("\n" + "=" * 50)
    print("Testing with pattern-based fallback (no LLM):")
    print("-" * 50)
    healer_pattern = CommandHealer(use_llm=False)
    
    # Test 4: Unknown command (pattern)
    print("\nTest 4: Unknown command typo (pattern)")
    cmd4 = "dumpheap -stat"
    error4 = "Unknown command: dumpheap"
    healed4 = healer_pattern.heal_command(cmd4, error4)
    print(f"  Original: {cmd4}")
    print(f"  Error: {error4}")
    print(f"  Healed: {healed4}\n")
    
    # Test 5: Syntax error (pattern)
    print("Test 5: Syntax error (pattern)")
    cmd5 = "!dumpheap-type String"
    error5 = "Syntax error at '-type'"
    healed5 = healer_pattern.heal_command(cmd5, error5)
    print(f"  Original: {cmd5}")
    print(f"  Error: {error5}")
    print(f"  Healed: {healed5}\n")
    
    # Print combined statistics
    print("=" * 50)
    print("=== Healing Statistics ===")
    stats_llm = healer_llm.get_stats()
    stats_pattern = healer_pattern.get_stats()
    print(f"\nLLM-based healing:")
    print(f"  Successful: {stats_llm['successful_heals']}")
    print(f"  Failed: {stats_llm['failed_heals']}")
    print(f"  Success rate: {stats_llm['success_rate']:.1%}")
    
    print(f"\nPattern-based healing:")
    print(f"  Successful: {stats_pattern['successful_heals']}")
    print(f"  Failed: {stats_pattern['failed_heals']}")
    print(f"  Success rate: {stats_pattern['success_rate']:.1%}")
    
    print("\n" + "=" * 50)
    print("The healer tries LLM first (intelligent, context-aware)")
    print("Falls back to patterns if LLM unavailable or fails")


if __name__ == "__main__":
    test_healer()
