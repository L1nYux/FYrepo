import csv
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import MemberProfile, Project
from .forms import SamplingRunForm
from .models import CandidatePaper, SamplingArtifact, SamplingDocument, SamplingRun
from .documents import document_bundle, process_next_document, store_pdf, store_upload
from .services import (SamplingError, build_frame, collection_config, freeze_readiness, freeze_run,
                       import_result_bundle, ingest_records, update_review_decisions)

User = get_user_model()


def text_pdf(text=True):
    """生成有效文字层 PDF，仅用于验证转换器，不向正式数据库预置数据。"""
    content = b'BT /F1 12 Tf 30 730 Td '
    if text:
        for line in [b'Abstract: Legal research examines evidence and reproducible analysis.'] * 8:
            content += b'(' + line + b') Tj 0 -20 Td '
    content += b'ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    result = b'%PDF-1.4\n'; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result)); result += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    pos = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n' + b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])
    return result + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{pos}\n%%EOF'.encode()


class ProductionBase(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.temp.name)
        self.settings_override.enable(); self.addCleanup(self.settings_override.disable)
        self.user = User.objects.create_user('production-owner', password='verification-only')
        self.project = Project.objects.create(name='原有项目', goal='研究', owner=self.user, created_by=self.user)
        self.client.force_login(self.user)

    def payload(self, **extra):
        return {'name':'自由命名样本集', 'project':'', 'version':'v1', 'periods':['P3'],
                'selected_tiers':['T1'], 'selected_journals':['中国法学'], 'main_n':'1','reserve_n':'1',
                'sampling_method':'hash_issue_balanced','sampling_seed':'review-seed', **extra}

    def make_run(self, **extra):
        form = SamplingRunForm(self.payload(**extra), user=self.user)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        run = form.save(commit=False); run.created_by=self.user; run.save(); return run

    def records(self):
        return [{'title':f'证据研究{i}', 'authors':'作者', 'journal':'中国法学','year':'2024','issue':f'{i:02}',
                 'url':f'https://kns.cnki.net/kcms/detail/detail.aspx?dbcode=CJFD&filename=LAW{i}'} for i in range(1,5)]

    def frozen(self, **extra):
        run = self.make_run(**extra); ingest_records(run, self.records()); freeze_run(run); run.refresh_from_db(); return run


