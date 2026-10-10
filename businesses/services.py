from django.contrib.auth import get_user_model
from django.db import transaction

from audit.services import log as audit_log
from core.exceptions import BusinessRuleError

from .models import Business, BusinessMember

User = get_user_model()


@transaction.atomic
def create_business_with_owner(*, user, name, business_type=Business.BusinessType.OTHER, request=None):
    from finance.services import create_default_categories

    business = Business.objects.create(name=name, business_type=business_type)
    BusinessMember.objects.create(user=user, business=business, role=BusinessMember.Role.OWNER)
    create_default_categories(business)
    audit_log(business=business, user=user, action="business.created", entity=business, request=request)
    return business


@transaction.atomic
def add_member(*, business, actor, username, email, password, role, request=None):
    """Create a login for a new team member (or attach an existing account by e-mail)."""
    if role not in (BusinessMember.Role.MANAGER, BusinessMember.Role.EMPLOYEE):
        raise BusinessRuleError("Team members can only be Manager or Employee.")
    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        user = existing
    else:
        if User.objects.filter(username__iexact=username).exists():
            raise BusinessRuleError("That username is already taken.")
        user = User.objects.create_user(username=username, email=email, password=password)
    if BusinessMember.objects.filter(user=user, business=business).exists():
        raise BusinessRuleError("This person is already a member of the business.")
    member = BusinessMember.objects.create(user=user, business=business, role=role)
    audit_log(
        business=business, user=actor, action="member.added", entity=member,
        metadata={"member_user": user.username, "role": role}, request=request,
    )
    return member
