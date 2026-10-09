"""Production boundaries: corrupt compressed data, bounded versions and ownership."""
import io
import struct
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import Project, Team, TeamMembership, Workspace
from core.tenancy import scope
from .models import SamplingDocument, SamplingRun
from .test_production import ProductionBase, text_pdf


def corrupt_deflate(data, member):
    raw = bytearray(data)
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        info = bundle.getinfo(member)
        assert info.compress_type == zipfile.ZIP_DEFLATED
        offset = info.header_offset
    name_size, extra_size = struct.unpack_from("<HH", raw, offset + 26)
    payload = offset + 30 + name_size + extra_size
    raw[payload] = (raw[payload] & ~7) | 7  # Reserved DEFLATE block type.
    return bytes(raw)


class RuntimeBoundaryTests(ProductionBase):
    def test_corrupt_pdf_zip_returns_400_without_partial_documents(self):
        run = self.frozen()
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("pdf_manifest.csv", "paper_id,source_pdf\nP001,paper.pdf\n")
            bundle.writestr("paper.pdf", text_pdf())
        payload = corrupt_deflate(data.getvalue(), "paper.pdf")
        response = self.client.post(reverse("sampling:document_upload", args=[run.pk]),
            {"file": SimpleUploadedFile("broken.zip", payload)}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("全文包无法读取", response.json()["error"])
        self.assertFalse(SamplingDocument.objects.exists())

    def test_corrupt_result_zip_returns_business_error_without_new_run(self):
        run = self.frozen()
        with run.artifacts.get(artifact_type="bundle").file.open("rb") as original:
            payload = corrupt_deflate(original.read(), "sampling_frame.csv")
        count = SamplingRun.objects.count()
        response = self.client.post(reverse("sampling:bundle_import"),
            {"name": "保留包名称", "version": "imported", "project": "",
             "file": SimpleUploadedFile("broken.zip", payload)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "结果包格式或数据校验失败")
        self.assertEqual(response.context["bundle_form"].data["name"], "保留包名称")
        self.assertEqual(SamplingRun.objects.count(), count)

    def test_maximum_custom_version_and_repeated_clones_remain_valid(self):
        source = self.frozen(version="x" * 40)
        versions = []
        for _ in range(3):
            response = self.client.post(reverse("sampling:clone", args=[source.pk]))
            self.assertEqual(response.status_code, 302)
            clone = SamplingRun.objects.latest("pk")
            self.assertLessEqual(len(clone.version), 40)
            self.assertEqual(clone.source_run_id, source.pk)
            versions.append(clone.version)
        self.assertEqual(len(set(versions)), 3)
        source.refresh_from_db()
        self.assertEqual(source.version, "x" * 40)
        self.assertTrue(source.is_frozen)

    def test_numeric_version_overflow_uses_a_bounded_successor(self):
        source = self.frozen(version="v" + "9" * 39)
        response = self.client.post(reverse("sampling:clone", args=[source.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertLessEqual(len(SamplingRun.objects.latest("pk").version), 40)


class SamplingOwnershipTests(TestCase):
    def setUp(self):
        with scope(None, http=True):
            self.alice = get_user_model().objects.create_user("sampling-personal-alice")
            self.bob = get_user_model().objects.create_user("sampling-personal-bob")
        self.alice_space = Workspace.objects.create(kind="personal", owner=self.alice)
        self.bob_space = Workspace.objects.create(kind="personal", owner=self.bob)
        with scope(self.alice_space):
            self.own = self.make_run(self.alice, "Alice 独立研究")
        with scope(self.bob_space):
            self.other = self.make_run(self.bob, "Bob 私有研究")
        self.client.force_login(self.alice)

    def make_run(self, user, name):
        return SamplingRun.objects.create(name=name, created_by=user,
            periods=[{"id": "P3", "start_year": 2024, "end_year": 2025}],
            selected_tiers=["T1"], selected_journals=["中国法学"], main_n=1, reserve_n=0)

    def test_index_excludes_other_persons_independent_run(self):
        response = self.client.get(reverse("sampling:index"))
        self.assertContains(response, self.own.name)
        self.assertNotContains(response, self.other.name)

    def test_other_persons_read_and_write_endpoints_are_not_accessible(self):
        for name in ("detail", "agent_config", "agent_pdf_config", "document_status"):
            with self.subTest(name=name):
                response = self.client.get(reverse("sampling:" + name, args=[self.other.pk]))
                self.assertEqual(response.status_code, 404)
        for name in ("clone", "freeze", "review_apply", "agent_import", "document_upload"):
            with self.subTest(name=name):
                response = self.client.post(reverse("sampling:" + name, args=[self.other.pk]), {})
                self.assertEqual(response.status_code, 404)
        self.assertEqual(SamplingRun.all_objects.count(), 2)

    def test_team_member_can_read_but_cannot_edit_another_creators_run(self):
        team = Team.objects.create(name="Sampling 共同研究", owner=self.alice)
        workspace = Workspace.objects.create(kind="team", team=team)
        TeamMembership.objects.create(team=team, user=self.alice, role="owner")
        TeamMembership.objects.create(team=team, user=self.bob, role="member")
        with scope(workspace):
            run = self.make_run(self.alice, "团队样本集")
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("sampling:detail", args=[run.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("sampling:edit", args=[run.pk]), {}).status_code, 403)
        TeamMembership.objects.filter(team=team, user=self.bob).update(active=False)
        self.assertEqual(self.client.get(reverse("sampling:detail", args=[run.pk])).status_code, 404)

    def test_new_run_uses_explicit_authorized_space_and_its_existing_project(self):
        team = Team.objects.create(name="Sampling 项目归属", owner=self.alice)
        workspace = Workspace.objects.create(kind="team", team=team)
        TeamMembership.objects.create(team=team, user=self.alice, role="owner")
        with scope(workspace):
            project = Project.objects.create(name="真实项目表", owner=self.alice, created_by=self.alice)
        payload = {"name": "团队新样本", "ownership": str(workspace.pk), "project": str(project.pk),
            "version": "v1", "periods": ["P3"], "selected_tiers": ["T1"],
            "selected_journals": ["中国法学"], "main_n": "1", "reserve_n": "0",
            "sampling_method": "hash_simple", "sampling_seed": "ownership-regression"}
        response = self.client.post(reverse("sampling:new"), payload)
        self.assertEqual(response.status_code, 302)
        run = SamplingRun.all_objects.get(name="团队新样本")
        self.assertEqual(run.workspace_id, workspace.pk)
        self.assertEqual(run.project_id, project.pk)
        self.assertEqual(run.team_id, team.pk)
        with scope(self.bob_space):
            bob_project = Project.objects.create(name="Bob 项目", owner=self.bob, created_by=self.bob)
        payload["project"] = str(bob_project.pk)
        response = self.client.post(reverse("sampling:new"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("project", response.context["scope_form"].errors)
        self.assertEqual(self.client.get(reverse("sampling:index"), {"ownership": str(self.bob_space.pk)}).status_code, 403)
