import shutil
import os
from pathlib import Path

# Paths
source_dir = Path("/Users/sigey/Library/Application Support/Google/Chrome/Profile 3")
target_dir = Path("/Users/sigey/Documents/Projects/OpenClaw Resume Bot/user_data_dir/Profile 3")
base_target_dir = Path("/Users/sigey/Documents/Projects/OpenClaw Resume Bot/user_data_dir")

print(f"Migrating ClawdBot Chrome Profile...")
print(f"Source: {source_dir}")
print(f"Target: {target_dir}")

# Ensure we don't overwrite if it's currently in use (which we know it isn't based on ps)
if base_target_dir.exists():
    shutil.rmtree(base_target_dir)
os.makedirs(base_target_dir, exist_ok=True)

# Copy the entire Profile 3 Directory to the isolated project folder
try:
    shutil.copytree(source_dir, target_dir)
    print("✅ Profile successfully migrated to isolated Project Directory.")
    print("This ensures 'nodriver' can access the session cookies without fighting macOS native Chrome locks.")
except Exception as e:
    print(f"❌ Migration failed: {e}")
