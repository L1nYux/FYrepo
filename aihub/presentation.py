"""Presentation only: never interpret model prose as executable tool calls."""
import re

PROTOCOL = r'(?:search_results|tool_name|tool_call|tool_calls|function_call|tool_response|tool_result|invoke|parameters)'

def clean_response(value):
    if not isinstance(value, str): return ''
    # Preserve literal protocol examples inside Markdown code blocks/spans.
    parts = re.split(r'(```[\s\S]*?(?:```|\Z)|`[^`\n]*`)', value[:160000])
    for index in range(0,len(parts),2):
        text=parts[index]
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
    for key in ('text','reasoning'):
        if key in result: result[key]=clean_response(result[key])
    if result.get('progress'): result['progress']=display_result(result['progress'])
    return result
