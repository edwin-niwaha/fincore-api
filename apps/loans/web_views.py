from collections.abc import Mapping, Sequence
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.common.permissions import CASH_ROLES, LOAN_ROLES

from .forms import LoanDisburseForm, LoanRejectForm, LoanRepaymentForm
from .models import LoanApplication
from .selectors import loan_products_for_user, loans_for_user
from .services import LoanService

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


class LoansWebScopeMixin(LoginRequiredMixin):
    def base_products_queryset(self):
        return loan_products_for_user(self.request.user).select_related("institution")

    def base_loans_queryset(self):
        return loans_for_user(self.request.user).select_related(
            "client",
            "client__branch",
            "client__institution",
            "product",
            "approved_by",
        )

    def can_manage_loans(self):
        return self.request.user.is_authenticated and self.request.user.role in LOAN_ROLES

    def can_manage_cash(self):
        return self.request.user.is_authenticated and self.request.user.role in CASH_ROLES

    def loan_permissions(self, loan):
        return {
            "can_manage_loans": self.can_manage_loans(),
            "can_manage_cash": self.can_manage_cash(),
            "can_approve_or_reject": self.can_manage_loans()
            and loan.status == LoanApplication.Status.PENDING,
            "can_disburse": self.can_manage_cash()
            and loan.status == LoanApplication.Status.APPROVED,
            "can_repay": self.can_manage_cash()
            and loan.status == LoanApplication.Status.DISBURSED,
        }

    def build_detail_context(
        self,
        *,
        loan,
        reject_form=None,
        disburse_form=None,
        repayment_form=None,
        active_panel=None,
    ):
        permissions = self.loan_permissions(loan)
        return {
            "page_title": f"Loan {loan.client.member_number}",
            "loan": loan,
            "schedule_rows": loan.schedule.order_by("due_date", "created_at"),
            "repayment_rows": loan.repayments.select_related("received_by").order_by("-created_at"),
            "active_panel": active_panel,
            "reject_form": reject_form or LoanRejectForm(),
            "disburse_form": disburse_form or LoanDisburseForm(),
            "repayment_form": repayment_form or LoanRepaymentForm(),
            **permissions,
        }


