"""Integration fixture using the same mailbox challenge as an actual signup."""
import json
import re
from unittest.mock import patch
from django.urls import reverse
from django.test import override_settings


def verified_post(client,url,data,**kwargs):
    is_json=kwargs.get('content_type')=='application/json'
    payload=json.loads(data) if is_json else dict(data)
    email=payload.get('email','')
    with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'), patch('core.registration_email.send_mail') as mail:
        if is_json:
            client.post(reverse('desktop_api',args=['registration-code']),json.dumps({'email':email}),content_type='application/json')
        else:
            client.post(url,{'action':'send_code','email':email})
    if mail.called:
        payload['emailCode' if is_json else 'email_code']=re.search(r'\d{6}',mail.call_args.args[1]).group()
    return client.post(url,json.dumps(payload) if is_json else payload,**kwargs)
