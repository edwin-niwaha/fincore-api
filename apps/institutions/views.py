from rest_framework import viewsets
from apps.common.permissions import IsAdminRole, IsStaffRole
from .models import Branch, Institution
from .serializers import BranchSerializer, InstitutionSerializer

class InstitutionViewSet(viewsets.ModelViewSet):
    queryset = Institution.objects.all()
    serializer_class = InstitutionSerializer
    permission_classes = [IsAdminRole]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "created_at"]

class BranchViewSet(viewsets.ModelViewSet):
    queryset = Branch.objects.select_related("institution")
    serializer_class = BranchSerializer
    permission_classes = [IsStaffRole]
    filterset_fields = ["institution", "status"]
    search_fields = ["name", "code"]
