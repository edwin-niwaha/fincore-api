from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.views.generic import ListView

from .forms import TransactionLedgerFilterForm
from .models import Transaction
from .selectors import transactions_for_user

ZERO_DECIMAL = Decimal("0.00")


class TransactionLedgerView(LoginRequiredMixin, ListView):
    context_object_name = "transactions"
    paginate_by = 25
    template_name = "transactions/ledger.html"

    def _base_queryset(self):
        if not hasattr(self, "_scoped_queryset"):
            self._scoped_queryset = transactions_for_user(self.request.user)
        return self._scoped_queryset

    def _build_filter_form(self):
        if not hasattr(self, "_filter_form"):
            self._filter_form = TransactionLedgerFilterForm(
                self.request.GET or None,
                transactions_queryset=self._base_queryset(),
            )
        return self._filter_form

    def get_queryset(self):
        queryset = self._base_queryset()
        form = self._build_filter_form()

        if form.is_valid():
            query = form.cleaned_data.get("q")
            institution = form.cleaned_data.get("institution")
            branch = form.cleaned_data.get("branch")
            client = form.cleaned_data.get("client")
            category = form.cleaned_data.get("category")
            direction = form.cleaned_data.get("direction")
            date_from = form.cleaned_data.get("date_from")
            date_to = form.cleaned_data.get("date_to")
            self.selected_transaction_id = form.cleaned_data.get("selected")

            if query:
                queryset = queryset.filter(
                    Q(reference__icontains=query)
                    | Q(description__icontains=query)
                    | Q(client__member_number__icontains=query)
                    | Q(client__first_name__icontains=query)
                    | Q(client__last_name__icontains=query)
                    | Q(branch__name__icontains=query)
                    | Q(institution__name__icontains=query)
                )
            if institution:
                queryset = queryset.filter(institution=institution)
            if branch:
                queryset = queryset.filter(branch=branch)
            if client:
                queryset = queryset.filter(client=client)
            if category:
                queryset = queryset.filter(category=category)
            if direction:
                queryset = queryset.filter(direction=direction)
            if date_from:
                queryset = queryset.filter(created_at__date__gte=date_from)
            if date_to:
                queryset = queryset.filter(created_at__date__lte=date_to)
        else:
            self.selected_transaction_id = (self.request.GET.get("selected") or "").strip()

        self.filtered_queryset = queryset
        return queryset

    def _summary(self):
        return self.filtered_queryset.aggregate(
            row_count=Count("id"),
            total_credits=Coalesce(
                Sum("amount", filter=Q(direction=Transaction.Direction.CREDIT)),
                Value(ZERO_DECIMAL),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            total_debits=Coalesce(
                Sum("amount", filter=Q(direction=Transaction.Direction.DEBIT)),
                Value(ZERO_DECIMAL),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )

    def _selected_transaction(self):
        if not self.selected_transaction_id:
            return None
        return self._base_queryset().filter(pk=self.selected_transaction_id).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = self._summary()
        summary["net_flow"] = summary["total_credits"] - summary["total_debits"]

        query_without_selected = self.request.GET.copy()
        query_without_selected.pop("selected", None)

        context.update(
            {
                "page_title": "Transaction Ledger",
                "filter_form": self._build_filter_form(),
                "summary": summary,
                "selected_transaction": self._selected_transaction(),
                "base_querystring": query_without_selected.urlencode(),
                "generated_at": timezone.now(),
                "is_export_ready": True,
            }
        )
        return context
