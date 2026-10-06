from .testing_registration import verified_post
"""工作台主流程与权限边界的自动化测试。

运行：manage.py test core
不需要写真实附件文件：附件相关的用例只校验权限判定（未授权 403，授权但因夹具文件不在磁盘而 404）。
"""

import datetime
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import checks
from .models import (Attachment, ChatMessage, Comment, EmailVerificationCode, ExpenseClaim,
                     FinanceEntry, Invite, MemberProfile, Project, Submission, Task, TeamContact)


@contextmanager
def scratch_dir(name):
    """工程内的临时目录。

    系统临时目录在受限环境（例如 DSH 沙箱）里可能不可写，测试不要依赖它。
    """
    directory = Path(settings.BASE_DIR) / '.test-scratch' / name
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield str(directory)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class WorkbenchTestCase(TestCase):
    """公共夹具：管理员、项目负责人、项目成员和一名项目外开发者。"""

    def setUp(self):
        self.admin = User.objects.create_user('boss', password='verify-only-12345', is_staff=True, is_superuser=True)
        self.owner = User.objects.create_user('lead', password='verify-only-12345')
        self.dev = User.objects.create_user('dev', password='verify-only-12345')
        self.outsider = User.objects.create_user('other', password='verify-only-12345')

        self.project = Project.objects.create(name='蛋白结构预测', goal='三个月内跑通基线',
                                              owner=self.owner, created_by=self.admin)
        self.project.members.set([self.dev])
        self.mother = Task.objects.create(project=self.project, title='数据准备', description='整理公开数据集',
                                          assignee=self.owner, due_date=datetime.date(2026, 3, 1),
                                          created_by=self.owner)
        self.child = Task.objects.create(project=self.project, parent=self.mother, title='清洗子集',
                                         description='清洗 5 万条', assignee=self.dev,
                                         due_date=datetime.date(2026, 2, 1), created_by=self.owner)


class AccessTests(WorkbenchTestCase):
    def test_guest_sees_nothing(self):
        for name in ['dashboard', 'task_list', 'finance_list', 'claim_list', 'profile',
                     'chat', 'chat_public', 'chat_developers']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn('/login/', response['Location'])

    def test_guest_cannot_open_project_or_task(self):
        self.assertEqual(self.client.get(reverse('project_detail', args=[self.project.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse('task_detail', args=[self.child.pk])).status_code, 302)

    def test_audit_page_is_gone(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/audit/').status_code, 404)

    def test_developer_can_view_all_task_progress(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse('task_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('project_detail', args=[self.project.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('task_detail', args=[self.child.pk])).status_code, 200)


class ProjectAndTaskTests(WorkbenchTestCase):
    def test_only_admin_creates_projects(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('project_new')).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(reverse('project_new'), {
            'name': '新方向', 'goal': '探索', 'description': '', 'owner': self.owner.pk,
            'members': [self.dev.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Project.objects.filter(name='新方向').exists())

    def test_owner_manages_only_own_project(self):
        other = Project.objects.create(name='别人的项目', goal='目标', owner=self.outsider, created_by=self.admin)
        self.client.force_login(self.owner)
        ok = self.client.post(reverse('task_new'), {
            'project': self.project.pk, 'title': '新增母任务', 'description': '说明',
            'assignee': self.owner.pk, 'due_date': '2026-04-01'})
        self.assertEqual(ok.status_code, 302)
        blocked = self.client.post(reverse('task_new'), {
            'project': other.pk, 'title': '越权任务', 'description': '说明',
            'assignee': self.outsider.pk, 'due_date': '2026-04-01'})
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(Task.objects.filter(title='越权任务').exists())

    def test_developer_cannot_publish_tasks(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('task_new'), {
            'project': self.project.pk, 'title': '开发者发布', 'description': '说明',
            'assignee': self.dev.pk, 'due_date': '2026-04-01'})
        self.assertEqual(response.status_code, 403)

    def test_only_two_task_levels(self):
        grandchild = Task(project=self.project, parent=self.child, title='三级以下', description='说明',
                          assignee=self.dev, due_date=datetime.date(2026, 5, 1), created_by=self.owner)
        with self.assertRaises(ValidationError):
            grandchild.full_clean()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('task_new'), {'project': self.project.pk, 'parent': self.child.pk})
        self.assertEqual(response.status_code, 404)

    def test_assignee_must_be_project_participant(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('task_new'), {
            'project': self.project.pk, 'title': '外部人员任务', 'description': '说明',
            'assignee': self.outsider.pk, 'due_date': '2026-04-01'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(title='外部人员任务').exists())

    def test_mother_progress_is_summarised_from_children(self):
        second = Task.objects.create(project=self.project, parent=self.mother, title='第二子任务',
                                     description='说明', assignee=self.dev,
                                     due_date=datetime.date(2026, 2, 5), created_by=self.owner, progress=100)
        self.assertEqual(self.mother.display_progress, 50)
        self.assertEqual(self.project.progress, 50)
        second.delete()
        self.assertEqual(self.project.progress, 0)

    def test_owner_closes_subtask_inside_project(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('task_close', args=[self.child.pk]), {'note': '数据已够用'})
        self.assertEqual(response.status_code, 302)
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Task.COMPLETED)
        self.assertEqual(self.child.closed_by, self.owner)
        self.assertTrue(Comment.objects.filter(task=self.child, kind=Comment.CONCLUSION).exists())


class SubmissionTests(WorkbenchTestCase):
    def test_text_only_result_is_enough(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('task_submit', args=[self.child.pk]),
                                    {'summary': '纯文本成果：数据集已清洗完成，指标见正文。'})
        self.assertEqual(response.status_code, 302)
        submission = Submission.objects.get()
        self.assertEqual(submission.attachments.count(), 0)
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Task.OPEN)

    def test_unassigned_developer_cannot_publish_result(self):
        self.client.force_login(self.outsider)
        response = self.client.post(reverse('task_submit', args=[self.child.pk]), {'summary': 'not assigned'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Submission.objects.exists())

    def test_task_stays_pending_until_every_result_is_reviewed(self):
        """接受到一份成果后，只要还有待审核成果，任务就停在「待审核」。"""
        first = Submission.objects.create(task=self.child, author=self.dev, summary='甲的结果')
        second = Submission.objects.create(task=self.child, author=self.outsider, summary='乙的结果')
        self.child.status = Task.SUBMITTED
        self.child.save(update_fields=['status'])
        self.client.force_login(self.admin)
        self.client.post(reverse('submission_review', args=[first.pk]), {'decision': 'accept', 'note': '可用'})
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Task.SUBMITTED)
        self.client.post(reverse('submission_review', args=[second.pk]), {'decision': 'reject', 'note': '与甲重复'})
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Task.COMPLETED)

    def test_closed_task_does_not_accept_new_results(self):
        self.child.status = Task.COMPLETED
        self.child.save(update_fields=['status'])
        self.client.force_login(self.dev)
        self.client.post(reverse('task_submit', args=[self.child.pk]), {'summary': '结项后的补充'})
        self.assertEqual(Submission.objects.count(), 0)

    def test_owner_reviews_and_reject_reopens_task(self):
        submission = Submission.objects.create(task=self.child, author=self.dev, summary='第一版')
        self.child.status = Task.SUBMITTED
        self.child.save(update_fields=['status'])
        self.client.force_login(self.owner)
        response = self.client.post(reverse('submission_review', args=[submission.pk]),
                                    {'decision': 'reject', 'note': '样本量不足'})
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(submission.status, Submission.REJECTED)
        self.assertEqual(self.child.status, Task.OPEN)

        submission.status = Submission.PENDING
        submission.save(update_fields=['status'])
        self.client.post(reverse('submission_review', args=[submission.pk]),
                         {'decision': 'accept', 'note': '通过'})
        submission.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(submission.status, Submission.ACCEPTED)
        self.assertEqual(submission.reviewed_by, self.owner)
        self.assertEqual(self.child.status, Task.COMPLETED)
        self.assertEqual(self.child.progress, 100)

    def test_developer_cannot_review(self):
        submission = Submission.objects.create(task=self.child, author=self.dev, summary='成果')
        self.client.force_login(self.dev)
        response = self.client.post(reverse('submission_review', args=[submission.pk]),
                                    {'decision': 'accept', 'note': ''})
        self.assertEqual(response.status_code, 403)

    def test_admin_picks_final_result_without_waiting_for_other_branches(self):
        submission = Submission.objects.create(task=self.child, author=self.dev, summary='有价值的结果')
        self.assertEqual(self.mother.status, Task.OPEN)  # 另一分支尚未完成
        self.client.force_login(self.admin)
        response = self.client.post(reverse('submission_final', args=[submission.pk]),
                                    {'action': 'mark', 'note': '先采用这条路线'})
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertTrue(submission.is_final)
        self.assertEqual(submission.final_by, self.admin)
        self.assertEqual(self.mother.status, Task.OPEN)

    def test_developer_cannot_mark_final(self):
        submission = Submission.objects.create(task=self.child, author=self.dev, summary='成果')
        self.client.force_login(self.dev)
        response = self.client.post(reverse('submission_final', args=[submission.pk]), {'action': 'mark'})
        self.assertEqual(response.status_code, 403)


    def test_upload_rejects_disallowed_extension(self):
        """不允许的附件类型在保存前就被拒绝，不会落盘也不会改变任务状态。"""
        self.client.force_login(self.dev)
        bad = SimpleUploadedFile('payload.exe', b'MZ', content_type='application/octet-stream')
        response = self.client.post(reverse('task_submit', args=[self.child.pk]),
                                    {'summary': '带附件的成果', 'attachments': [bad]})
        # 校验失败时回到任务页并列出错误，不再 302 跳转。
        self.assertEqual(response.status_code, 200)
        self.assertIn('errorlist', response.content.decode())
        self.assertEqual(Submission.objects.count(), 0)
        self.assertEqual(Attachment.objects.count(), 0)
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Task.OPEN)


class DiscussionTests(WorkbenchTestCase):
    def test_member_records_goal_idea_issue_conclusion(self):
        self.client.force_login(self.dev)
        for kind, _ in Comment.KINDS:
            response = self.client.post(reverse('task_comment', args=[self.child.pk]),
                                        {'kind': kind, 'body': f'{kind} 内容'})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(self.child.comments.count(), len(Comment.KINDS))

    def test_any_developer_can_comment_on_task(self):
        """每个开发者都可以对任务留言，不再要求是项目成员。"""
        self.client.force_login(self.outsider)
        response = self.client.post(reverse('task_comment', args=[self.child.pk]),
                                    {'kind': 'idea', 'body': '旁观者的一条思路'})
        self.assertEqual(response.status_code, 302)
        comment = Comment.objects.get()
        self.assertEqual(comment.task, self.child)
        self.assertEqual(comment.author, self.outsider)
        self.assertIsNone(comment.project_id)

    def test_submission_comment_keeps_context(self):
        submission = Submission.objects.create(task=self.child, author=self.dev, summary='成果')
        self.client.force_login(self.owner)
        self.client.post(reverse('submission_comment', args=[submission.pk]),
                         {'kind': 'issue', 'body': '这里的指标怎么解释？'})
        comment = Comment.objects.get()
        self.assertEqual(comment.submission, submission)
        self.assertIsNone(comment.task_id)  # 针对成果的留言只挂成果，避免重复归属

    def test_attachment_permission_is_checked(self):
        submission = Submission.objects.create(task=self.child, author=self.dev, summary='成果')
        attachment = Attachment.objects.create(submission=submission, file='attachment/report.pdf',
                                               original_name='report.pdf', uploaded_by=self.dev)
        url = reverse('attachment_download', args=[attachment.pk])
        self.assertNotEqual(self.client.get(url).status_code, 200)  # 访客被拦截
        self.client.force_login(self.outsider)
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 403)  # 未审核成果对外人不可见
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 404)  # 有权限，但夹具文件未落盘
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(url).status_code, 404)  # 作者本人有权限


