from collections.abc import Mapping, Sequence
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.common.permissions import CASH_ROLES

from .forms import SavingsOperationForm
from .models import SavingsAccount
from .selectors import savings_accounts_for_user
from .services import SavingsService

ZERO_DECIMAL = Decimal("0.00")


def flatten_error_messages(detail):
    if isinstance(detail, Mapping):
        messages_list = []
        for value in detail.values():
            messages_list.extend(flatten_error_messages(value))
        return messages_list

    if isinstance(detail, Sequence) and not isinstance(detail, str):
        messages_list = []
        for value in detail:
            messages_list.extend(flatten_error_messages(value))
        return messages_list

    return [str(detail)]


class SavingsWebScopeMixin(LoginRequiredMixin):
    def base_queryset(self):
        return savings_accounts_for_user(self.request.user).select_related(
            "client",
            "client__branch",
            "client__institution",
        )

    def can_manage_cash(self):
        return self.request.user.is_authenticated and self.request.user.role in CASH_ROLES


class SavingsAccountListView(SavingsWebScopeMixin, ListView):
    model = SavingsAccount
    context_object_name = "accounts"
    paginate_by = 18
    template_name = "savings/account_list.html"

    def get_queryset(self):
        queryset = self.base_queryset()
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(account_number__icontains=query)
                | Q(client__member_number__icontains=query)
                | Q(client__first_name__icontains=query)
                | Q(client__last_name__icontains=query)
                | Q(client__branch__name__icontains=query)
            )
        self.filtered_queryset = queryset
        self.search_query = query
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = self.filtered_queryset.aggregate(
            account_count=Count("id"),
            active_count=Count("id", filter=Q(status="active")),
            total_balance=Coalesce(
                Sum("balance"),
                Value(ZERO_DECIMAL),
            ),
        )
        context.update(
            {
                "page_title": "Savings Accounts",
                "search_query": self.search_query,
                "summary": summary,
                "can_manage_cash": self.can_manage_cash(),
            }
        )
        return context


class SavingsAccountDetailView(SavingsWebScopeMixin, DetailView):
    context_object_name = "account"
    template_name = "savings/account_detail.html"

    def get_queryset(self):
        return self.base_queryset().prefetch_related("transactions__performed_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        account = self.object
        context.setdefault("page_title", account.account_number)
        context.setdefault("can_manage_cash", self.can_manage_cash())
        context.setdefault("active_modal", None)
        context.setdefault("deposit_form", SavingsOperationForm())
        context.setdefault("withdraw_form", SavingsOperationForm())
        context["transaction_history"] = account.transactions.select_related(
            "performed_by"
        ).order_by("-created_at")
        return context


class SavingsAccountOperationView(SavingsWebScopeMixin, View):
    action_name = ""
    action_label = ""
    form_context_name = ""

    def get_account(self, request, pk):
        return get_object_or_404(
            self.base_queryset().prefetch_related("transactions__performed_by"),
            pk=pk,
        )

    def post(self, request, pk):
        if not self.can_manage_cash():
            raise PermissionDenied("You do not have permission to perform cash operations.")

        account = self.get_account(request, pk)
        form = SavingsOperationForm(request.POST)
        if not form.is_valid():
            messages.error(request, f"{self.action_label} failed. Please review the form.")
            return self.render_detail(request, account, form, status=400)

        service_method = getattr(SavingsService, self.action_name)
        try:
            service_method(
                account=account,
                performed_by=request.user,
                **form.cleaned_data,
            )
        except DRFValidationError as exc:
            for message in flatten_error_messages(exc.detail):
                messages.error(request, message)
            return self.render_detail(request, account, form, status=400)

        messages.success(
            request,
            f"{self.action_label} recorded for {account.account_number}.",
        )
        return redirect("savings_web:account-detail", pk=account.pk)

    def render_detail(self, request, account, form, *, status):
        account = self.get_account(request, account.pk)
        detail_view = SavingsAccountDetailView()
        detail_view.request = request
        detail_view.object = account
        page_context = detail_view.get_context_data(
            **{
                self.form_context_name: form,
                "active_modal": self.action_name,
                "can_manage_cash": self.can_manage_cash(),
                "page_title": account.account_number,
            }
        )
        return render(request, "savings/account_detail.html", page_context, status=status)


class SavingsAccountDepositView(SavingsAccountOperationView):
    action_name = "deposit"
    action_label = "Deposit"
    form_context_name = "deposit_form"


class SavingsAccountWithdrawalView(SavingsAccountOperationView):
    action_name = "withdraw"
    action_label = "Withdrawal"
    form_context_name = "withdraw_form"