class ScopeFlowTests(ProductionBase):
    def test_empty_and_name_only_posts_are_bound_field_errors(self):
        for data in ({}, {'name':'保留这个名称'}):
            with self.subTest(data=data):
                response = self.client.post(reverse('sampling:new'), data)
                self.assertEqual(response.status_code, 200)
                form = response.context['scope_form']
                for field in ('periods','selected_tiers','selected_journals','main_n','reserve_n'):
                    self.assertIn(field, form.errors)
                self.assertTrue(response.context['drawer_open'])
                self.assertContains(response, 'sampling-required')
                if data: self.assertEqual(form['name'].value(), data['name'])
        self.assertEqual(SamplingRun.objects.count(), 0)

    def test_optional_project_and_existing_project_fk(self):
        for project in ('', str(self.project.pk)):
            response = self.client.post(reverse('sampling:new'), self.payload(project=project))
            self.assertEqual(response.status_code, 302)
            run = SamplingRun.objects.latest('pk')
            self.assertEqual(run.project_id, self.project.pk if project else None)
            detail = self.client.get(response.url)
            self.assertContains(detail, run.name)
            self.assertContains(detail, self.project.name if project else '独立样本集')
            self.assertFalse(detail.context['drawer_open'])

    def test_real_project_tree_and_single_primary_entry(self):
        response = self.client.get(reverse('sampling:new'))
        form = response.context['scope_form']
        self.assertIn(self.project, form.fields['project'].queryset)
        self.assertContains(response, 'href="/sampling/"', count=1)
        self.assertContains(response, self.project.name)
        self.assertContains(response, 'data-sampling-drawer')
        self.assertNotContains(response, 'Preview')

    def test_periods_invalid_missing_never_raise_modelform_valueerror(self):
        for periods in ([], ['unknown']):
            response = self.client.post(reverse('sampling:new'), self.payload(periods=periods))
            self.assertEqual(response.status_code, 200)
            self.assertIn('periods', response.context['scope_form'].errors)
        # v1 旧表单也进入同一规范化路径。
        data=self.payload(); data['period_ids']=data.pop('periods')
        self.assertTrue(SamplingRunForm(data, user=self.user).is_valid())

    def test_holdout_conditional_required_and_year_order(self):
        self.assertTrue(SamplingRunForm(self.payload(holdout_start='bad'),user=self.user).is_valid())
        self.assertTrue(SamplingRunForm(self.payload(holdout_enabled='false'),user=self.user).is_valid())
        for extra, fields in [({'holdout_enabled':'on'}, ('holdout_n','holdout_start','holdout_end')),
                              ({'holdout_enabled':'on','holdout_n':'1','holdout_start':'2028','holdout_end':'2027'}, ('holdout_end',)),
                              ({'holdout_enabled':'on','holdout_n':'1','holdout_start':'2024','holdout_end':'2025'}, ('holdout_start',))]:
            response=self.client.post(reverse('sampling:new'),self.payload(**extra))
            self.assertEqual(response.status_code,200)
            for f in fields: self.assertIn(f,response.context['scope_form'].errors)

    def test_invalid_numbers_and_project(self):
        for values, field in [({'main_n':'0'},'main_n'),({'reserve_n':'-1'},'reserve_n'),
                              ({'main_n':'1.5'},'main_n'),({'project':'99999'},'project')]:
            form=SamplingRunForm(self.payload(**values),user=self.user)
            self.assertFalse(form.is_valid()); self.assertIn(field,form.errors)
        self.project.archived_at=timezone.now(); self.project.save()
        self.assertFalse(SamplingRunForm(self.payload(project=str(self.project.pk)),user=self.user).is_valid())

    def test_edit_refills_and_invalid_save_retains_values(self):
        run=self.make_run()
        response=self.client.get(reverse('sampling:edit',args=[run.pk]))
        self.assertEqual(response.context['scope_form']['periods'].value(),['P3'])
        self.assertEqual(response.context['scope_form']['name'].value(),run.name)
        response=self.client.post(reverse('sampling:edit',args=[run.pk]),self.payload(name='修改但未保存',periods=[]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['scope_form']['name'].value(),'修改但未保存')
        run.refresh_from_db(); self.assertNotEqual(run.name,'修改但未保存')

    def test_collection_pool_kept_on_parameter_change_and_stale_job_rejected(self):
        run=self.make_run(); ingest_records(run,self.records()); old=collection_config(run)['scope_signature']
        self.client.post(reverse('sampling:edit',args=[run.pk]),self.payload(main_n='2'))
        self.assertEqual(run.candidates.count(),4)
        response=self.client.post(reverse('sampling:agent_import',args=[run.pk]),
            json.dumps({'records':self.records(),'scope_signature':old}),content_type='application/json')
        self.assertEqual(response.status_code,409)

    def test_period_specific_tier_override(self):
        run=self.make_run(periods=['P1'],selected_tiers=['T4'],selected_journals=['法律适用'])
        self.assertEqual(build_frame(run)[0]['tier'],'T4')
        form=SamplingRunForm(self.payload(periods=['P1'],selected_tiers=['T3'],selected_journals=['法律适用']),user=self.user)
        self.assertFalse(form.is_valid()); self.assertIn('selected_journals',form.errors)


class FreezeIntegrityTests(ProductionBase):
    def test_readiness_shortage_and_unresolved_review(self):
        run=self.make_run(); self.assertFalse(freeze_readiness(run)['ready'])
        ingest_records(run,[{'title':'法治圆桌','journal':'中国法学','year':'2024'}])
        self.assertFalse(freeze_readiness(run)['ready'])
        with self.assertRaises(SamplingError): freeze_run(run)
        update_review_decisions(run,[run.candidates.get().pk],'include')
        self.assertTrue(freeze_readiness(run)['ready'])

    def test_freeze_immutable_clone_and_stored_registry_snapshot(self):
        run=self.frozen()
        with patch('sampling.services.REGISTRY', {'tiers':{}}):
            self.assertEqual(build_frame(run),run.protocol['frame_snapshot'])
        run.main_n=2
        with self.assertRaises(ValidationError): run.save()
        response=self.client.post(reverse('sampling:clone',args=[run.pk]))
        self.assertEqual(response.status_code,302)
        clone=SamplingRun.objects.latest('pk')
        self.assertEqual(clone.source_run_id,run.pk); self.assertFalse(clone.is_frozen)
        self.assertEqual(clone.version,'v2'); self.assertEqual(clone.candidates.count(),0)
        self.assertEqual(self.client.post(reverse('sampling:edit',args=[run.pk]),self.payload()).status_code,302)
        run.refresh_from_db(); self.assertEqual(run.main_n,1)

    def test_import_repeated_uncertain_preserves_manual_decision(self):
        run=self.make_run(); records=[{'title':'法治圆桌','journal':'中国法学','year':'2024'}]
        ingest_records(run,records); update_review_decisions(run,[run.candidates.get().pk],'exclude')
        ingest_records(run,records); self.assertEqual(run.candidates.get().decision,'exclude')

    def test_upstream_algorithms_match_selected_keys_hashes_roles(self):
        sys.path.insert(0,str(settings.BASE_DIR / 'vendor/sample_llm'))
        try:
            import pandas as pd
            from sampling_core.sampler import sample
            for method in ('hash_simple','hash_issue_balanced'):
                run=self.frozen(sampling_method=method)
                registry=pd.DataFrame(list(run.candidates.values()))
                primary,reserves,_,_=sample(registry,pd.DataFrame(build_frame(run)),seed=run.sampling_seed,method=method)
                expected={(r['paper_id'],r['candidate_key'],r['draw_hash']) for r in primary.to_dict('records')+reserves.to_dict('records')}
                actual=set(run.candidates.exclude(paper_id='').values_list('paper_id','candidate_key','draw_hash'))
                self.assertEqual(actual,expected)
        finally: sys.path.pop(0)

    def test_experiment_uses_existing_model_once(self):
        run=self.frozen()
        for _ in range(2): self.assertEqual(self.client.post(reverse('sampling:create_experiment',args=[run.pk])).status_code,302)
        self.assertEqual(run.experiment_links.count(),1)
        experiment=run.experiment_links.get().experiment
        self.assertIsNone(experiment.project_id); self.assertIn(run.run_fingerprint,experiment.purpose)

    def test_permissions_follow_workbench_roles(self):
        run=self.make_run()
        other=User.objects.create_user('other-developer'); self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('sampling:detail',args=[run.pk])).status_code,200)
        self.assertEqual(self.client.post(reverse('sampling:edit',args=[run.pk]),self.payload()).status_code,403)
        MemberProfile.objects.create(user=other,tier=MemberProfile.NORMAL)
        response=self.client.get(reverse('sampling:index'))
        self.assertRedirects(response,reverse('showcase'),fetch_redirect_response=False)

    def test_frozen_pool_rejects_all_ingest_and_review(self):
        run=self.frozen()
        with self.assertRaises(SamplingError): ingest_records(run,self.records())
        with self.assertRaises(SamplingError): update_review_decisions(run,[],'include')

    def test_admin_cannot_overwrite_frozen_run_or_candidate(self):
        run=self.frozen(); paper=run.candidates.get(paper_id='P001')
        self.user.is_staff=True;self.user.is_superuser=True;self.user.save()
        for name, pk in (('samplingrun',run.pk),('candidatepaper',paper.pk)):
            url=reverse(f'admin:sampling_{name}_change',args=[pk])
            self.assertEqual(self.client.get(url).status_code,200)
            self.assertEqual(self.client.post(url,{'name':'覆盖','title':'覆盖'}).status_code,403)


