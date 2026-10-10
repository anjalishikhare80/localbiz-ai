from django import forms

from core.forms import StyledFormMixin

from .models import Business, BusinessMember


class BusinessCreateForm(StyledFormMixin, forms.Form):
    name = forms.CharField(max_length=150)
    business_type = forms.ChoiceField(choices=Business.BusinessType.choices)


class BusinessSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Business
        fields = ["name", "business_type", "address", "phone", "tax_id", "tax_rate", "invoice_prefix"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class MemberCreateForm(StyledFormMixin, forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput, min_length=8, help_text="Ignored if this e-mail already has an account.")
    role = forms.ChoiceField(choices=[(BusinessMember.Role.MANAGER, "Manager"), (BusinessMember.Role.EMPLOYEE, "Employee")])


class MemberUpdateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BusinessMember
        fields = ["role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [(BusinessMember.Role.MANAGER, "Manager"), (BusinessMember.Role.EMPLOYEE, "Employee")]
