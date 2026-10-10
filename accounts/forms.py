from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from businesses.models import Business
from core.forms import style_fields

from .models import User


class RegisterForm(UserCreationForm):
    business_name = forms.CharField(max_length=150, label="Business name")
    business_type = forms.ChoiceField(choices=Business.BusinessType.choices)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class StyledAuthForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)
