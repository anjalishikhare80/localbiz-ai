from django import forms


def style_fields(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault("class", "form-select")
        elif isinstance(widget, forms.FileInput):
            widget.attrs.setdefault("class", "form-control")
        else:
            widget.attrs.setdefault("class", "form-control")


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class TenantModelForm(StyledFormMixin, forms.ModelForm):
    """
    ModelForm that is locked to one business.

    * every ForeignKey dropdown is restricted to that business's rows, so a
      forged POST containing another tenant's ID fails validation (IDOR guard);
    * unique constraints that include ``business`` are validated (Django would
      otherwise skip them because ``business`` is not a form field).
    """

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if business is not None:
            self.instance.business = business
            for field in self.fields.values():
                qs = getattr(field, "queryset", None)
                if qs is not None and hasattr(qs.model, "business"):
                    field.queryset = qs.filter(business=business)

    def _get_validation_exclusions(self):
        exclude = super()._get_validation_exclusions()
        exclude.discard("business")
        return exclude
