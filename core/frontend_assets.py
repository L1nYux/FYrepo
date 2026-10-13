"""Ordered frontend dependencies; a feature loads each shared script once per render."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Bundle:
    scripts: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


BUNDLES = {
    'base': Bundle(tuple('core/' + name + '.js' for name in (
        'app-runtime', 'app-components', 'site', 'graphite', 'loading',
        'delete-confirm', 'release', 'update-modal',
    ))),
    'shell': Bundle(tuple('core/' + name + '.js' for name in (
        'ownership', 'resource-tree', 'avatars', 'avatar-crop', 'message-scope',
        'app-experience', 'social', 'communication', 'research', 'composer',
        'interaction-repair', 'members', 'permission-templates',
    )) + ('aihub/account-usage.js',), ('base',)),
    'sharing': Bundle(('core/conversation-workflows.js',), ('shell',)),
    'emoji': Bundle(('vendor/emoji-mart/browser.js', 'core/emoji.js'), ('sharing',)),
    'conversation': Bundle(tuple('core/' + name + '.js' for name in (
        'conversations', 'message-layout', 'chat-drafts', 'chat-references',
        'chat-stickers', 'local-chat',
    )), ('emoji',)),
    'comments': Bundle(('core/comment-emoji.js',), ('emoji',)),
    'task': Bundle(('core/mobile-workflows.js',), ('comments',)),
    'assistant': Bundle(('aihub/web-browser.js',), ('emoji',)),
    'usage': Bundle(('aihub/activity-scale.js', 'aihub/usage.js'), ('shell',)),
    'work-list': Bundle(('core/work-list.js',), ('shell',)),
    'plugins': Bundle(('aihub/plugins.js',), ('base',)),
}


def scripts_for(features):
    """Topological order, explicit failures for unknown bundles or dependency cycles."""
    result, seen, visiting = [], set(), set()

    def visit(name):
        if name in seen:
            return
        if name in visiting:
            raise ValueError(f'Frontend dependency cycle: {name}')
        bundle = BUNDLES[name]
        visiting.add(name)
        for dependency in bundle.requires:
            visit(dependency)
        visiting.remove(name)
        seen.add(name)
        for script in bundle.scripts:
            if script not in result:
                result.append(script)

    for feature in features:
        visit(feature)
    return result


def page_features(context):
    request = context.get('request')
    match = getattr(request, 'resolver_match', None)
    name = match.url_name if match else ''
    features = ['base']
    if not context.get('shell_enabled'):
        return features
    features.append('shell')
    if name in ('dashboard', 'task_list'):
        features.append('work-list')
    # A failed POST may render a detail page from another endpoint. The renderer
    # declares its features so errors retain the same controls as a normal GET.
    features.extend(context.get('frontend_features', ()))
    if context.get('is_messages'):
        features.append('conversation')
    if name == 'task_detail':
        features.append('task')
    elif name in ('project_detail', 'document_detail'):
        features.append('comments')
    if context.get('is_assistant'):
        features.append('assistant')
    if context.get('is_ai_module') and not context.get('is_plugins'):
        features.append('usage')
    return features
