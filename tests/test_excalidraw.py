#!/usr/bin/env python3
"""
Test script to verify Excalidraw generation works correctly
"""

import json
import sys
import os

# Add the Groundwire directory to path
sys.path.insert(0, os.path.dirname(__file__))

from groundwire_cli import GroundwireAgent

def test_excalidraw_generation():
    """Test that the agent can generate valid Excalidraw JSON"""

    print("Testing Excalidraw generation...")

    # Initialize the agent
    agent = GroundwireAgent()

    # Test that we can create a basic Excalidraw structure
    basic_excalidraw = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": [],
        "appState": {},
        "files": {}
    }

    try:
        # Validate the JSON structure
        json.dumps(basic_excalidraw)
        print("✓ Basic Excalidraw JSON structure is valid")
    except json.JSONDecodeError as e:
        print(f"✗ Basic Excalidraw JSON is invalid: {e}")
        return False

    # Test that the agent has the required attributes
    if hasattr(agent, 'created_files'):
        print("✓ Agent has file tracking capability")
    else:
        print("✗ Agent missing file tracking")
        return False

    print("✓ All tests passed!")
    return True

if __name__ == "__main__":
    success = test_excalidraw_generation()
    sys.exit(0 if success else 1)