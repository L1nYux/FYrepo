"""Opt-in discovery contacts share the participant-owned private inbox."""
import re
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import AccountNotice, ApplicantProfile, PersonalMessage, RecruitmentOffer, Team


def available(user, peer):
    if PersonalMessage.objects.filter(Q(sender=user,recipient=peer)|Q(sender=peer,recipient=user),contact_source='discovery').exists():
        return True
    profile=ApplicantProfile.objects.filter(user=peer,listed=True).first()
    if profile and not profile.blocked_teams.filter(memberships__user=user,memberships__active=True,memberships__deleted_at__isnull=True).exists():
        return True
    return Team.objects.filter(owner=peer,active=True,listed=True,solo_owner__isnull=True).exclude(recruitment_mode='closed').exists()


def deliver(notice):
    peer=None
    if notice.application_id:
        item=notice.application
        peer=item.reviewed_by if notice.user_id==item.applicant_id and item.reviewed_by_id else item.opening.team.owner if notice.user_id==item.applicant_id else item.applicant
    else:
        match=re.fullmatch(r'/discover/offers/([1-9][0-9]*)/',notice.target_url)
        offer=RecruitmentOffer.objects.filter(pk=match[1]).select_related('issued_by','recipient').first() if match else None
        if offer:peer=offer.issued_by if notice.user_id==offer.recipient_id else offer.recipient
    if not peer or peer.pk==notice.user_id or not peer.is_active or not notice.user.is_active:
        return
    from .models import ConversationPreference
    if ConversationPreference.objects.filter(Q(user=notice.user,channel='person:'+str(peer.pk),blocked=True)|Q(user=peer,channel='person:'+str(notice.user_id),blocked=True)).exists():
        return
    PersonalMessage.objects.get_or_create(notice=notice,defaults={'sender':peer,'recipient':notice.user,
        'body':(notice.title+'\n'+notice.body).strip()[:2000],'relation_verified':True,'contact_source':'discovery',
        'references':[{'kind':'discovery-notice','pk':notice.pk}]})


@receiver(post_save,sender=AccountNotice)
def new_notice(sender,instance,created=False,raw=False,**kwargs):
    if created and not raw:deliver(instance)
