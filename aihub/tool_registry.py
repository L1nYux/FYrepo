"""Trusted tool manifests. Model input can select tools, never register code."""
from copy import deepcopy
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class Tool:
    name: str
    label: str
    description: str
    properties: dict
    required: tuple
    handler: str = 'aihub.agent.read_tool'
    effect: str = 'read'

    def definition(self):
        return {'type': 'function', 'function': {'name': self.name, 'description': self.description,
            'parameters': {'type': 'object', 'properties': deepcopy(self.properties),
                'required': list(self.required), 'additionalProperties': False}}}


@dataclass(frozen=True)
class Plugin:
    id: str
    label: str
    tools: tuple
    version: str = '1'
    default_enabled: bool = True


class Registry:
    def __init__(self):
        self.plugins = {}
        self.tools = {}
        self.owners = {}

    def register(self, plugin):
        names = [tool.name for tool in plugin.tools]
        if plugin.id in self.plugins or len(set(names)) != len(names) or any(name in self.tools for name in names):
            raise ValueError('插件或工具名称重复。')
        if any(tool.effect not in ('read', 'write') for tool in plugin.tools):
            raise ValueError('工具必须声明读写类别。')
        self.plugins[plugin.id] = plugin
        for tool in plugin.tools:
            self.tools[tool.name] = tool
            self.owners[tool.name] = plugin.id

    def get(self, name):
        if name not in self.tools:
            raise ValidationError('工具不存在。')
        return self.tools[name]

    def invoke(self, user, name, args):
        tool = self.get(name)
        validate(tool.definition()['function']['parameters'], args)
        return import_string(tool.handler)(user, name, args)


def validate(schema, value):
    """Small strict schema subset used by our manifests; no coercion of writes."""
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
        'string': isinstance(value, str), 'integer': type(value) is int, 'boolean': type(value) is bool}
    if kind not in valid or not valid[kind]:
        raise ValidationError('工具参数类型无效。')
    if 'enum' in schema and value not in schema['enum']:
        raise ValidationError('工具选项无效。')
    if kind == 'object':
        fields = schema.get('properties', {})
        if set(value) - set(fields) or any(key not in value for key in schema.get('required', [])):
            raise ValidationError('工具参数缺失或包含未知字段。')
        for name, item in value.items():
            validate(fields[name], item)
    if kind in ('string', 'array') and len(value) > schema.get('maxLength' if kind == 'string' else 'maxItems', 30000 if kind == 'string' else 100):
        raise ValidationError('工具参数超过长度限制。')
    if kind == 'array':
        for item in value:
            validate(schema['items'], item)
    if kind == 'integer' and not schema.get('minimum', 0) <= value <= schema.get('maximum', 2**63-1):
        raise ValidationError('工具参数超出范围。')


registry = Registry()
identifier = {'type': 'integer', 'minimum': 1}
text = {'type': 'string'}
kinds = {'type': 'string', 'enum': ['document','project','task','experiment','announcement','message','entry','claim']}
registry.register(Plugin('workspace', '工作资料', (
    Tool('my_workspace', '读取我的待办与公告', '读取当前账户资料、本人待办和最新公告。', {}, ()),
    Tool('search_workspace', '搜索工作资料', '搜索有权查看的项目、任务、文档、实验、公告、财务或聊天。空查询列出最近记录。',
        {'kind': kinds, 'query': text, 'project_id': identifier}, ('kind','query')),
    Tool('read_record', '读取资料详情', '读取资料详情；项目包含成员编号，任务包含进度，在线文档包含修改稿编号与版本。', {'kind': kinds, 'id': identifier}, ('kind','id')),
    Tool('read_attachment', '读取附件正文', '提取有权查看的 TXT、PDF、DOCX、XLSX 附件文字。', {'id': identifier}, ('id',)),
)))
registry.register(Plugin('web', '互联网资料', (
    Tool('search_web', '搜索互联网', '搜索公开互联网。去掉提问中的客套语，保留主题关键词。', {'query': text}, ('query',)),
    Tool('read_web', '读取网页正文', '读取公开网页或 PDF 正文。不能读取内网或登录页面。', {'url': text, 'mode': {'type': 'string','enum': ['auto','static','browser']}}, ('url',)),
)))
registry.register(Plugin('tasks', '任务协作', (
    Tool('create_task', '创建任务', '在授权项目内创建任务。先读取项目确认成员编号；相同参数在本轮及重试中只创建一次。',
        {'project_id': identifier, 'title': {'type': 'string','maxLength':160}, 'description': {'type':'string','maxLength':5000},
         'assignee_id': identifier, 'member_ids': {'type':'array','items':identifier,'maxItems':30},
         'due_date': {'type':'string','maxLength':10}, 'parent_id': identifier}, ('project_id','title'),
        'aihub.workspace_tools.write_tool', 'write'),
    Tool('update_task_progress', '更新任务进度', '更新授权项目内任务进度（0 到 99）；必须先读取当前进度作为 expected_progress。正式结项走成果审核。',
        {'task_id': identifier, 'progress': {'type':'integer','minimum':0,'maximum':99},
         'expected_progress': {'type':'integer','minimum':0,'maximum':99}}, ('task_id','progress','expected_progress'),
        'aihub.workspace_tools.write_tool', 'write'),
)))
registry.register(Plugin('documents', '文档草稿', (
    Tool('save_document_draft', '保存文档草稿', '保存授权项目内在线文档的本人修改稿。先读取文档取得 draft_id 和 generation；正式版本保持原有审核流程。',
        {'document_id': identifier, 'draft_id': {'type':'integer','minimum':0}, 'generation': {'type':'integer','minimum':0},
         'text': {'type':'string','maxLength':30000}}, ('document_id','draft_id','generation','text'),
        'aihub.workspace_tools.write_tool', 'write'),
)))