class ResultPackageTests(ProductionBase):
    def bundle(self):
        run=self.frozen()
        artifact=run.artifacts.get(artifact_type=SamplingArtifact.TYPE_BUNDLE)
        with artifact.file.open('rb') as f: return run,f.read()

    def test_verified_roundtrip_with_optional_project(self):
        run,data=self.bundle()
        imported=import_result_bundle(None,SimpleUploadedFile('正式包.zip',data),self.user)
        self.assertEqual(imported.run_fingerprint,run.run_fingerprint)
        self.assertEqual(imported.candidates.count(),run.candidates.count())
        self.assertEqual(build_frame(imported),build_frame(run))
        self.assertEqual(imported.artifacts.get(artifact_type='frame').original_name,'sampling_frame.csv')

    def test_zero_reserve_bundle_roundtrip(self):
        run=self.frozen(reserve_n='0')
        with run.artifacts.get(artifact_type='bundle').file.open('rb') as source:
            imported=import_result_bundle(None,SimpleUploadedFile('zero-reserve.zip',source.read()),self.user)
        self.assertEqual(imported.reserve_n,0)
        self.assertEqual(imported.candidates.filter(sample_role='RESERVE').count(),0)

    def test_native_upstream_bundle_csv_hash_and_holdout_roundtrip(self):
        sys.path.insert(0,str(settings.BASE_DIR / 'vendor/sample_llm'))
        try:
            import pandas as pd
            from sampling_core.exporter import make_bundle
            from sampling_core.sampler import sample
            run=self.make_run(holdout_enabled='on',holdout_n='1',holdout_start='2026',holdout_end='2026')
            ingest_records(run,self.records()+[{**r,'year':'2026','url':r['url']+'H'} for r in self.records()])
            registry=pd.DataFrame(list(run.candidates.values()))
            frame=pd.DataFrame(build_frame(run))
            primary,reserve,issues,audit=sample(registry,frame,seed=run.sampling_seed,method=run.sampling_method)
            path=Path(self.temp.name)/'upstream.zip'
            make_bundle(frame,registry,primary,reserve,issues,path,audit=audit,
                        protocol={'method':run.sampling_method,'seed':run.sampling_seed})
            imported=import_result_bundle(None,SimpleUploadedFile('upstream.zip',path.read_bytes()),self.user)
            self.assertTrue(imported.holdout_enabled);self.assertEqual(imported.holdout_start,2026)
            self.assertTrue(imported.candidates.filter(paper_id='H001').exists())
        finally:sys.path.pop(0)

    def test_modified_registry_and_selected_table_are_rejected_atomically(self):
        _,data=self.bundle()
        for file in ('candidate_registry.csv','selected_samples.csv','sampling_ranking_full.csv','sampling_certificate.csv'):
            with self.subTest(file=file):
                payload=io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(data)) as original,zipfile.ZipFile(payload,'w') as target:
                    for name in original.namelist():
                        content=original.read(name)
                        if name==file: content=content.replace('证据研究'.encode(), '改写研究'.encode()) if file.startswith('candidate') else content.replace(b'P001',b'P999')
                        target.writestr(name,content)
                count=SamplingRun.objects.count()
                with self.assertRaises(SamplingError): import_result_bundle(None,SimpleUploadedFile('changed.zip',payload.getvalue()),self.user)
                self.assertEqual(SamplingRun.objects.count(),count)

    def test_missing_protocol_and_invalid_zip_return_business_error(self):
        for data in (b'bad',b'PK\x03\x04'):
            response=self.client.post(reverse('sampling:bundle_import'),{'version':'v1','file':SimpleUploadedFile('invalid.zip',data)})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context['bundle_form'].errors)


