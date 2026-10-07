"""Display model families and capabilities without making inference requests.

Prefer catalog modality metadata; known identifiers fill gaps in simple /models
responses. An unfamiliar identifier stays available as a generic conversation.
"""
from urllib.parse import urlsplit

USES = {'chat': '文本对话', 'vision': '多模态对话', 'image': '图片生成',
        'video': '视频生成', 'audio': '语音 / 实时音频', 'embedding': '向量 / 排序', 'other': '其他用途'}


def describe(identifier, row=None):
    row = row or {}
    name = identifier.lower().removeprefix('models/')
    vendors = [('qwen', '千问'), ('glm', '智谱'), ('chatglm', '智谱'), ('zhipu/', '智谱'),
               ('zai/', '智谱'), ('deepseek', 'DeepSeek'), ('minimax', 'MiniMax'),
               ('kimi', '月之暗面'), ('moonshot', '月之暗面'), ('step', '阶跃星辰'),
               ('claude', 'Anthropic'), ('anthropic/', 'Anthropic'), ('gpt', 'OpenAI'),
               ('chatgpt', 'OpenAI'), ('openai/', 'OpenAI'), ('gemini', 'Google'),
               ('google/', 'Google'), ('llama', 'Meta'), ('meta-llama/', 'Meta'),
               ('mistral', 'Mistral'), ('mistralai/', 'Mistral'), ('wan', '通义万相')]
    vendor = next((label for prefix, label in vendors if name.startswith(prefix)), None)
    if vendor is None:
        author = row.get('owned_by') or row.get('author')
        vendor = author[:80] if isinstance(author, str) and author.strip() else '其他 / 未标明'
    architecture = row.get('architecture')
    output = architecture.get('output_modalities') if isinstance(architecture, dict) else None
    inputs = architecture.get('input_modalities') if isinstance(architecture, dict) else None
    output = output if isinstance(output, list) else []
    inputs = inputs if isinstance(inputs, list) else []
    if any(word in name for word in ('embedding', 'rerank', 'bge-')):
        use = 'embedding'
    elif any(word in name for word in ('realtime', 'tts', 'asr', 'whisper', 'transcrib', 'speech', '-audio')) or ('audio' in output and 'text' not in output):
        use = 'audio'
    elif any(word in name for word in ('cogvideo', 'wan-', 'sora', 'veo', 'video-generation')) or ('video' in output and 'text' not in output):
        use = 'video'
    elif any(word in name for word in ('qwen-image', 'gpt-image', 'dall-e', 'cogview', 'flux', 'image-generation', 'image-01', 'image-02')) or ('image' in output and 'text' not in output):
        use = 'image'
    elif any(word in name for word in ('moderation', 'search-')) or (output and 'text' not in output):
        use = 'other'
    elif any(word in name for word in ('-vl', 'vision', 'glm-4v', 'glm-5v', 'glm-5.3-flash')) or any(m in inputs for m in ('image', 'video')):
        use = 'vision'
    else:
        use = 'chat'
    supported = use in ('chat', 'vision')
    return {'vendor': vendor, 'use': use, 'use_label': USES[use], 'assistant_supported': supported,
            'unavailable_reason': '' if supported else '当前助手暂不支持此用途'}


def channel(provider):
    host = urlsplit(provider.base_url).hostname or ''
    if host in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'coding.dashscope.aliyuncs.com'):
        return '阿里云百炼'
    if host == 'openrouter.ai': return 'OpenRouter'
    return provider.name
