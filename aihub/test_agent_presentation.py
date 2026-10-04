from django.test import SimpleTestCase
from .agent import model_data, SYSTEM

class PresentationPromptTests(SimpleTestCase):
    def test_internal_source_urls_stay_out_of_model_context(self):
        original={'source':{'kind':'project','id':2,'title':'项目','url':'/projects/2/'},'nested':[{'url':'/tasks/5/','title':'任务'}],'source_url':'https://research.example/paper'}
        value=model_data(original)
        self.assertNotIn('url',value['source']);self.assertNotIn('url',value['nested'][0])
        self.assertEqual(value['source_url'],'https://research.example/paper')
        self.assertEqual(original['source']['url'],'/projects/2/')

    def test_chat_capability_does_not_confuse_background_overview_with_messages(self):
        self.assertIn('不等于聊天记录',SYSTEM);self.assertIn('调用搜索和读取工具',SYSTEM)
        self.assertIn('不输出工作台内部路径',SYSTEM)
