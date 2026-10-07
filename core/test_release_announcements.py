import os
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, SimpleTestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .releases import bundled,validate,publish,sync
from .models import ApplicationRelease

class ReleaseAnnouncementTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('release-member');self.client.force_login(self.user)
    def test_system_release_is_published_once(self):
        info=bundled();first,created=publish(info);self.assertTrue(created)
        second,created=publish(info);self.assertFalse(created);self.assertEqual(first.pk,second.pk);self.assertEqual(ApplicationRelease.objects.count(),1)
    def test_size_metadata_can_be_enriched_without_reposting(self):
        info=bundled();item,_=publish(info);info['installers']={'win-x64':{'name':'ResearchWorkbench-'+info['version']+'-win-x64.exe','size':123456}}
        other,created=publish(info);self.assertFalse(created);self.assertEqual(item.pk,other.pk);self.assertEqual(other.release_data['installers']['win-x64']['size'],123456)
    def test_release_actions_exist_in_list_and_reference_detail(self):
        item,_=publish(bundled())
        for url in [reverse('application_updates'),reverse('application_update_detail',args=[item.pk])]:
            response=self.client.get(url);self.assertContains(response,'data-release-update');self.assertContains(response,'data-release-feature')
        target=os.environ.get('WORKBENCH_CAPTURE_UI')
        if target:
            folder=Path(target);folder.mkdir(parents=True,exist_ok=True);(folder/'release-announcement.html').write_bytes(self.client.get(reverse('application_updates')).content)
    def test_offline_sync_preserves_existing_announcements(self):
        with patch('core.releases.latest',side_effect=OSError('offline')):sync(True)
        self.assertEqual(ApplicationRelease.objects.count(),1)
    def test_release_endpoint_requires_login(self):
        self.client.logout();self.assertEqual(self.client.get(reverse('release_current')).status_code,302)

class ReleaseMetadataTests(SimpleTestCase):
    def test_features_cannot_redirect_to_external_or_privileged_routes(self):
        self.assertTrue({'/discover/talents/','/discover/offers/','/messages/social/','/assistant/'} <= {item['path'] for item in bundled()['features']})
        info=bundled();info['features']=[{'title':'Bad','path':'https://evil.example/'},{'title':'Bad','path':'/admin/'},{'title':'Valid','path':'/assistant/'}]
        self.assertEqual(len(validate(info)['features']),1)
    def test_version_rejects_path_or_prerelease(self):
        for v in ['../0.2.12','v0.2.12','0.2.12-beta']:
            with self.assertRaises(ValueError):validate({'version':v})