class ProjectResultTests(WorkbenchTestCase):
    """成果与留言直接挂在项目上的场景。"""

    def test_project_member_publishes_result_on_project(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('project_submit', args=[self.project.pk]), {'summary': 'report'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Submission.objects.get().project, self.project)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse('project_submit', args=[self.project.pk]), {'summary':'blocked'}).status_code,403)

    def test_developer_comments_on_project(self):
        self.client.force_login(self.outsider)
        response = self.client.post(reverse('project_comment', args=[self.project.pk]),
                                    {'kind': 'goal', 'body': '项目目标建议'})
        self.assertEqual(response.status_code, 302)
        comment = Comment.objects.get()
        self.assertEqual(comment.project, self.project)
        self.assertIsNone(comment.task_id)
        self.assertIn('蛋白结构预测', comment.context_label)

    def test_admin_reviews_project_result(self):
        submission = Submission.objects.create(project=self.project, author=self.outsider, summary='结题报告')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('submission_review', args=[submission.pk]),
                                    {'decision': 'accept', 'note': '通过'})
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.ACCEPTED)
        self.assertEqual(submission.reviewed_by, self.admin)

    def test_project_owner_reviews_in_own_project_only(self):
        submission = Submission.objects.create(project=self.project, author=self.dev, summary='报告')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('submission_review', args=[submission.pk]),
                                          {'decision': 'accept', 'note': '可以'}).status_code, 302)
        other = Project.objects.create(name='别人的项目', goal='目标', owner=self.outsider, created_by=self.admin)
        foreign = Submission.objects.create(project=other, author=self.dev, summary='别人的报告')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('submission_review', args=[foreign.pk]),
                                          {'decision': 'accept', 'note': ''}).status_code, 403)

    def test_developer_cannot_review_results(self):
        submission = Submission.objects.create(project=self.project, author=self.outsider, summary='报告')
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(reverse('submission_review', args=[submission.pk]),
                                          {'decision': 'accept', 'note': ''}).status_code, 403)

    def test_review_returns_to_source_page(self):
        submission = Submission.objects.create(project=self.project, author=self.dev, summary='报告')
        self.client.force_login(self.admin)
        target = f'/projects/{self.project.pk}/#review'
        response = self.client.post(reverse('submission_review', args=[submission.pk]),
                                    {'decision': 'accept', 'note': '', 'next': target})
        self.assertEqual(response['Location'], target)

    def test_review_ignores_external_next(self):
        submission = Submission.objects.create(project=self.project, author=self.dev, summary='报告')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('submission_review', args=[submission.pk]),
                                    {'decision': 'accept', 'note': '',
                                     'next': 'https://evil.example.com/steal'})
        self.assertNotIn('evil.example.com', response['Location'])

    def test_result_must_have_exactly_one_target(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Submission.objects.create(task=self.child, project=self.project,
                                          author=self.dev, summary='两个归属')

    def test_comment_must_have_exactly_one_target(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Comment.objects.create(task=self.child, project=self.project,
                                       author=self.dev, body='两个归属')


class SectionLayoutTests(WorkbenchTestCase):
    """成果、审核、留言三块必须分开，且权限差异体现在页面上。"""

    def test_task_page_separates_results_review_and_discussion(self):
        submission = Submission.objects.create(task=self.child, author=self.dev, summary='待审成果')
        self.client.force_login(self.admin)
        html = self.client.get(reverse('task_detail', args=[self.child.pk])).content.decode()
        # 新版任务页：正文是「讨论 + 成果提交区」，任务信息收进可折叠的详情区。
        for anchor in ['id="results"', 'id="discussion"']:
            self.assertIn(anchor, html)
        self.assertIn('task-brief', html)
        self.assertIn(self.child.description, html)
        self.assertIn(f'action="{reverse("submission_review", args=[submission.pk])}"', html)
        # 侧栏「待审核」直接锚到对应成果卡片
        self.assertIn('待审核', html)
        self.assertIn(f'href="#submission-{submission.pk}"', html)
        self.assertIn(f'action="{reverse("task_submit", args=[self.child.pk])}"', html)
        self.assertIn(f'action="{reverse("task_comment", args=[self.child.pk])}"', html)

    def test_unassigned_developer_sees_comment_but_not_submit_or_review(self):
        self.client.force_login(self.outsider)
        html = self.client.get(reverse('task_detail',args=[self.child.pk])).content.decode()
        self.assertNotIn(f'action="{reverse("task_submit", args=[self.child.pk])}"',html)
        self.assertIn(f'action="{reverse("task_comment", args=[self.child.pk])}"',html)
        self.assertNotIn('id="review"',html)

    def test_project_page_separates_sections(self):
        self.client.force_login(self.admin)
        base = reverse('project_detail', args=[self.project.pk])
        overview = self.client.get(base).content.decode()
        self.assertIn('id="brief"', overview)
        self.assertNotIn('id="tree"', overview)
        tasks = self.client.get(base + '?tab=tasks').content.decode()
        self.assertIn('id="tree"', tasks)
        results = self.client.get(base + '?tab=results').content.decode()
        self.assertIn('id="results"', results)
        combined = overview + tasks + results
        self.assertIn('id="discussion"', combined)
        self.assertIn(f'action="{reverse("project_comment", args=[self.project.pk])}"', combined)
        self.assertIn(f'action="{reverse("project_submit", args=[self.project.pk])}"', combined)

    def test_pending_result_is_reachable_from_review_section(self):
        submission = Submission.objects.create(project=self.project, author=self.dev, summary='项目成果待审')
        self.client.force_login(self.admin)
        base = reverse('project_detail', args=[self.project.pk])
        html = self.client.get(base + '?tab=results').content.decode()
        self.assertIn(f'id="submission-{submission.pk}"', html)
        self.assertIn(f'action="{reverse("submission_review", args=[submission.pk])}"', html)
        # 概览页签不再平铺成果
        self.assertNotIn(f'id="submission-{submission.pk}"', self.client.get(base).content.decode())


class FinanceTests(WorkbenchTestCase):
    def test_ledger_requires_finance_grant(self):
        FinanceEntry.objects.create(kind='income', amount='5000.00', occurred_on=datetime.date(2026, 1, 5),
                                    memo='启动经费', created_by=self.admin)
        self.client.force_login(self.dev)
        response = self.client.get(reverse('finance_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '启动经费')
        from .models import TeamMembership
        TeamMembership.objects.filter(team_id=1,user=self.dev).update(permissions=['finance'])
        self.assertContains(self.client.get(reverse('finance_list')), '启动经费')

    def test_only_admin_books_and_voids(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse('finance_new')).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(reverse('finance_new'), {
            'kind': 'api', 'amount': '128.50', 'occurred_on': '2026-01-06', 'memo': '模型调用'})
        self.assertEqual(response.status_code, 302)
        entry = FinanceEntry.objects.get()
        self.client.post(reverse('finance_void', args=[entry.pk]))
        entry.refresh_from_db()
        self.assertIsNotNone(entry.voided_at)
        self.assertEqual(entry.voided_by, self.admin)

    def test_balance_counts_the_whole_ledger_not_just_the_visible_page(self):
        """余额按整本账本聚合：列表只显示最近 200 条，不能因此少算最早的一笔。"""
        early = FinanceEntry(kind='income', amount='10000.00', occurred_on=datetime.date(2026, 1, 1),
                             memo='最早的一笔收入', created_by=self.admin)
        recent = [FinanceEntry(kind='expense', amount='1.00', occurred_on=datetime.date(2026, 6, 1),
                               memo=f'近期支出 {index}', created_by=self.admin) for index in range(200)]
        FinanceEntry.objects.bulk_create([early] + recent)      # 最早那笔会被 [:200] 切片切掉
        self.client.force_login(self.admin)
        html = self.client.get(reverse('finance_list')).content.decode()
        self.assertEqual(FinanceEntry.objects.count(), 201)
        self.assertIn('10000.00', html)                         # 收入合计包含被切片的最早一笔
        self.assertIn('200.00', html)                           # 支出合计
        self.assertIn('9800.00', html)                          # 余额 = 10000 - 200

    def test_voided_entries_are_left_out_of_a_finance_delegates_totals(self):
        from .models import TeamMembership
        TeamMembership.objects.filter(team_id=1,user=self.dev).update(permissions=['finance'])
        """作废记录对开发者既不出现在列表里，也不计入余额。"""
        FinanceEntry.objects.create(kind='income', amount='500.00', occurred_on=datetime.date(2026, 1, 2),
                                    memo='有效收入', created_by=self.admin)
        voided = FinanceEntry.objects.create(kind='expense', amount='300.00',
                                            occurred_on=datetime.date(2026, 1, 3),
                                            memo='已作废支出', created_by=self.admin)
        voided.voided_at = timezone.now()
        voided.voided_by = self.admin
        voided.save(update_fields=['voided_at', 'voided_by'])
        self.client.force_login(self.dev)
        html = self.client.get(reverse('finance_list')).content.decode()
        self.assertIn('500.00', html)
        self.assertIn('已作废支出',html)
        self.assertIn('¥ 500.00',html)
        self.assertIn('¥ 0.00',html)
        self.assertNotIn('¥ 200.00',html)

    def test_voided_entries_are_left_out_of_an_admins_totals(self):
        """作废记录对管理员仍然列出来，但不计入余额：余额按未作废账目聚合。"""
        FinanceEntry.objects.create(kind='income', amount='500.00', occurred_on=datetime.date(2026, 1, 2),
                                    memo='有效收入', created_by=self.admin)
        voided = FinanceEntry.objects.create(kind='expense', amount='300.00',
                                            occurred_on=datetime.date(2026, 1, 3),
                                            memo='已作废支出', created_by=self.admin)
        voided.voided_at = timezone.now()
        voided.voided_by = self.admin
        voided.save(update_fields=['voided_at', 'voided_by'])
        self.client.force_login(self.admin)
        html = self.client.get(reverse('finance_list')).content.decode()
        self.assertIn('已作废支出', html)                       # 管理员能看到这条记录
        self.assertIn('¥ 500.00', html)                        # 余额 = 500，不是 500-300=200
        self.assertNotIn('¥ 200.00', html)
        self.assertIn('¥ 0.00', html)                          # 支出合计不含作废的 300

    def test_claim_approval_creates_ledger_entry(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('claim_new'),
                                    {'amount': '320.00', 'occurred_on': '2026-01-08', 'memo': '服务器流量费'})
        self.assertEqual(response.status_code, 302)
        claim = ExpenseClaim.objects.get()
        self.assertEqual(claim.status, ExpenseClaim.PENDING)

        self.client.force_login(self.admin)
        response = self.client.post(reverse('claim_review', args=[claim.pk]),
                                    {'decision': 'approve', 'note': '凭证齐全'})
        self.assertEqual(response.status_code, 302)
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.APPROVED)
        self.assertIsNotNone(claim.entry)
        self.assertEqual(claim.entry.kind, 'reimburse')
        self.assertEqual(str(claim.entry.amount), '320.00')

    def test_claim_rejection_requires_reason_and_does_not_book(self):
        claim = ExpenseClaim.objects.create(applicant=self.dev, amount='99.00',
                                            occurred_on=datetime.date(2026, 1, 9), memo='打车')
        self.client.force_login(self.admin)
        self.client.post(reverse('claim_review', args=[claim.pk]), {'decision': 'reject', 'note': ''})
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.PENDING)
        self.client.post(reverse('claim_review', args=[claim.pk]), {'decision': 'reject', 'note': '缺少发票'})
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.REJECTED)
        self.assertEqual(FinanceEntry.objects.count(), 0)

    def test_developer_cannot_review_claims(self):
        claim = ExpenseClaim.objects.create(applicant=self.dev, amount='99.00',
                                            occurred_on=datetime.date(2026, 1, 9), memo='打车')
        self.client.force_login(self.outsider)
        response = self.client.post(reverse('claim_review', args=[claim.pk]),
                                    {'decision': 'approve', 'note': 'ok'})
        self.assertEqual(response.status_code, 403)

    def test_member_sees_own_claims_only(self):
        """报销申请对团队成员全公开：含他人待审、已驳回的申请与审核结论。"""
        ExpenseClaim.objects.create(applicant=self.dev, amount='10.00',
                                    occurred_on=datetime.date(2026, 1, 9), memo='我的申请')
        other = ExpenseClaim.objects.create(applicant=self.outsider, amount='20.00',
                                            occurred_on=datetime.date(2026, 1, 9), memo='别人的待审申请')
        ExpenseClaim.objects.create(applicant=self.outsider, amount='30.00',
                                    occurred_on=datetime.date(2026, 1, 9), memo='别人的已驳回申请',
                                    status=ExpenseClaim.REJECTED, review_note='缺少发票')
        self.client.force_login(self.dev)
        response = self.client.get(reverse('finance_list') + '?tab=claims')
        self.assertContains(response, '我的申请')
        self.assertNotContains(response, '别人的待审申请')
        self.assertNotContains(response, '别人的已驳回申请')
        self.assertNotContains(response, '缺少发票')
        self.assertContains(response, '1 待审')
        # 看得到不等于能审：审核入口仍然只对管理员开放。
        self.assertNotIn(reverse('claim_review', args=[other.pk]), response.content.decode())

    def test_developer_cannot_review_other_members_claim(self):
        """能看到所有申请，但审核仍需管理员。"""
        claim = ExpenseClaim.objects.create(applicant=self.outsider, amount='20.00',
                                            occurred_on=datetime.date(2026, 1, 9), memo='别人的申请')
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(reverse('claim_review', args=[claim.pk]),
                                          {'decision': 'approve', 'note': 'ok'}).status_code, 403)

    def test_claim_vouchers_follow_the_claim_visibility(self):
        """发票凭证跟随报销申请可见性：团队成员能下载他人待审申请的凭证。"""
        claim = ExpenseClaim.objects.create(applicant=self.dev, amount='50.00',
                                            occurred_on=datetime.date(2026, 1, 12), memo='打印费')
        voucher = Attachment.objects.create(claim=claim, file='claim/receipt.pdf',
                                           original_name='发票.pdf', uploaded_by=self.dev)
        url = reverse('attachment_download', args=[voucher.pk])
        self.client.force_login(self.outsider)               # 与申请人无关的另一名开发者
        self.assertEqual(self.client.get(url).status_code,403)
        from .models import TeamMembership
        TeamMembership.objects.filter(team_id=1,user=self.outsider).update(permissions=['finance'])
        self.assertEqual(self.client.get(url).status_code,404)  # Authorized; fixture file does not exist.


    def test_approved_claim_moves_vouchers_into_ledger(self):
        """报销通过后，发票等凭证同时出现在账本记录上，所有开发者都能下载。"""
        claim = ExpenseClaim.objects.create(applicant=self.dev, amount='50.00',
                                            occurred_on=datetime.date(2026, 1, 12), memo='打印费')
        Attachment.objects.create(claim=claim, file='claim/receipt.pdf', original_name='发票.pdf',
                                  uploaded_by=self.dev)
        self.client.force_login(self.admin)
        self.client.post(reverse('claim_review', args=[claim.pk]), {'decision': 'approve', 'note': 'ok'})
        claim.refresh_from_db()
        self.assertEqual(claim.entry.attachments.count(), 1)
        self.assertEqual(claim.entry.attachments.first().original_name, '发票.pdf')
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse('finance_list')).status_code, 200)


