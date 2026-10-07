from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Project

from .models import CandidatePaper, SamplingRun
from .services import freeze_run, ingest_records, update_review_decisions

User = get_user_model()


class SamplingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sampling-owner", password="verify-only-12345")
        self.project = Project.objects.create(
            name="Sampling Project",
            goal="test",
            owner=self.user,
            created_by=self.user,
        )

    def make_run(self, seed="law_sampling_v1"):
        return SamplingRun.objects.create(
            project=self.project,
            name="Law sample",
            version="v1",
            periods=[{"id":"P3","label":"P3","start_year":2024,"end_year":2025}],
            selected_tiers=["T1"],
            selected_journals=["中国法学"],
            main_n=1,
            reserve_n=1,
            holdout_enabled=False,
            sampling_method=SamplingRun.METHOD_HASH_ISSUE_BALANCED,
            sampling_seed=seed,
            created_by=self.user,
        )

    def records(self):
        return [
            {"title":"论文甲","authors":"甲","journal":"中国法学","year":"2024","issue":"01","url":"https://example.test/?dbcode=CJFD&filename=A"},
            {"title":"论文乙","authors":"乙","journal":"中国法学","year":"2024","issue":"02","url":"https://example.test/?dbcode=CJFD&filename=B"},
            {"title":"论文丙","authors":"丙","journal":"中国法学","year":"2025","issue":"01","url":"https://example.test/?dbcode=CJFD&filename=C"},
        ]

    def test_ingest_deduplicates_and_auto_includes(self):
        run=self.make_run()
        ingest_records(run,self.records()+[self.records()[0]],"test.json")
        self.assertEqual(run.candidates.count(),3)
        self.assertEqual(run.candidates.filter(decision=CandidatePaper.INCLUDE).count(),3)

    def test_deterministic_freeze_and_artifacts(self):
        first=self.make_run("same-seed")
        ingest_records(first,self.records(),"a.json")
        freeze_run(first)
        pick1=list(first.candidates.exclude(sample_role="").order_by("paper_id").values_list("paper_id","candidate_key"))
        first.refresh_from_db()
        self.assertEqual(first.status,SamplingRun.FROZEN)
        self.assertTrue(first.run_fingerprint)
        self.assertTrue(first.artifacts.filter(artifact_type="bundle").exists())

        second=SamplingRun.objects.create(
            project=self.project,name="Law sample 2",version="v1",
            periods=first.periods,selected_tiers=first.selected_tiers,
            selected_journals=first.selected_journals,main_n=1,reserve_n=1,
            holdout_enabled=False,sampling_method=first.sampling_method,
            sampling_seed="same-seed",created_by=self.user,
        )
        ingest_records(second,self.records(),"b.json")
        freeze_run(second)
        pick2=list(second.candidates.exclude(sample_role="").order_by("paper_id").values_list("paper_id","candidate_key"))
        self.assertEqual(pick1,pick2)

    def test_uncertain_requires_review(self):
        run=self.make_run()
        ingest_records(run,[{"title":"人工智能法治圆桌","authors":"甲","journal":"中国法学","year":"2024","issue":"01"}],"x.json")
        item=run.candidates.get()
        self.assertEqual(item.eligibility_status,CandidatePaper.UNCERTAIN)
        update_review_decisions(run,[item.pk],CandidatePaper.INCLUDE)
        item.refresh_from_db()
        self.assertEqual(item.decision,CandidatePaper.INCLUDE)


class SamplingViewTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user("sampling-viewer",password="verify-only-12345")
        self.project=Project.objects.create(name="P",goal="g",owner=self.user,created_by=self.user)
        self.run=SamplingRun.objects.create(
            project=self.project,name="S",version="v1",
            periods=[{"id":"P3","label":"P3","start_year":2024,"end_year":2025}],
            selected_tiers=["T1"],selected_journals=["中国法学"],
            main_n=1,reserve_n=0,created_by=self.user,
        )
        self.client.force_login(self.user)

    def test_index_and_detail_render(self):
        self.assertEqual(self.client.get(reverse("sampling:index")).status_code,200)
        self.assertEqual(self.client.get(reverse("sampling:detail",args=[self.run.pk])).status_code,200)

    def test_agent_config_is_real_frame(self):
        response=self.client.get(reverse("sampling:agent_config",args=[self.run.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["config"]["frame"][0]["journal_family_name"],"中国法学")
