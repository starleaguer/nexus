import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.config_loader import NexusConfig

print("=== Discovered Skills ===")
skills = NexusConfig.get_discovered_skills()
for s in skills:
    print(f"- {s['name']}: {s['description']}")

print("\n=== Manifest Tools ===")
manifest = NexusConfig.load_manifest()
mcp_tools = manifest.get("tools", {}).get("mcp", [])
for t in mcp_tools:
    print(f"- {t['name']}: {t['description']}")
