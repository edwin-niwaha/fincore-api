from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    detail = response.data
    if isinstance(detail, dict):
        message = detail.get("detail") or detail.get("message") or "Request failed."
        errors = {key: value for key, value in detail.items() if key not in {"detail", "message"}}
    else:
        message = str(detail)
        errors = {}

    response.data = {
        "message": str(message),
        "status_code": response.status_code,
        "errors": errors,
    }
    return response
