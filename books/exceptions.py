"""
books/exceptions.py
===================
Global exception handler for the BookIQ API.

Replaces DRF's default exception handler to ensure every error
response — regardless of source — returns a consistent JSON envelope:

{
    "error": true,
    "status_code": 404,
    "detail": "No Book matches the given query."
}

Registered in settings.py under:
    REST_FRAMEWORK = {
        'EXCEPTION_HANDLER': 'books.exceptions.global_exception_handler'
    }
"""

import logging
from django.core.exceptions import (
    PermissionDenied,
    ValidationError as DjangoValidationError,
    ObjectDoesNotExist,
)
from django.http import Http404, JsonResponse
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied as DRFPermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger(__name__)


def _make_error_response(
    detail,
    status_code: int,
    extra: dict = None
) -> Response:
    """
    Constructs the standard BookIQ error envelope.

    Args:
        detail:      human-readable error message (str, list, or dict)
        status_code: HTTP status code integer
        extra:       optional dict of additional fields to include

    Returns:
        DRF Response with consistent JSON structure
    """
    body = {
        'error': True,
        'status_code': status_code,
        'detail': detail,
    }
    if extra:
        body.update(extra)
    return Response(body, status=status_code)


def global_exception_handler(exc, context) -> Response:
    """
    Global DRF exception handler.

    Processing order:
    1. Let DRF handle its own exceptions first (returns None if unhandled)
    2. Intercept the DRF response and reformat into our envelope
    3. Handle Django exceptions DRF does not handle (Http404,
       PermissionDenied, ValidationError, ObjectDoesNotExist)
    4. Catch-all for unhandled exceptions → 500 Internal Server Error

    All exceptions are logged at ERROR level with request context.
    """
    request = context.get('request')
    view = context.get('view')

    # Log every exception with context
    logger.error(
        'Exception in view %s: %s',
        view.__class__.__name__ if view else 'unknown',
        str(exc),
        exc_info=True,
    )

    # --- Step 1: Let DRF handle its own exceptions ---
    response = drf_exception_handler(exc, context)

    if response is not None:
        # DRF handled it — reformat into our envelope
        detail = response.data

        if isinstance(exc, DRFPermissionDenied):
            return _make_error_response(
                detail='You do not have permission to perform this action.',
                status_code=status.HTTP_403_FORBIDDEN,
            )

        if response.status_code == status.HTTP_401_UNAUTHORIZED and isinstance(detail, dict) and 'detail' in detail:
            detail = str(detail['detail'])

        # DRF wraps single messages in {'detail': '...'}
        # Unwrap for cleaner responses
        if isinstance(detail, dict) and 'detail' in detail and len(detail) == 1:
            detail = str(detail['detail'])
        elif isinstance(detail, dict) and 'detail' in detail:
            # Has extra fields — keep the dict but ensure 'detail' is a string
            detail['detail'] = str(detail['detail'])

        return _make_error_response(
            detail=detail,
            status_code=response.status_code,
        )

    # --- Step 2: Handle Django exceptions DRF misses ---

    if isinstance(exc, Http404):
        return _make_error_response(
            detail=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, PermissionDenied):
        return _make_error_response(
            detail='You do not have permission to perform this action.',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, DjangoValidationError):
        return _make_error_response(
            detail=exc.message_dict if hasattr(exc, 'message_dict') else exc.messages,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, ObjectDoesNotExist):
        return _make_error_response(
            detail=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # --- Step 3: Catch-all for truly unhandled exceptions ---
    # In production (DEBUG=False) we never expose stack traces
    logger.critical(
        'Unhandled exception in %s: %s',
        view.__class__.__name__ if view else 'unknown',
        str(exc),
        exc_info=True,
    )

    return _make_error_response(
        detail='An unexpected error occurred. Please try again later.',
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def handler_404(request, exception=None):
    """
    Custom Django 404 handler.
    Fires for URLs that do not match any pattern — outside DRF's scope.
    Returns JSON instead of Django's default HTML 404 page.
    """
    return JsonResponse(
        {
            'error': True,
            'status_code': 404,
            'detail': f'Endpoint not found: {request.path}',
        },
        status=404
    )


def handler_500(request):
    """
    Custom Django 500 handler.
    Fires for unhandled server errors outside DRF's scope.
    Returns JSON instead of Django's default HTML 500 page.
    """
    return JsonResponse(
        {
            'error': True,
            'status_code': 500,
            'detail': 'Internal server error. Please try again later.',
        },
        status=500
    )