class DocumentPipelineTests(ProductionBase):
    def test_real_pdf_worker_name_hashes_mapping_and_download(self):
        run=self.frozen(); paper=run.candidates.get(paper_id='P001')
        doc,created=store_pdf(run,'P001','原论文.pdf',text_pdf(),self.user)
        self.assertTrue(created); self.assertEqual(doc.status,'queued')
        same,created=store_pdf(run,'P001','原论文.pdf',text_pdf(),self.user)
        self.assertFalse(created); self.assertEqual(same.pk,doc.pk)
        result=process_next_document()
        self.assertIn(result.status,('ready','review')); self.assertGreater(result.characters,100)
        self.assertEqual(result.original_name,'原论文.pdf'); self.assertEqual(len(result.md_sha256),64)
        with result.md_file.open('rb') as f: markdown=f.read().decode()
        self.assertIn('原论文.pdf',markdown); self.assertIn('P001',markdown)
        self.assertIn('Legal research',markdown)
        response=self.client.get(reverse('sampling:document_download',args=[run.pk,doc.pk,'md']))
        self.assertEqual(response.status_code,200); response.close()
        with zipfile.ZipFile(io.BytesIO(document_bundle(run))) as package:
            self.assertIn('markdown/P001.md',package.namelist())
            self.assertIn('原论文.pdf',package.read('pdf_md_manifest.csv').decode('utf-8-sig'))
        self.assertIsNone(process_next_document())

    def test_scanned_or_corrupt_pdf_never_returns_fake_markdown(self):
        for data in (text_pdf(False),b'%PDF-invalid'):
            run=self.frozen(); doc,_=store_pdf(run,'P001','扫描.pdf',data,self.user)
            result=process_next_document(); self.assertEqual(result.status,'failed'); self.assertFalse(result.md_file)
            self.assertTrue(result.error)

    def test_upload_requires_matching_frozen_id_and_pdf(self):
        run=self.frozen()
        for pid,name,data in [('P999','x.pdf',text_pdf()),('P001','x.caj',text_pdf()),('P001','x.pdf',b'<html>permission</html>')]:
            response=self.client.post(reverse('sampling:document_upload',args=[run.pk]),
                {'paper_id':pid,'file':SimpleUploadedFile(name,data)},HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code,400)
        self.assertEqual(SamplingDocument.objects.count(),0)
        draft=self.make_run()
        with self.assertRaises(SamplingError): store_pdf(draft,'P001','x.pdf',text_pdf(),self.user)

    def test_zip_mapping_validated_before_any_write(self):
        run=self.frozen()
        for invalid in (False,True):
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as archive:
                archive.writestr('pdf_manifest.csv', 'paper_id,source_pdf\nP001,论文原名.pdf\n'+('P999,不存在.pdf\n' if invalid else ''))
                archive.writestr('论文原名.pdf',text_pdf())
            if invalid:
                with self.assertRaises(SamplingError): store_upload(run,SimpleUploadedFile('files.zip',data.getvalue()),'',self.user)
                self.assertEqual(SamplingDocument.objects.count(),0)
            else:
                docs,count=store_upload(run,SimpleUploadedFile('files.zip',data.getvalue()),'',self.user)
                self.assertEqual(count,1); self.assertEqual(docs[0].original_name,'论文原名.pdf')
                docs[0].delete()

    def test_report_alone_does_not_claim_pdf_received(self):
        run=self.frozen()
        response=self.client.post(reverse('sampling:agent_pdf_report',args=[run.pk]),json.dumps({'records':[{'paper_id':'P001','status':'downloaded'}]}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(run.candidates.get(paper_id='P001').pdf_status,'本机已下载，等待上传')
        self.assertEqual(SamplingDocument.objects.count(),0)
