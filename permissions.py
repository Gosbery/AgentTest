PERMISSIONS = {
    "read_file": "allow",
    "list_dir": "allow",
    "glob_files": "allow",
    "get_location": "allow",
    "get_weather": "allow",
    "todo_write": "allow",

    "write_file": "deny",
    "edit_file": "allow",

    "delete_file": "deny",
}


def check_permission(tool_name: str):
    """
    检查工具是否允许执行。

    输入：
        tool_name: str
            工具名称。

    输出：
        tuple[bool, str | None]
            - True, None:
                允许执行
            - False, reason:
                禁止执行，并返回原因
    """

    permission = PERMISSIONS.get(tool_name, "deny")

    if permission == "allow":
        return True, None

    return False, f"Permission denied: {tool_name}"