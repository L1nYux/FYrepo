"""模板上下文：把生效角色交给所有模板，避免每个视图重复传一遍。

模板里用 `is_admin` / `is_developer` / `is_normal` / `role_label` 判断界面差异；
视图如果自己在上下文里传了同名变量，以视图为准（视图用的是同一个判定函数，不会矛盾）。
"""

from . import permissions as perms


def role(request):
    current = getattr(request, 'role', None)
    if current not in perms.RANK:
        current = perms.account_role(getattr(request, 'user', None))
    available = perms.allowed_login_roles(getattr(request, 'user', None))
    return {
        'role': current,
        'role_label': perms.role_label(current),
        'is_admin': current == perms.ADMIN,
        'is_developer': current == perms.DEVELOPER,
        'is_normal': current == perms.NORMAL,
        'home_url_name': perms.home_url_name(current),
        'available_roles': [(value, perms.ROLE_LABELS[value]) for value in available],
    }
