from rest_framework import viewsets

class ReadWriteByRoleMixin(viewsets.ModelViewSet):
    staff_only_actions = {"create", "update", "partial_update", "destroy"}
