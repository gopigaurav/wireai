#!/usr/bin/env python3
"""
Test: Verify detailed diagram detection works correctly
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from groundwire_cli import GroundwireAgent

def test_detailed_diagram_detection():
    """Test that the agent correctly detects detailed diagram requests"""
    
    agent = GroundwireAgent()
    
    print("=" * 70)
    print("  Testing Detailed Diagram Detection")
    print("=" * 70)
    print()
    
    test_cases = [
        # Should trigger auto-enhancement
        ("create a very detailed exclidraw diagram for cloudflare", True),
        ("Draw a comprehensive architecture diagram", True),
        ("Create an in-depth diagram of Kubernetes", True),
        ("Very detailed diagram showing internal flows", True),
        ("Complete breakdown of microservices architecture diagram", True),
        ("Detailed excalidraw of AWS infrastructure", True),
        ("comprehensive system design diagram", True),
        ("deeply detailed internal working diagram", True),
        
        # Should NOT trigger auto-enhancement
        ("create a simple web architecture diagram", False),
        ("Draw a database schema", False),
        ("Make a basic deployment diagram", False),
        ("create a diagram", False),
        ("simple excalidraw", False),
        ("Give me a summary", False),
        ("Tell me about microservices", False),
        ("Complete breakdown of microservices", False),  # No diagram keyword
    ]
    
    print("Test Results:")
    print("-" * 70)
    
    passed = 0
    failed = 0
    
    for prompt, expected in test_cases:
        result = agent._is_detailed_diagram_request(prompt)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        expected_text = "TRIGGER auto-enhancement" if expected else "skip auto-enhancement"
        result_text = "TRIGGERED" if result else "skipped"
        
        print(f"{status} | {result_text:10} | {expected_text:25} | {prompt[:50]}")
    
    print("-" * 70)
    print(f"\nResults: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    
    if failed == 0:
        print("✓ All tests passed!")
        return True
    else:
        print(f"✗ {failed} tests failed")
        return False

if __name__ == "__main__":
    success = test_detailed_diagram_detection()
    sys.exit(0 if success else 1)
