# permissions.py — migrated from root directory

PERMISSIONS = {
    "read_file": "allow",
    "list_dir": "allow",
    "glob_files": "allow",
    "run_bash": "allow",
    "todo_write": "allow",
    "write_file": "allow",
    "edit_file": "allow",
    "task": "allow",

    "delete_file": "deny",
}


def check_permission(tool_name: str):
    """
    Check if a tool is allowed to execute.

    Returns:
        (True, None) if allowed
        (False, reason) if denied
    """
    permission = PERMISSIONS.get(tool_name, "deny")
    if permission == "allow":
        return True, None
    return False, f"Permission denied: {tool_name}"