class LoanProductListView(LoansWebScopeMixin, ListView):
    context_object_name = "products"
    paginate_by = 18
    template_name = "loans/product_list.html"

    def get_queryset(self):
        queryset = self.base_products_queryset()
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(code__icontains=query)
                | Q(institution__name__icontains=query)
            )
        self.filtered_queryset = queryset
        self.search_query = query
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = self.filtered_queryset.aggregate(
            product_count=Count("id"),
            active_count=Count("id", filter=Q(is_active=True)),
            portfolio_ceiling=Coalesce(
                Sum("max_amount"),
                Value(ZERO_DECIMAL),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        context.update(
            {
                "page_title": "Loan Products",
                "search_query": self.search_query,
                "summary": summary,
            }
        )
        return context


class LoanApplicationListView(LoansWebScopeMixin, ListView):
    context_object_name = "loans"
    paginate_by = 18
    template_name = "loans/application_list.html"

    def get_queryset(self):
        queryset = self.base_loans_queryset()
        query = self.request.GET.get("q", "").strip()
        status_filter = self.request.GET.get("status", "").strip()

        if query:
            queryset = queryset.filter(
                Q(client__member_number__icontains=query)
                | Q(client__first_name__icontains=query)
                | Q(client__last_name__icontains=query)
                | Q(product__name__icontains=query)
                | Q(product__code__icontains=query)
                | Q(purpose__icontains=query)
            )
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        self.filtered_queryset = queryset
        self.search_query = query
        self.status_filter = status_filter
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = self.filtered_queryset.aggregate(
            application_count=Count("id"),
            pending_count=Count("id", filter=Q(status=LoanApplication.Status.PENDING)),
            disbursed_count=Count("id", filter=Q(status=LoanApplication.Status.DISBURSED)),
            outstanding_principal=Coalesce(
                Sum("principal_balance"),
                Value(ZERO_DECIMAL),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        context.update(
            {
                "page_title": "Loan Applications",
                "search_query": self.search_query,
                "status_filter": self.status_filter,
                "summary": summary,
                "status_options": LoanApplication.Status.choices,
            }
        )
        return context


class LoanApplicationDetailView(LoansWebScopeMixin, DetailView):
    context_object_name = "loan"
    template_name = "loans/application_detail.html"

    def get_queryset(self):
        return self.base_loans_queryset().prefetch_related("schedule", "repayments__received_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            self.build_detail_context(
                loan=self.object,
                reject_form=kwargs.get("reject_form"),
                disburse_form=kwargs.get("disburse_form"),
                repayment_form=kwargs.get("repayment_form"),
                active_panel=kwargs.get("active_panel"),
            )
        )
        return context


class LoanApplicationActionView(LoansWebScopeMixin, View):
    form_class = None
    required_capability = ""
    success_message = ""
    active_panel = None

    def get_loan(self, request, pk):
        return get_object_or_404(
            self.base_loans_queryset().prefetch_related("schedule", "repayments__received_by"),
            pk=pk,
        )

    def has_permission(self, loan):
        permissions = self.loan_permissions(loan)
        return permissions.get(self.required_capability, False)

    def render_detail(
        self,
        request,
        loan,
        *,
        status_code=400,
        reject_form=None,
        disburse_form=None,
        repayment_form=None,
        active_panel=None,
    ):
        loan = self.get_loan(request, loan.pk)
        context = self.build_detail_context(
            loan=loan,
            reject_form=reject_form,
            disburse_form=disburse_form,
            repayment_form=repayment_form,
            active_panel=active_panel,
        )
        return render(request, "loans/application_detail.html", context, status=status_code)

    def post(self, request, pk):
        loan = self.get_loan(request, pk)
        if not self.has_permission(loan):
            raise PermissionDenied("You do not have permission to perform this loan action.")

        form = self.form_class(request.POST) if self.form_class else None
        if form is not None and not form.is_valid():
            messages.error(request, "Please review the form and try again.")
            return self.render_form_errors(request, loan, form)

        try:
            result = self.perform_action(loan, form)
        except DRFValidationError as exc:
            for message in flatten_error_messages(exc.detail):
                messages.error(request, message)
            return self.render_form_errors(request, loan, form)

        messages.success(request, self.success_message.format(loan=result))
        return redirect("loans_web:application-detail", pk=loan.pk)

    def render_form_errors(self, request, loan, form):
        return self.render_detail(
            request,
            loan,
            reject_form=form if self.active_panel == "reject" else None,
            disburse_form=form if self.active_panel == "disburse" else None,
            repayment_form=form if self.active_panel == "repay" else None,
            active_panel=self.active_panel,
        )

    def perform_action(self, loan, form):
        raise NotImplementedError


class LoanApplicationApproveView(LoanApplicationActionView):
    required_capability = "can_approve_or_reject"
    success_message = "Loan approved for {loan.client.member_number}."

    def perform_action(self, loan, form):
        return LoanService.approve(loan=loan, user=self.request.user)


class LoanApplicationRejectView(LoanApplicationActionView):
    form_class = LoanRejectForm
    required_capability = "can_approve_or_reject"
    success_message = "Loan rejected for {loan.client.member_number}."
    active_panel = "reject"

    def perform_action(self, loan, form):
        return LoanService.reject(
            loan=loan,
            user=self.request.user,
            reason=form.cleaned_data["reason"],
        )


class LoanApplicationDisburseView(LoanApplicationActionView):
    form_class = LoanDisburseForm
    required_capability = "can_disburse"
    success_message = "Loan disbursed to {loan.client.member_number}."
    active_panel = "disburse"

    def perform_action(self, loan, form):
        return LoanService.disburse(
            loan=loan,
            user=self.request.user,
            reference=form.cleaned_data["reference"],
        )


class LoanApplicationRepaymentView(LoanApplicationActionView):
    form_class = LoanRepaymentForm
    required_capability = "can_repay"
    success_message = "Repayment recorded for {loan.client.member_number}."
    active_panel = "repay"

    def perform_action(self, loan, form):
        LoanService.repay(
            loan=loan,
            amount=form.cleaned_data["amount"],
            reference=form.cleaned_data["reference"],
            received_by=self.request.user,
        )
        return self.get_loan(self.request, loan.pk)