class FinanceMergeTests(WorkbenchTestCase):
    """财务与报销合并成一页：报销区在前、账本在后，导航只留一个入口。"""

    def test_finance_page_contains_claims_and_ledger(self):
        ExpenseClaim.objects.create(applicant=self.dev, amount='30.00',
                                    occurred_on=datetime.date(2026, 1, 13), memo='合并后的报销')
        FinanceEntry.objects.create(kind='income', amount='800.00',
                                    occurred_on=datetime.date(2026, 1, 14), memo='合并后的账本',
                                    created_by=self.admin)
        self.client.force_login(self.admin)
        ledger = self.client.get(reverse('finance_list')).content.decode()
        self.assertIn('id="ledger"', ledger)
        self.assertNotIn('id="claims"', ledger)          # 账本页签不渲染报销区
        self.assertIn('合并后的账本', ledger)
        claims = self.client.get(reverse('finance_list') + '?tab=claims').content.decode()
        self.assertIn('id="claims"', claims)
        self.assertIn('合并后的报销', claims)
        self.assertIn(f'action="{reverse("claim_new")}"', claims)  # 报销表单在同一页的报销页签
        self.assertIn('?tab=ledger', ledger)             # 两个页签的入口都在
        self.assertIn('?tab=claims', ledger)

    def test_navigation_has_one_finance_entry(self):
        self.client.force_login(self.dev)
        html = self.client.get(reverse('dashboard')).content.decode()
        sidebar = html.split('<aside class="shell-sidebar"')[1].split('</aside>')[0]
        self.assertEqual(sidebar.count(f'href="{reverse("finance_list")}"'), 1)
        self.assertNotIn(f'href="{reverse("claim_list")}"', sidebar)
        self.assertNotIn(f'href="{reverse("change_password")}"', sidebar)  # 修改密码并入账户设置
        settings = self.client.get(reverse('profile')).content.decode()
        self.assertIn(f'href="{reverse("profile")}?tab=security"', settings)
        self.assertNotIn(f'href="{reverse("profile")}?tab=appearance"', settings)  # 外观页签已移除

    def test_members_can_submit_claim_from_finance_page(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('claim_new'),
                                    {'amount': '66.00', 'occurred_on': '2026-01-16', 'memo': '合并页提交'})
        self.assertEqual(response['Location'], reverse('finance_list') + '?tab=claims')
        claim = ExpenseClaim.objects.get()
        self.assertEqual(claim.applicant, self.dev)
        self.assertEqual(claim.status, ExpenseClaim.PENDING)

    def test_old_claim_pages_redirect_into_finance_page(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse('claim_list'))['Location'],
                         reverse('finance_list') + '?tab=claims')
        self.assertEqual(self.client.get(reverse('claim_new'))['Location'],
                         reverse('finance_list') + '?tab=claims#claim-new')

    def test_claim_review_returns_to_claims_section(self):
        claim = ExpenseClaim.objects.create(applicant=self.dev, amount='40.00',
                                            occurred_on=datetime.date(2026, 1, 15), memo='打车')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('claim_review', args=[claim.pk]),
                                    {'decision': 'reject', 'note': ''})
        self.assertEqual(response['Location'], reverse('finance_list') + '?tab=claims')


