from django import forms

from apps.clients.models import Client
from apps.institutions.models import Branch, Institution

from .models import Transaction


class TransactionLedgerFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "Search reference, member, branch, or description"}
        ),
    )
    institution = forms.ModelChoiceField(
        queryset=Institution.objects.none(),
        required=False,
        empty_label="All institutions",
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.none(),
        required=False,
        empty_label="All branches",
    )
    client = forms.ModelChoiceField(
        queryset=Client.objects.none(),
        required=False,
        empty_label="All clients",
    )
    category = forms.ChoiceField(required=False)
    direction = forms.ChoiceField(
        required=False,
        choices=[("", "All directions"), *Transaction.Direction.choices],
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    selected = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, transactions_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = transactions_queryset
        if queryset is None:
            queryset = Transaction.objects.none()

        self.fields["institution"].queryset = Institution.objects.filter(
            pk__in=queryset.order_by().values_list("institution_id", flat=True).distinct()
        ).order_by("name")
        self.fields["branch"].queryset = Branch.objects.filter(
            pk__in=queryset.order_by().values_list("branch_id", flat=True).distinct()
        ).order_by("name")
        self.fields["client"].queryset = Client.objects.filter(
            pk__in=queryset.order_by().values_list("client_id", flat=True).distinct()
        ).order_by("member_number")

        category_values = list(
            queryset.order_by().values_list("category", flat=True).distinct()
        )
        self.fields["category"].choices = [("", "All categories")] + [
            (value, value.replace("_", " ").title()) for value in category_values
        ]

    def clean_q(self):
        return self.cleaned_data["q"].strip()

    def clean_selected(self):
        return self.cleaned_data["selected"].strip()
