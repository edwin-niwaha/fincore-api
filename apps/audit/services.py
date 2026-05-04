class AuditService:
    @staticmethod
    def _normalize_metadata(metadata):
        if metadata is None:
            return {}
        if isinstance(metadata, dict):
            return metadata
        return {"value": metadata}

    @staticmethod
    def _derive_scope(*, user=None, institution=None, branch=None):
        resolved_institution = institution
        resolved_branch = branch

        if resolved_branch is None and getattr(user, "branch_id", None):
            resolved_branch = getattr(user, "branch", None)

        if resolved_branch is None:
            client_profile = getattr(user, "client_profile", None) if user else None
            if client_profile and getattr(client_profile, "branch_id", None):
                resolved_branch = client_profile.branch

        if resolved_institution is None and getattr(user, "institution_id", None):
            resolved_institution = getattr(user, "institution", None)

        if resolved_institution is None:
            client_profile = getattr(user, "client_profile", None) if user else None
            if client_profile and getattr(client_profile, "institution_id", None):
                resolved_institution = client_profile.institution

        if resolved_institution is None and resolved_branch is not None:
            resolved_institution = getattr(resolved_branch, "institution", None)

        return resolved_institution, resolved_branch

    @staticmethod
    def _derive_action_parts(*, action, module=None, resource=None, event=None):
        parts = [part.strip() for part in str(action or "").split(".") if part.strip()]
        resolved_module = module or (parts[0] if len(parts) >= 1 else "")
        resolved_resource = resource or (parts[1] if len(parts) >= 2 else "")
        resolved_event = event or (".".join(parts[2:]) if len(parts) >= 3 else "")
        return resolved_module, resolved_resource, resolved_event

    @staticmethod
    def _resolve_ip_address(request):
        if request is None:
            return None

        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip() or None

        return request.META.get("REMOTE_ADDR")

    @staticmethod
    def log(
        *,
        user=None,
        action,
        target="",
        metadata=None,
        ip_address=None,
        request=None,
        institution=None,
        branch=None,
        module=None,
        resource=None,
        event=None,
        request_path="",
    ):
        from .models import AuditLog

        resolved_user = user if getattr(user, "is_authenticated", False) else None
        resolved_institution, resolved_branch = AuditService._derive_scope(
            user=resolved_user,
            institution=institution,
            branch=branch,
        )
        resolved_module, resolved_resource, resolved_event = (
            AuditService._derive_action_parts(
                action=action,
                module=module,
                resource=resource,
                event=event,
            )
        )

        return AuditLog.objects.create(
            user=resolved_user,
            institution=resolved_institution,
            branch=resolved_branch,
            action=action,
            module=resolved_module,
            resource=resolved_resource,
            event=resolved_event,
            target=target,
            metadata=AuditService._normalize_metadata(metadata),
            ip_address=ip_address or AuditService._resolve_ip_address(request),
            request_path=request_path or getattr(request, "path", ""),
        )