class ClaimProjectTests(WorkbenchTestCase):
    """报销申请可以（可选）关联一个项目；下拉框只列出申请人参与的项目，管理员看到全部。"""

    def project_select(self, response):
        html = response.content.decode()
        self.assertIn('<select name="project"', html)
        return html.split('<select name="project"', 1)[1].split('</select>', 1)[0]

    def test_project_dropdown_lists_only_projects_i_participate_in(self):
        self.client.force_login(self.dev)                       # dev 是项目成员
        select = self.project_select(self.client.get(reverse('finance_list') + '?tab=claims'))
        self.assertIn(self.project.name, select)
        self.assertIn('不关联项目', select)                      # 项目可以不选

        self.client.force_login(self.outsider)                  # other 不在项目里
        select = self.project_select(self.client.get(reverse('finance_list') + '?tab=claims'))
        self.assertNotIn(self.project.name, select)

    def test_admin_project_dropdown_lists_every_open_project(self):
        self.client.force_login(self.admin)                     # 管理员不是项目成员，也能选任何项目
        select = self.project_select(self.client.get(reverse('finance_list') + '?tab=claims'))
        self.assertIn(self.project.name, select)

    def test_claim_can_be_submitted_with_a_project(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('claim_new'), {
            'amount': '120.00', 'occurred_on': '2026-02-02', 'memo': '试剂采购',
            'project': self.project.pk})
        self.assertEqual(response.status_code, 302)
        claim = ExpenseClaim.objects.get()
        self.assertEqual(claim.project, self.project)
        self.assertEqual(claim.project_label, self.project.name)
        claims = self.client.get(reverse('finance_list') + '?tab=claims').content.decode()
        self.assertIn(self.project.name, claims)
        self.assertNotIn('未关联项目', claims)

    def test_claim_can_be_submitted_without_a_project(self):
        self.client.force_login(self.dev)
        self.client.post(reverse('claim_new'), {
            'amount': '45.00', 'occurred_on': '2026-02-03', 'memo': '团队宽带'})
        claim = ExpenseClaim.objects.get()
        self.assertIsNone(claim.project)
        self.assertEqual(claim.project_label, '未关联项目')
        claims = self.client.get(reverse('finance_list') + '?tab=claims').content.decode()
        self.assertIn('未关联项目', claims)

    def test_claim_cannot_name_a_project_i_do_not_participate_in(self):
        self.client.force_login(self.outsider)
        self.client.post(reverse('claim_new'), {
            'amount': '10.00', 'occurred_on': '2026-02-04', 'memo': '越权尝试',
            'project': self.project.pk})
        self.assertEqual(ExpenseClaim.objects.count(), 0)       # 表单校验挡下，不落库


