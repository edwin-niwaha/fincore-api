from decimal import Decimal

from django import forms


class LoanRejectForm(forms.Form):
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Why is this application being rejected?",
            }
        ),
    )

    def clean_reason(self):
        return self.cleaned_data["reason"].strip()


class LoanDisburseForm(forms.Form):
    reference = forms.CharField(
        max_length=80,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Cash voucher or disbursement reference",
            }
        ),
    )

    def clean_reference(self):
        reference = self.cleaned_data["reference"].strip()
        if not reference:
            raise forms.ValidationError("Reference is required.")
        return reference


class LoanRepaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(
            attrs={
                "step": "0.01",
                "min": "0.01",
                "placeholder": "0.00",
            }
        ),
    )
    reference = forms.CharField(
        max_length=80,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Receipt or repayment reference",
            }
        ),
    )

    def clean_reference(self):
        reference = self.cleaned_data["reference"].strip()
        if not reference:
            raise forms.ValidationError("Reference is required.")
        return reference
