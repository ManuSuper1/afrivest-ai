import os
import glob

replacements = {
    "afrivest_ai.backend": "afrivest_ai.core.backend",
    "afrivest_ai.agent": "afrivest_ai.core.agent",
    "afrivest_ai.subagents": "afrivest_ai.core.subagents",
    "afrivest_ai.prompts": "afrivest_ai.core.prompts",
    "afrivest_ai.runner": "afrivest_ai.core.runner",
    "afrivest_ai.streaming": "afrivest_ai.core.streaming",
    "afrivest_ai.extraction": "afrivest_ai.core.extraction",
    "afrivest_ai.tools": "afrivest_ai.core.tools",
    "afrivest_ai.schemas": "afrivest_ai.models.schemas",
    "afrivest_ai.runtime_context": "afrivest_ai.models.runtime_context",
    "afrivest_ai.fx": "afrivest_ai.core.tools.fx",
    "afrivest_ai.search": "afrivest_ai.core.tools.search",
    "afrivest_ai import build_agent": "afrivest_ai.core.agent import build_agent",
    "afrivest_ai import arun_market_entry_research": "afrivest_ai.core.runner import arun_market_entry_research",
}

for filepath in glob.glob("src/**/*.py", recursive=True) + glob.glob("examples/**/*.py", recursive=True) + glob.glob("run_example.py"):
    if not os.path.isfile(filepath):
        continue
    with open(filepath, "r") as f:
        content = f.read()
    
    new_content = content
    for old, new in replacements.items():
        new_content = new_content.replace(old, new)
        
    if new_content != content:
        with open(filepath, "w") as f:
            f.write(new_content)
        print(f"Updated {filepath}")
