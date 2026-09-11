import json
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "sme_procurement"


def load_prompt(version: str = None):
    """Load system and user template prompts for a given version."""
    manifest = json.loads((PROMPTS_DIR / "manifest.json").read_text())
    version = version or manifest["active_version"]
    entry = manifest["versions"][version]

    system = (PROMPTS_DIR / entry["system"]).read_text()
    user_template = (PROMPTS_DIR / entry["user_template"]).read_text()
    return system, user_template, version