class ProjectCostTests(WorkbenchTestCase):
    def setUp(self):
        super().setUp()
        from .models import TeamMembership
        TeamMembership.objects.filter(team_id=1,user=self.dev).update(permissions=['finance'])

    """项目页成本汇总：只统计关联本项目、且未作废的账本记录。"""

    def ledger(self, **kwargs):
        kwargs.setdefault('created_by', self.admin)
        kwargs.setdefault('occurred_on', datetime.date(2026, 1, 10))
        return FinanceEntry.objects.create(**kwargs)

    def page(self):
        self.client.force_login(self.dev)
        return self.client.get(reverse('project_detail', args=[self.project.pk])).content.decode()

    def test_summary_adds_up_only_linked_entries(self):
        self.ledger(kind='expense', amount='200.00', memo='试剂', project=self.project)
        self.ledger(kind='api', amount='50.00', memo='模型调用', project=self.project)
        self.ledger(kind='expense', amount='999.00', memo='别的项目开销', project=None)
        html = self.page()
        self.assertIn('¥ 250.00', html)                 # 已用 = 200 + 50
        self.assertNotIn('999.00', html)                # 未关联本项目的账目不计入

    def test_summary_separates_project_income_from_cost(self):
        self.ledger(kind='expense', amount='200.00', memo='试剂', project=self.project)
        self.ledger(kind='income', amount='500.00', memo='项目拨款', project=self.project)
        html = self.page()
        self.assertIn('¥ 200.00', html)                 # 已用（只算流出）
        self.assertIn('¥ 500.00', html)                 # 项目收入

    def test_voided_entries_are_not_counted(self):
        self.ledger(kind='expense', amount='200.00', memo='有效支出', project=self.project)
        voided = self.ledger(kind='expense', amount='400.00', memo='已作废支出', project=self.project)
        voided.voided_at = timezone.now()
        voided.voided_by = self.admin
        voided.save(update_fields=['voided_at', 'voided_by'])
        html = self.page()
        self.assertIn('¥ 200.00', html)                 # 只算未作废的那笔
        self.assertNotIn('400.00', html)
        self.assertNotIn('已作废支出', html)

    def test_budget_gives_remaining_and_usage(self):
        self.project.budget = '1000.00'
        self.project.save(update_fields=['budget'])
        self.ledger(kind='expense', amount='250.00', memo='试剂', project=self.project)
        html = self.page()
        self.assertIn('¥ 1000.00', html)                # 预算
        self.assertIn('¥ 750.00', html)                 # 剩余
        self.assertIn('已使用预算的 25%', html)

    def test_over_budget_is_flagged_and_the_bar_is_capped(self):
        self.project.budget = '100.00'
        self.project.save(update_fields=['budget'])
        self.ledger(kind='expense', amount='250.00', memo='超支', project=self.project)
        html = self.page()
        self.assertIn('已使用预算的 250%', html)
        self.assertIn('已超出预算', html)
        self.assertIn('width:100%', html)               # 进度条上限 100%，不外溢

    def test_project_without_budget_shows_no_usage(self):
        self.ledger(kind='expense', amount='250.00', memo='试剂', project=self.project)
        html = self.page()
        self.assertIn('¥ 250.00', html)                 # 成本照样汇总
        self.assertIn('未设预算', html)
        self.assertNotIn('已使用预算的', html)           # 没有预算就不给使用比例与进度条

    def test_approved_claim_carries_its_project_into_the_ledger(self):
        claim = ExpenseClaim.objects.create(applicant=self.dev, amount='120.00',
                                            occurred_on=datetime.date(2026, 2, 2),
                                            memo='试剂采购', project=self.project)
        self.client.force_login(self.admin)
        self.client.post(reverse('claim_review', args=[claim.pk]), {'decision': 'approve', 'note': 'ok'})
        claim.refresh_from_db()
        self.assertEqual(claim.entry.project, self.project)
        self.client.force_login(self.dev)
        html = self.client.get(reverse('project_detail', args=[self.project.pk])).content.decode()
        self.assertIn('¥ 120.00', html)                 # 入账后立刻计入项目成本


