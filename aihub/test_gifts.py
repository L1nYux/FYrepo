import os
import uuid
from pathlib import Path
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import ChatMessage, MemberProfile
from .models import Allowance, PointGift, PointGiftReceipt, BudgetWeek, PoolSettings
from .service import allowance, summary, week_now
from .gifts import expire_gifts

class PointGiftTests(TestCase):
    def setUp(self):
        self.me=User.objects.create_user('gift-sender');self.peer=User.objects.create_user('gift-recipient');self.third=User.objects.create_user('gift-other')
        self.client.force_login(self.me);self.other=Client();self.other.force_login(self.peer)
        self.member=allowance(self.me);self.member.extra_balance=Decimal('1');self.member.save()
        self.key=f'dm:{self.peer.pk}'

    def send(self,**kwargs):
        self.data={'request_id':str(uuid.uuid4()),'kind':'transfer','mode':'equal','points':'10','count':'1','channel':self.key,'confirm':'yes','greeting':'hello'}
        self.data.update(kwargs)
        return self.client.post(reverse('point_gift_send'),self.data)

    def gift(self): return PointGift.objects.latest('created_at')
    def claim(self,gift,client=None): return (client or self.other).post(reverse('point_gift_claim',args=[gift.pk]),{'confirm':'yes'})
    def balance(self,user): return Allowance.objects.get(user=user).extra_balance
    def credit(self,user): return allowance(user).extra_balance

    def test_transfer_escrow_and_claim_conserve_points(self):
        response=self.send();self.assertEqual(response.status_code,201);gift=self.gift()
        self.assertEqual(response.json()['message']['gift']['points'],'10.00000000')
        self.assertEqual(self.balance(self.me),Decimal('.9'))
        self.assertEqual(self.claim(gift).status_code,200)
        self.assertEqual(self.balance(self.peer),Decimal('.1'));gift.refresh_from_db()
        self.assertEqual(gift.remaining_cny,0);self.assertIsNotNone(gift.closed_at)
        self.assertEqual(self.balance(self.me)+self.balance(self.peer),1)

    def test_send_idempotency_and_changed_payload_rejected(self):
        self.send();first=self.data.copy();gift=self.gift()
        self.assertEqual(self.client.post(reverse('point_gift_send'),first).status_code,200)
        self.assertEqual(PointGift.objects.count(),1);self.assertEqual(self.balance(self.me),Decimal('.9'))
        first['points']='20';self.assertEqual(self.client.post(reverse('point_gift_send'),first).status_code,400)
        self.assertEqual(PointGift.objects.count(),1)

    def test_claim_idempotency(self):
        self.send();gift=self.gift();self.claim(gift);self.claim(gift)
        self.assertEqual(self.balance(self.peer),Decimal('.1'));self.assertEqual(gift.receipts.count(),1)
        notes=ChatMessage.objects.filter(kind='notice',system_gift=gift)
        self.assertEqual(notes.count(),1);self.assertEqual(notes.get().recipient_id,self.me.pk)
        self.assertEqual(self.claim(gift).json()['state_label'],'已收款')
        self.assertTrue(self.claim(gift).json()['dimmed'])

    def test_weekly_base_budget_is_not_transferable(self):
        self.member.extra_balance=0;self.member.save()
        response=self.send(points='1');self.assertEqual(response.status_code,400)
        self.assertIn('每周基础额度',response.json()['error']);self.assertEqual(PointGift.objects.count(),0)
        self.assertEqual(summary(self.me)['member_week']['remaining_points'],'1000.000000')

    def test_reserved_points_cannot_be_transferred(self):
        self.member.extra_reserved=Decimal('.95');self.member.save()
        self.assertEqual(self.send(points='10').status_code,400)
        self.assertEqual(self.balance(self.me),1)

    def test_insufficient_and_invalid_amounts_leave_everything_unchanged(self):
        for amount in ('101','0','-1','NaN','Infinity','.0000001','1e9999'):
            self.assertEqual(self.send(points=amount).status_code,400)
        self.assertEqual(self.balance(self.me),1);self.assertEqual(PointGift.objects.count(),0);self.assertEqual(ChatMessage.objects.count(),0)

    def test_claim_permissions_and_self_transfer_rejected(self):
        self.send();gift=self.gift();third=Client();third.force_login(self.third)
        self.assertEqual(self.claim(gift,third).status_code,403)
        self.assertEqual(self.claim(gift,self.client).status_code,403)
        self.assertEqual(self.client.post(reverse('point_gift_send'),{**self.data,'request_id':str(uuid.uuid4()),'channel':f'dm:{self.me.pk}'}).status_code,403)
        self.assertEqual(self.balance(self.me),Decimal('.9'))

    def test_disabled_and_normal_users_cannot_send_or_claim(self):
        self.send();gift=self.gift();self.peer.is_active=False;self.peer.save()
        self.assertNotEqual(self.claim(gift).status_code,200)
        self.peer.is_active=True;self.peer.save();MemberProfile.objects.create(user=self.peer,tier='normal')
        self.assertNotEqual(self.claim(gift).status_code,200)
        self.member.enabled=False;self.member.save();self.assertEqual(self.send(kind='packet',channel='developers').status_code,400)

    def test_equal_group_packet_conserves_remainder(self):
        self.send(kind='packet',channel='developers',points='.00001',count='3');gift=self.gift()
        third=Client();third.force_login(self.third)
        for client in (self.client,self.other,third): self.assertEqual(self.claim(gift,client).status_code,200)
        amounts=list(gift.receipts.values_list('amount_cny',flat=True))
        self.assertEqual(sum(amounts),Decimal('.0000001'));self.assertEqual(max(amounts)-min(amounts),Decimal('.00000001'))
        self.assertEqual(self.balance(self.me)+self.balance(self.peer)+self.balance(self.third),1)

    def test_random_group_packet_conserves_balance_and_each_share_positive(self):
        self.send(kind='packet',mode='random',channel='developers',points='60',count='3');gift=self.gift()
        third=Client();third.force_login(self.third)
        for client in (self.client,self.other,third): self.assertEqual(self.claim(gift,client).status_code,200)
        self.assertEqual(sum(gift.receipts.values_list('amount_cny',flat=True)),Decimal('.6'))
        self.assertTrue(all(v>0 for v in gift.receipts.values_list('amount_cny',flat=True)))
        self.assertEqual(self.balance(self.me)+self.balance(self.peer)+self.balance(self.third),1)

    def test_expired_and_partially_claimed_packet_refunds_only_remainder(self):
        self.send(kind='packet',mode='equal',channel='developers',points='30',count='3');gift=self.gift();self.claim(gift)
        PointGift.objects.filter(pk=gift.pk).update(expires_at=timezone.now()-timezone.timedelta(seconds=1))
        self.assertEqual(expire_gifts(),1);self.assertEqual(expire_gifts(),0)
        self.assertEqual(self.balance(self.me),Decimal('.9'));self.assertEqual(self.balance(self.peer),Decimal('.1'))
        self.assertEqual(self.claim(gift).status_code,200) # Already claimed: idempotent receipt, no additional credit.
        third=Client();third.force_login(self.third);self.assertEqual(self.claim(gift,third).status_code,400)

    def test_expired_transfer_refunds_on_wallet_or_summary(self):
        self.send();gift=self.gift();PointGift.objects.filter(pk=gift.pk).update(expires_at=timezone.now()-timezone.timedelta(seconds=1))
        self.assertEqual(summary(self.me)['extra']['remaining_points'],'100.00000000')
        self.assertEqual(self.claim(gift).status_code,400);self.assertEqual(self.balance(self.me),1)

    def test_transfer_return_before_claim_and_cannot_refund_after_claim(self):
        self.send();gift=self.gift();url=reverse('point_gift_detail',args=[gift.pk])
        self.assertEqual(self.other.post(url,{'action':'refund','confirm':'yes'}).status_code,400)
        self.client.post(url,{'action':'refund','confirm':'yes'});self.client.post(url,{'action':'refund','confirm':'yes'})
        self.assertEqual(self.balance(self.me),1);self.assertEqual(self.claim(gift).status_code,400)
        self.send();gift=self.gift();self.claim(gift);self.client.post(reverse('point_gift_detail',args=[gift.pk]),{'action':'refund','confirm':'yes'})
        self.assertEqual(self.balance(self.me),Decimal('.9'));self.assertEqual(self.balance(self.peer),Decimal('.1'))

    def test_chat_delete_clear_and_remove_cannot_erase_gift_ledger(self):
        self.send();gift=self.gift()
        self.assertEqual(self.client.post(reverse('message_action',args=[gift.message_id]),{'action':'withdraw'}).status_code,400)
        self.client.post(reverse('message_action',args=[gift.message_id]),{'action':'delete'})
        self.client.post(reverse('messages_manage'),{'action':'clear','channel':self.key,'confirm':'yes'})
        self.assertEqual(self.claim(gift).status_code,200);self.assertTrue(PointGift.objects.filter(pk=gift.pk).exists())
        self.assertEqual(len(self.client.get(reverse('point_wallet')).json()['gifts']),1)

    def test_no_group_transfers_invalid_counts_or_missing_confirmation(self):
        for args in ({'channel':'developers'},{'count':'2'},{'count':'101'},{'mode':'random'},{'confirm':''},{'kind':'packet','channel':'developers','count':'3','points':'.000001'}):
            self.assertEqual(self.send(**args).status_code,400)
        self.assertEqual(self.balance(self.me),1)

    def test_gift_claim_updates_poll_and_group_search(self):
        self.send();gift=self.gift();self.claim(gift)
        data=self.client.get(reverse('messages_private_poll',args=[self.peer.pk]),{'after':gift.message_id,'known':str(gift.message_id)}).json()
        self.assertEqual(data['updates'][0]['gift']['status'],'已领完')

    def test_gifting_does_not_create_api_usage_or_weekly_spending(self):
        from .models import Call
        self.send();self.claim(self.gift());self.assertEqual(Call.objects.count(),0)
        self.assertEqual(BudgetWeek.objects.count(),0)

    def test_csrf_on_send_and_claim(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.me)
        self.assertEqual(secure.post(reverse('point_gift_send'),{}).status_code,403)
        self.send();self.assertEqual(secure.post(reverse('point_gift_claim',args=[self.gift().pk]),{'confirm':'yes'}).status_code,403)

    def test_capture_gift_page(self):
        self.send();response=self.other.get(reverse('messages_private',args=[self.me.pk]));self.assertEqual(response.status_code,200)
        self.assertContains(response,'point-gift-card');capture=os.environ.get('WORKBENCH_CAPTURE_UI')
        if capture: Path(capture,'gifts.html').write_bytes(response.content)
