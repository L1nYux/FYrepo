"""Presentation only: never interpret model prose as executable tool calls."""
import re

PROTOCOL = r'(?:search_results|tool_name|tool_call|tool_calls|function_call|tool_response|tool_result|invoke|parameters)'

# Detection only. Prose, JSON and vendor delimiters are NEVER executed as tools.
COMMAND = r'\{\s*"name"\s*:\s*"[a-z_]+"\s*,\s*"(?:arguments|parameters)"\s*:'
LEAK = re.compile(r'<\]minimax\[>|\[minimax\]|<\|tool_call\|>|<tool_(?:call|calls|name)\b|<function_call\b|<invoke\b|<parameters\b|'+COMMAND,re.I)

def prose_parts(value):
    return re.split(r'(```[\s\S]*?(?:```|\Z)|`[^`\n]*`)',str(value or '')[:160000])

def tool_protocol_leak(value):
    return any(LEAK.search(part) for part in prose_parts(value)[::2])


def clean_response(value):
    if not isinstance(value, str): return ''
    # Preserve literal protocol examples inside Markdown code blocks/spans.
    parts = prose_parts(value)
    for index in range(0,len(parts),2):
        text=parts[index]
        # Hide a leaked command tail during streaming and for historical messages.
        leaked=re.search(r'<\]minimax\[>|\[minimax\]|'+COMMAND,text,re.I)
        if leaked: text=text[:leaked.start()]
        text=re.sub(r'<tool_name\b[^>]*>[\s\S]*?</tool_name\s*>','',text,flags=re.I)
        text=re.sub(r'</?'+PROTOCOL+r'\b[^>]*>','',text,flags=re.I)
        text=re.sub(r'<\|(?:im_start|im_end|tool_call|tool_response|endoftext)\|>','',text)
        text=re.sub(r'(?m)^\s*</?\s*$','',text)
        # Hold a partial protocol tag until its next streaming chunk arrives.
        text=re.sub(r'</?(?:search_results|tool_name|tool_call|function_call|tool_response|tool_result|invoke|parameters)?[^>\n]*\Z',lambda m:'' if re.match(r'</?(?:search_|tool_|function_|invoke|parameters)',m[0],re.I) else m[0],text)
        paragraphs=text.split('\n\n'); cleaned=[]
        for p in paragraphs:
            if p.strip() and cleaned and len(p.strip())>=16 and p.strip()==cleaned[-1].strip(): continue
            cleaned.append(p)
        parts[index]='\n\n'.join(cleaned)
    return ''.join(parts).strip()

def display_result(result):
    result=dict(result or {})
    if tool_protocol_leak(result.get('text')):
        result['text']='这条回复未完成实际查询，请重试或换一个模型。'
        result['warning']='模型返回了文字形式的工具指令，应用没有执行。'
    for key in ('text','reasoning'):
        if key in result: result[key]=clean_response(result[key])
    if result.get('progress'): result['progress']=display_result(result['progress'])
    return result