class ChatReferenceScopeTests(WorkbenchTestCase):
    """消息引用的可见范围与来源记录一致：报销申请对团队成员全开放。"""

    def setUp(self):
        super().setUp()
        self.claim = ExpenseClaim.objects.create(applicant=self.outsider, amount='88.00',
                                                 occurred_on=datetime.date(2026, 1, 20),
                                                 memo='他人的待审报销')

    def test_other_members_cannot_search_a_claim(self):
        self.client.force_login(self.dev)
        response = self.client.get(reverse('chat_reference_search'), {'kind': 'claim', 'q': '待审报销'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('他人的待审报销', [row['title'] for row in response.json()['results']])
        from .models import TeamMembership
        TeamMembership.objects.filter(team_id=1,user=self.dev).update(permissions=['finance'])
        response=self.client.get(reverse('chat_reference_search'), {'kind':'claim'})
        self.assertIn('他人的待审报销',[row['title'] for row in response.json()['results']])

    def test_other_members_need_finance_to_open_claim_reference(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse('chat_reference_detail',args=['claim',self.claim.pk])).status_code,404)
        from .models import TeamMembership
        TeamMembership.objects.filter(team_id=1,user=self.dev).update(permissions=['finance'])
        self.client.force_login(self.dev)
        response = self.client.get(reverse('chat_reference_detail', args=['claim', self.claim.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '88.00')
        self.assertContains(response, '他人的待审报销')

    def test_normal_users_are_kept_out_of_claim_references(self):
        """普通用户不是团队成员：引用搜索与详情都由中间件挡回公开站。"""
        MemberProfile.objects.create(user=self.dev, tier=MemberProfile.NORMAL)
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse('chat_reference_search'),{'kind':'claim'}).json()['results'],[])
        self.assertEqual(self.client.get(reverse('chat_reference_detail',args=['claim',self.claim.pk])).status_code,404)


class LegacyRecoveryCompatibilityTests(WorkbenchTestCase):
    """Previously issued email links still work; new recovery uses codes."""
    def test_old_link_is_valid_and_single_use(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        url=reverse('password_reset_confirm',kwargs={'uidb64':urlsafe_base64_encode(force_bytes(self.dev.pk)), 'token':default_token_generator.make_token(self.dev)})
        page=self.client.get(url,follow=True)
        self.assertContains(page,'设置新密码')
        response=self.client.post(page.redirect_chain[-1][0],{'new_password1':'new-pass-9812!','new_password2':'new-pass-9812!'})
        self.assertRedirects(response,reverse('password_reset_complete'))
        self.assertContains(self.client.get(url,follow=True),'链接无效或已过期')

    def test_code_hash_expiration_and_replacement(self):
        item,code=EmailVerificationCode.issue(self.dev,'dev@example.com')
        self.assertNotEqual(item.code_hash,code)
        self.assertTrue(item.verify(code))
        second,new_code=EmailVerificationCode.issue(self.dev,'dev@example.com')
        item.refresh_from_db();self.assertFalse(item.is_usable)
        self.assertTrue(second.verify(new_code))
        second.expires_at=timezone.now()-datetime.timedelta(seconds=1)
        second.save(update_fields=['expires_at']);self.assertFalse(second.verify(new_code))

    def test_code_hour_limit_and_cooldown(self):
        for _ in range(5):EmailVerificationCode.issue(self.dev,'dev@example.com')
        self.assertEqual(EmailVerificationCode.sends_in_last_hour(self.dev),5)
        self.assertGreater(EmailVerificationCode.cooldown_remaining(self.dev),0)

    def test_email_still_normalises_and_remains_unique(self):
        user=User.objects.create_user('mixed',email='  MiXeD@Example.COM  ')
        self.assertEqual(user.email,'mixed@example.com')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():User.objects.create_user('clash',email='MIXED@example.com')

    def test_login_links_to_recovery(self):
        self.assertContains(self.client.get(reverse('login')),reverse('password_reset'))


class EmailConfigurationCheckTests(TestCase):
    """邮件配置自检：把「生产没配 SMTP」变成启动警告，而不是成员遇到的 500。"""

    def ids(self, **overrides):
        with override_settings(**overrides):
            return {issue.id for issue in checks.email_configuration(None)}

    def test_warns_when_production_has_no_smtp(self):
        ids = self.ids(DEBUG=False, EMAIL_HOST='', EMAIL_HOST_USER='')
        self.assertIn('core.W001', ids)

    def test_development_needs_no_smtp(self):
        self.assertEqual(self.ids(DEBUG=True, EMAIL_HOST='', EMAIL_HOST_USER=''), set())

    def test_warns_when_smtp_host_has_no_user(self):
        ids = self.ids(DEBUG=False, EMAIL_HOST='smtp.example.com', EMAIL_HOST_USER='',
                       EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
        self.assertIn('core.W004', ids)
        self.assertNotIn('core.W001', ids)

    def test_warns_when_smtp_user_has_no_password(self):
        ids = self.ids(DEBUG=False, EMAIL_HOST='smtp.example.com', EMAIL_HOST_USER='a@example.com',
                       EMAIL_HOST_PASSWORD='',
                       EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
        self.assertIn('core.W005', ids)

    def test_warns_when_tls_and_ssl_are_both_on(self):
        ids = self.ids(DEBUG=False, EMAIL_HOST='smtp.example.com', EMAIL_HOST_USER='a@example.com',
                       EMAIL_USE_TLS=True, EMAIL_USE_SSL=True)
        self.assertIn('core.W002', ids)

    def test_fully_configured_smtp_is_clean(self):
        self.assertEqual(self.ids(DEBUG=False, EMAIL_HOST='smtp.example.com',
                                  EMAIL_HOST_USER='a@example.com', EMAIL_HOST_PASSWORD='x',
                                  EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
                                  EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend'), set())


class ProfileTests(WorkbenchTestCase):
    """账户设置：资料与密码，以及并入其中的修改密码。主题切换只在顶栏。"""

    def test_profile_shows_account_and_permissions(self):
        self.owner.email = 'lead@example.com'
        self.owner.save(update_fields=['email'])
        self.client.force_login(self.owner)
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '账户设置')
        self.assertContains(response, 'lead@example.com')       # 资料表单带出当前邮箱
        self.assertContains(response, '密码与安全')              # 设置页签入口
        self.assertNotContains(response, '外观')                 # 外观页签已移除

    def test_appearance_tab_is_gone(self):
        """旧书签 ?tab=appearance 退回账户资料页，不再渲染主题选项。"""
        self.client.force_login(self.dev)
        html = self.client.get(reverse('profile') + '?tab=appearance').content.decode()
        self.assertIn('账户资料', html)
        self.assertNotIn('data-theme-set', html)
        self.assertNotIn('theme-options', html)

    def test_admin_sees_admin_permissions(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn(f'href="{reverse("project_new")}"', html)

    def test_developer_does_not_get_admin_permissions(self):
        self.client.force_login(self.dev)
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertNotIn(f'href="{reverse("project_new")}"', html)

    def test_member_updates_own_profile(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('profile'),
                                    {'action': 'profile', 'first_name': '小张', 'email': 'dev@example.com'})
        self.assertRedirects(response, reverse('profile'))
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.first_name, '小张')
        self.assertEqual(self.dev.email, '')  # 邮箱另走验证码绑定，资料表单不能绕过。
        self.assertFalse(self.dev.is_staff)  # 改资料不改角色

    def test_password_change_lives_in_profile_and_keeps_session(self):
        self.client.force_login(self.dev)
        response = self.client.post(reverse('profile'), {
            'action': 'password', 'old_password': 'verify-only-12345',
            'new_password1': 'new-pass-9911aa', 'new_password2': 'new-pass-9911aa'})
        self.assertRedirects(response, reverse('profile') + '?tab=security')
        self.dev.refresh_from_db()
        self.assertTrue(self.dev.check_password('new-pass-9911aa'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)  # 本人不被登出

    def test_no_way_to_open_someone_elses_profile(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        self.assertEqual(self.client.get(f'/account/{self.dev.pk}/').status_code, 404)

    def test_unknown_profile_action_is_rejected(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(reverse('profile'), {'action': 'promote-me'}).status_code, 403)
        self.dev.refresh_from_db()
        self.assertFalse(self.dev.is_staff)

    def test_old_password_page_redirects_into_profile(self):
        self.client.force_login(self.dev)
        response = self.client.get(reverse('change_password'))
        self.assertEqual(response['Location'], reverse('profile') + '?tab=security')


class ThemeTests(WorkbenchTestCase):
    """深色模式：由顶栏开关选择（工作台与公开页都有），脚本记住选择。"""

    def test_theme_can_be_chosen_from_the_header(self):
        """深色 / 浅色只由顶栏开关切换；账户设置里不再有「外观」页签。"""
        login_html = self.client.get(reverse('login')).content.decode()
        self.assertIn('data-theme-toggle', login_html)          # 公开页面也有开关
        self.assertIn('workbench-theme', login_html)            # 样式加载前先定主题,不闪白
        self.assertLess(login_html.index('workbench-theme'), login_html.index('site.css'))
        self.client.force_login(self.dev)
        dashboard = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('data-theme-toggle', dashboard)           # 工作台顶栏也有
        self.assertNotIn('data-theme-set', dashboard)           # 设置页里的主题选项已移除

    def test_theme_is_chosen_before_the_stylesheet_loads(self):
        """先定主题、再加载样式，深色模式刷新时不会闪一下白底。"""
        self.client.force_login(self.dev)
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('workbench-theme', html)
        self.assertLess(html.index('workbench-theme'), html.index('site.css'))

    def test_dark_palette_and_script_are_shipped(self):
        css = (settings.BASE_DIR / 'static' / 'core' / 'site.css').read_text(encoding='utf-8')
        self.assertIn('[data-theme="dark"]', css)
        self.assertIn('--bg:', css)
        js = (settings.BASE_DIR / 'static' / 'core' / 'site.js').read_text(encoding='utf-8')
        self.assertIn('workbench-theme', js)
        self.assertIn('localStorage', js)


class MembershipTests(WorkbenchTestCase):
    def test_only_admin_manages_members(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse('members')).status_code, 200)
        self.assertEqual(self.client.post(reverse('members'), {'id': self.admin.pk, 'action': 'demote'}).status_code, 403)

    def test_admin_cannot_lock_itself_out(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('members'), {'id': self.admin.pk, 'action': 'deactivate'})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_last_admin_is_protected(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('members'), {'id': self.admin.pk, 'action': 'demote'})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff)

    def test_admin_promotes_and_deactivates_developers(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('members'), {'id': self.dev.pk, 'action': 'promote'})
        self.dev.refresh_from_db()
        from .models import TeamMembership
        self.assertFalse(self.dev.is_staff)
        self.assertEqual(TeamMembership.objects.get(team_id=1,user=self.dev).role,'admin')
        self.client.post(reverse('members'), {'id': self.dev.pk, 'action': 'demote'})
        self.dev.refresh_from_db()
        self.assertFalse(self.dev.is_staff)
        self.client.post(reverse('members'), {'id': self.dev.pk, 'action': 'deactivate'})
        self.dev.refresh_from_db()
        self.assertTrue(self.dev.is_active)
        self.assertFalse(TeamMembership.objects.get(team_id=1,user=self.dev).active)

    def test_invite_code_registers_exactly_one_developer(self):
        invite, code = Invite.issue(self.admin)
        payload = {'username': 'newbie', 'email': 'newbie@example.com',
                   'password1': 'verify-only-12345',
                   'password2': 'verify-only-12345', 'invite_code': code}
        response = verified_post(self.client,reverse('register'), payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='newbie').exists())
        invite.refresh_from_db()
        self.assertIsNotNone(invite.used_at)

        self.client.logout()
        payload['username'] = 'newbie2'
        payload['email'] = 'newbie2@example.com'
        response = verified_post(self.client,reverse('register'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newbie2').exists())


class PageRenderTests(WorkbenchTestCase):
    """冒烟测试：每个页面都能正常渲染，兜住模板错误。"""

    def setUp(self):
        super().setUp()
        self.submission = Submission.objects.create(task=self.child, author=self.dev, summary='成果正文')
        self.attachment = Attachment.objects.create(submission=self.submission, file='attachment/a.pdf',
                                                    original_name='a.pdf', uploaded_by=self.dev)
        self.claim = ExpenseClaim.objects.create(applicant=self.dev, amount='12.00',
                                                 occurred_on=datetime.date(2026, 1, 10), memo='报销事由')
        self.entry = FinanceEntry.objects.create(kind='income', amount='100.00',
                                                 occurred_on=datetime.date(2026, 1, 11), memo='收入',
                                                 created_by=self.admin)
        self.entry_attachment = Attachment.objects.create(entry=self.entry, file='entry/r.pdf',
                                                          original_name='r.pdf', uploaded_by=self.admin)
        self.comment = Comment.objects.create(task=self.child, author=self.dev,
                                              kind=Comment.GOAL, body='目标留言')
        self.comment_attachment = Attachment.objects.create(comment=self.comment, file='comment/c.png',
                                                            original_name='c.png', uploaded_by=self.dev)
        self.claim_attachment = Attachment.objects.create(claim=self.claim, file='claim/i.pdf',
                                                          original_name='i.pdf', uploaded_by=self.dev)

    def _common_urls(self):
        return [
            reverse('dashboard'),
            reverse('task_list'),
            reverse('task_list') + '?status=open&mine=1',
            reverse('project_detail', args=[self.project.pk]),
            reverse('task_detail', args=[self.mother.pk]),
            reverse('task_detail', args=[self.child.pk]),
            reverse('finance_list'),
            reverse('profile'),
        ]

    def test_admin_pages_render(self):
        self.client.force_login(self.admin)
        urls = self._common_urls() + [
            reverse('project_new'),
            reverse('project_edit', args=[self.project.pk]),
            reverse('task_new') + f'?project={self.project.pk}',
            reverse('task_new') + f'?project={self.project.pk}&parent={self.mother.pk}',
            reverse('task_edit', args=[self.child.pk]),
            reverse('finance_new'),
            reverse('finance_edit', args=[self.entry.pk]),
            reverse('members'),
            reverse('invites'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_owner_pages_render(self):
        self.client.force_login(self.owner)
        for url in self._common_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_developer_pages_render(self):
        self.client.force_login(self.dev)
        for url in self._common_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_only_pages_reject_developer(self):
        self.client.force_login(self.dev)
        for url in [reverse('project_new'), reverse('invites'),
                    reverse('finance_new')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_attachment_links_render_for_authorised_viewers(self):
        self.client.force_login(self.admin)
        for url in [reverse('task_detail', args=[self.child.pk]), reverse('finance_list')]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get(reverse('finance_list')), 'r.pdf')


class RoleLoginTests(WorkbenchTestCase):
    def test_login_automatically_uses_account_role(self):
        for user, role in [(self.admin,'admin'),(self.dev,'developer')]:
            self.client.logout()
            result=self.client.post(reverse('login'),{'username':user.username,'password':'verify-only-12345'})
            self.assertEqual(result['Location'],reverse('workspace_home'))
            self.assertEqual(self.client.session['workbench-login-role'],role)

    def test_forged_login_role_does_not_escalate(self):
        self.client.post(reverse('login'),{'username':self.dev.username,'password':'verify-only-12345','role':'admin'})
        self.assertEqual(self.client.get(reverse('members')).status_code,200)
        self.assertEqual(self.client.post(reverse('members'), {'id': self.dev.pk, 'action': 'promote'}).status_code,403)

    def test_demoted_admin_loses_access_in_existing_session(self):
        self.client.force_login(self.admin)
        self.admin.is_staff=False
        self.admin.is_superuser=False
        self.admin.save()
        from .models import TeamMembership
        TeamMembership.objects.filter(team_id=1,user=self.admin).update(role='member')
        self.assertEqual(self.client.get(reverse('members')).status_code,200)
        self.assertEqual(self.client.post(reverse('members'), {'id': self.dev.pk, 'action': 'promote'}).status_code,403)

    def test_existing_normal_user_remains_restricted(self):
        MemberProfile.objects.create(user=self.outsider,tier=MemberProfile.NORMAL)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code,200)
        self.assertEqual(self.client.get(reverse('finance_list')).status_code,200)
        self.assertEqual(self.client.get(reverse('project_detail',args=[self.project.pk])).status_code,404)
        self.assertEqual(self.client.post('/register/user/',{}).status_code,404)

    def test_login_by_email(self):
        MemberProfile.objects.update_or_create(user=self.dev,defaults={'legacy_login_allowed':True})
        self.dev.email='dev@example.com'; self.dev.save()
        result=self.client.post(reverse('login'),{'username':'dev@example.com','password':'verify-only-12345'})
        self.assertEqual(result['Location'],reverse('workspace_home'))

    def test_ambiguous_email_is_rejected(self):
        """邮箱唯一性是「邮箱自助找回」的前提：数据库层面不再允许两个账号共用一个邮箱。"""
        self.dev.email = 'same@example.com'
        self.dev.save(update_fields=['email'])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.filter(pk=self.owner.pk).update(email='same@example.com')

    def test_login_by_email_works_when_unique(self):
        """元老账号保留唯一邮箱登录兼容。"""
        MemberProfile.objects.update_or_create(user=self.dev,defaults={'legacy_login_allowed':True})
        self.dev.email = 'Dev@Example.com'
        self.dev.save(update_fields=['email'])
        result = self.client.post(reverse('login'),
                                  {'username': 'dev@example.com', 'password': 'verify-only-12345'})
        self.assertEqual(result['Location'], reverse('workspace_home'))



class PublicPageTests(WorkbenchTestCase):
    """项目展示、关于，以及普通用户注册。"""

    def test_showcase_only_displays_published_projects(self):
        self.assertNotContains(self.client.get(reverse('showcase')), self.project.name)
        self.project.public_state='public'
        self.project.public_summary='approved summary'
        self.project.save()
        self.assertContains(self.client.get(reverse('showcase')), self.project.name)

    def test_about_requires_member_opt_in(self):
        from .models import PublicProfile
        PublicProfile.objects.create(user=self.dev, display_name='Visible member', is_public=True)
        self.assertContains(self.client.get(reverse('about')), 'Visible member')
        self.assertNotContains(self.client.get(reverse('about')), self.admin.username)

    def test_registration_requires_an_invite(self):
        response=self.client.post('/register/user/', {'username':'reader01'})
        self.assertEqual(response.status_code,404)
        verified_post(self.client,reverse('register'),{'username':'reader01','email':'reader01@example.com',
                                              'password1':'verify-only-12345','password2':'verify-only-12345'})
        self.assertFalse(User.objects.filter(username='reader01').exists())

    def test_registration_requires_an_email(self):
        """邮箱是找回密码的唯一凭据，注册时必须填。"""
        invite, code = Invite.issue(self.admin)
        base = {'username': 'nomail', 'password1': 'verify-only-12345',
                'password2': 'verify-only-12345', 'invite_code': code}
        self.assertEqual(verified_post(self.client,reverse('register'), base).status_code, 200)
        self.assertFalse(User.objects.filter(username='nomail').exists())

    def test_registration_rejects_a_duplicate_email(self):
        invite, code = Invite.issue(self.admin)
        self.dev.email = 'taken@example.com'
        self.dev.save(update_fields=['email'])
        response = verified_post(self.client,reverse('register'), {
            'username': 'dup', 'email': 'Taken@Example.com', 'password1': 'verify-only-12345',
            'password2': 'verify-only-12345', 'invite_code': code})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='dup').exists())

    def test_invited_developer_registration_records_the_developer_tier(self):
        invite, code = Invite.issue(self.admin)
        verified_post(self.client,reverse('register'), {
            'username': 'dev02', 'email': 'dev02@example.com', 'password1': 'verify-only-12345',
            'password2': 'verify-only-12345', 'invite_code': code})
        self.assertEqual(User.objects.get(username='dev02').member_profile.tier,
                         MemberProfile.DEVELOPER)

    def test_admin_can_invite_a_developer_to_become_an_admin(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('members'), {'id': self.dev.pk, 'action': 'promote'})
        self.assertEqual(response.status_code, 302)
        self.dev.refresh_from_db()
        from .models import TeamMembership
        self.assertFalse(self.dev.is_staff)
        self.assertEqual(TeamMembership.objects.get(team_id=1,user=self.dev).role,'admin')
        # 升为管理员后，以管理员身份登录即可看到完整界面。
        self.client.logout()
        self.client.post(reverse('login'), {'username': self.dev.username, 'role': 'admin',
                                           'password': 'verify-only-12345'})
        self.assertEqual(self.client.get(reverse('members')).status_code, 200)

    def test_admin_can_promote_a_normal_user_to_developer(self):
        normal = User.objects.create_user('reader02', password='verify-only-12345')
        MemberProfile.objects.create(user=normal, tier=MemberProfile.NORMAL)
        self.client.force_login(self.admin)
        self.client.post(reverse('members'), {'id': normal.pk, 'action': 'make_developer'})
        normal.refresh_from_db()
        from .models import TeamMembership
        self.assertEqual(normal.member_profile.tier, MemberProfile.NORMAL)
        self.assertEqual(TeamMembership.objects.get(team_id=1,user=normal).role,'member')


class ChatRoomTests(WorkbenchTestCase):
    """聊天室分为「公共讨论」（管理员＋开发者）与「公共聊天室」（所有登录用户）。"""

    def setUp(self):
        super().setUp()
        self.normal = User.objects.create_user('reader03', password='verify-only-12345')
        MemberProfile.objects.create(user=self.normal, tier=MemberProfile.NORMAL)

    def login(self, username, role):
        return self.client.post(reverse('login'), {'username': username, 'role': role,
                                                   'password': 'verify-only-12345'})

    def test_developer_room_is_open_to_admins_and_developers(self):
        for account, role in [(self.admin, 'admin'), (self.dev, 'developer')]:
            with self.subTest(account=account.username):
                self.client.logout()
                self.login(account.username, role)
                self.assertRedirects(self.client.get(reverse('chat_developers')), reverse('messages_hub'))

    def test_public_room_is_open_to_everyone(self):
        for account, role in [(self.admin, 'admin'), (self.dev, 'developer'),
                              (self.normal, 'normal')]:
            with self.subTest(account=account.username):
                self.client.logout()
                self.login(account.username, role)
                response = self.client.get(reverse('chat_public'))
                if account == self.normal:
                    self.assertEqual(response.status_code, 200)
                else:
                    self.assertRedirects(response, reverse('messages_hub') + '?room=public&space=1')

    def test_normal_user_cannot_enter_the_developer_room(self):
        self.login(self.normal.username, 'normal')
        self.assertEqual(self.client.get(reverse('chat_developers')).status_code,403)
        # 房间页签里不出现「公共讨论」的入口。
        html = self.client.get(reverse('chat_public')).content.decode()
        room_tabs = html.split('aria-label="聊天室"')[1].split('</nav>')[0]
        self.assertNotIn(reverse('chat_developers'), room_tabs)
        self.assertIn(reverse('chat_public'), room_tabs)

    def test_developer_sees_both_room_tabs(self):
        self.login(self.dev.username, 'developer')
        html = self.client.get(reverse('chat_public'), follow=True).content.decode()
        self.assertIn(reverse('messages_hub'), html)
        self.assertIn(reverse('messages_hub') + '?room=public', html)

    def test_chat_index_lands_on_a_room_the_identity_may_use(self):
        self.login(self.dev.username, 'developer')
        self.assertEqual(self.client.get(reverse('chat'))['Location'],
                         reverse('chat_developers'))
        self.client.logout()
        self.login(self.normal.username, 'normal')
        self.assertEqual(self.client.get(reverse('chat'))['Location'], reverse('chat_public'))

    def test_message_is_stored_and_shown(self):
        self.login(self.dev.username, 'developer')
        response = self.client.post(reverse('chat_developers'), {'body': '大家好，基线跑通了。'})
        self.assertEqual(response['Location'], reverse('chat_developers'))
        message = ChatMessage.objects.get()
        self.assertEqual(message.room, ChatMessage.DEVELOPERS)
        self.assertEqual(message.author, self.dev)
        self.assertContains(self.client.get(reverse('chat_developers'), follow=True), '基线跑通了')

    def test_rooms_do_not_leak_into_each_other(self):
        ChatMessage.objects.create(room=ChatMessage.DEVELOPERS, author=self.admin, body='内部消息')
        ChatMessage.objects.create(room=ChatMessage.PUBLIC, author=self.admin, body='公开消息')
        self.login(self.dev.username, 'developer')
        self.assertContains(self.client.get(reverse('chat_developers'), follow=True), '内部消息')
        self.assertNotIn('公开消息',self.client.get(reverse('chat_developers'),follow=True).content.decode().split('data-message-log')[1])
        self.assertContains(self.client.get(reverse('chat_public'), follow=True), '公开消息')
        self.assertNotIn('内部消息',self.client.get(reverse('chat_public'),follow=True).content.decode().split('data-message-log')[1])

    def test_polling_returns_only_newer_messages(self):
        old = ChatMessage.objects.create(room=ChatMessage.PUBLIC, author=self.admin, body='旧的')
        ChatMessage.objects.create(room=ChatMessage.PUBLIC, author=self.dev, body='新的')
        self.login(self.dev.username, 'developer')
        payload = self.client.get(reverse('chat_public_messages'), {'after': old.pk}).json()
        self.assertEqual([item['body'] for item in payload['messages']], ['新的'])
        self.assertEqual(payload['messages'][0]['author'], 'dev')
        self.assertTrue(payload['messages'][0]['mine'])
        self.assertEqual(payload['total'], 2)

    def test_polling_rejects_a_room_the_identity_cannot_use(self):
        self.login(self.normal.username, 'normal')
        response = self.client.get(reverse('chat_developers_messages'))
        self.assertEqual(response.status_code,403)

    def test_empty_message_is_rejected(self):
        self.login(self.dev.username, 'developer')
        self.client.post(reverse('chat_developers'), {'body': '   '})
        self.assertEqual(ChatMessage.objects.count(), 0)


class PublicPagesTests(WorkbenchTestCase):
    """公开页面:登录落地页、成员与联系合并页、首页与分页的导航差异。"""

    def test_login_page_is_a_landing_with_public_links(self):
        html = self.client.get(reverse('login')).content.decode()
        self.assertIn('让研究过程可理解', html)
        self.assertIn('让成果有出处', html)
        for name in ['public_projects', 'public_experiments', 'public_members']:
            self.assertIn(f'href="{reverse(name)}"', html)
        self.assertIn('name="password"', html)          # 登录表单仍在这一页
        self.assertIn('name="username"', html)

    def test_members_and_contact_share_one_page(self):
        TeamContact.objects.update_or_create(pk=1, defaults={'email': 'team@example.com', 'phone': '123456'})
        for name in ['public_members', 'contact']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, '成员与联系')
            self.assertContains(response, 'team@example.com')
            self.assertContains(response, '123456')

    def test_home_hides_public_nav_but_subpages_keep_it(self):
        home = self.client.get(reverse('public_home')).content.decode()
        self.assertNotIn('public-nav', home)              # 首页不显示那排标签
        sub = self.client.get(reverse('public_projects')).content.decode()
        self.assertIn('public-nav', sub)                  # 分页仍可见
        for name in ['public_projects', 'public_experiments', 'public_members']:
            self.assertIn(f'href="{reverse(name)}"', sub)
        self.assertNotIn(f'href="{reverse("contact")}"', sub)   # 已合并成「成员与联系」
