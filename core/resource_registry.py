"""Canonical resource names shared by lists, search and chat references."""
RESOURCES = {
    'project': {'label': '项目', 'detail': 'project_detail', 'search': ('name', 'description'), 'icon': 'project'},
    'task': {'label': '任务', 'detail': 'task_detail', 'search': ('title', 'description', 'project__name'), 'icon': 'task'},
    'document': {'label': '文档', 'detail': 'document_detail', 'search': ('title',), 'icon': 'document'},
    'experiment': {'label': '实验', 'detail': 'experiment_detail', 'search': ('title', 'number'), 'icon': 'experiment'},
    'entry': {'label': '财务记录', 'search': ('memo',), 'icon': 'finance'},
    'claim': {'label': '报销申请', 'search': ('memo',), 'icon': 'finance'},
    'announcement': {'label': '公告', 'search': ('title', 'body'), 'icon': 'announcement'},
}
