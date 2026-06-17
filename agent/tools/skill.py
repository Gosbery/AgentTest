"""
Skill tool — loads skill content on demand via the load_skill tool.
"""


def make_load_skill(loader):
    """
    Factory: returns a load_skill function bound to the given loader.

    The returned function is callable as a tool:
        load_skill(name="git") -> "<skill name=\"git\">...body...</skill>"
    """
    def load_skill(name: str) -> str:
        body = loader.load_skill(name)
        if body is None:
            available = ", ".join(loader.list_skills())
            return f"Error: Skill '{name}' not found. Available: {available}"
        return f'<skill name="{name}">\n{body}\n</skill>'

    return load_skill


def make_load_skill_schema(loader) -> dict:
    """Create the OpenAI-compatible tool schema for load_skill."""
    skill_names = ", ".join(loader.list_skills())
    return {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": f"Load a skill's full instructions by name. Available skills: {skill_names}",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": f"Name of the skill to load. Available: {skill_names}",
                    }
                },
                "required": ["name"],
            },
        },
    }
