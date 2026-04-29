from collections.abc import Mapping, Sequence

from rest_framework.views import exception_handler


def _normalize_error_detail(detail):
    if isinstance(detail, Mapping):
        return {str(key): _normalize_error_detail(value) for key, value in detail.items()}

    if isinstance(detail, Sequence) and not isinstance(detail, str):
        return [_normalize_error_detail(value) for value in detail]

    return str(detail)


def _first_message(detail):
    if isinstance(detail, Mapping):
        for value in detail.values():
            message = _first_message(value)
            if message:
                return message
        return None

    if isinstance(detail, Sequence) and not isinstance(detail, str):
        for value in detail:
            message = _first_message(value)
            if message:
                return message
        return None

    text = str(detail).strip()
    return text or None


def _first_code(detail):
    if isinstance(detail, Mapping):
        for value in detail.values():
            code = _first_code(value)
            if code:
                return code
        return None

    if isinstance(detail, Sequence) and not isinstance(detail, str):
        for value in detail:
            code = _first_code(value)
            if code:
                return code
        return None

    return str(detail).strip() or None


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    detail = _normalize_error_detail(response.data)
    request = context.get("request")

    if isinstance(detail, dict):
        errors = {key: value for key, value in detail.items() if key not in {"detail", "message"}}
        message = detail.get("detail") or detail.get("message") or _first_message(errors)
    else:
        errors = {}
        message = _first_message(detail)

    code = (
        _first_code(getattr(exc, "get_codes", lambda: None)())
        if hasattr(exc, "get_codes")
        else None
    )

    if not code:
        code = "error"

    if not message:
        message = "Request failed."

    response.data = {
        "message": str(message),
        "status": response.status_code,
        "status_code": response.status_code,
        "code": code,
        "errors": errors,
        "path": request.get_full_path() if request else None,
    }
    return response
