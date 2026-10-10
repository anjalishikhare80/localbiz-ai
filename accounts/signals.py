from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from audit.services import log as audit_log


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    membership = user.memberships.filter(is_active=True).select_related("business").first()
    audit_log(
        business=membership.business if membership else None,
        user=user, action="user.login", entity_type="user", entity_id=user.pk, request=request,
    )
