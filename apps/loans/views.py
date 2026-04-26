from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied
from apps.clients.selectors import clients_for_user
from apps.common.permissions import IsLoanRole, IsStaffRole, IsCashRole
from .models import LoanProduct, LoanRepayment
from .selectors import loans_for_user
from .serializers import LoanActionSerializer, LoanApplicationSerializer, LoanProductSerializer, LoanRepaymentCreateSerializer, LoanRepaymentSerializer
from .services import LoanService

class LoanProductViewSet(viewsets.ModelViewSet):
    queryset = LoanProduct.objects.select_related("institution")
    serializer_class = LoanProductSerializer
    permission_classes = [IsStaffRole]
    filterset_fields = ["institution", "is_active"]
    search_fields = ["name", "code"]

class LoanApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = LoanApplicationSerializer
    filterset_fields = ["client", "product", "status"]
    search_fields = ["client__member_number", "client__first_name", "client__last_name", "purpose"]

    def get_queryset(self):
        return loans_for_user(self.request.user)

    def perform_create(self, serializer):
        client = serializer.validated_data.get("client")
        if not clients_for_user(self.request.user).filter(pk=getattr(client, "pk", None)).exists():
            raise PermissionDenied("You cannot create a loan application for this client.")
        serializer.save()

    @decorators.action(detail=True, methods=["post"], permission_classes=[IsLoanRole])
    def approve(self, request, pk=None):
        loan = LoanService.approve(loan=self.get_object(), user=request.user)
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"], permission_classes=[IsLoanRole])
    def reject(self, request, pk=None):
        serializer = LoanActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = LoanService.reject(loan=self.get_object(), user=request.user, reason=serializer.validated_data.get("reason", ""))
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"], permission_classes=[IsCashRole])
    def disburse(self, request, pk=None):
        serializer = LoanActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = LoanService.disburse(loan=self.get_object(), user=request.user, reference=serializer.validated_data.get("reference") or f"DISB-{pk}")
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"], permission_classes=[IsCashRole])
    def repay(self, request, pk=None):
        serializer = LoanRepaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repayment = LoanService.repay(loan=self.get_object(), received_by=request.user, **serializer.validated_data)
        return response.Response(LoanRepaymentSerializer(repayment).data, status=201)

class LoanRepaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LoanRepaymentSerializer
    def get_queryset(self):
        loan_ids = loans_for_user(self.request.user).values_list("id", flat=True)
        return LoanRepayment.objects.filter(loan_id__in=loan_ids).select_related("loan", "received_by")
