from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.exceptions import BusinessRuleError


def custom_exception_handler(exc, context):
    """Every error looks the same: {"error": {"status": 400, "message": "...", "details": ...}}"""
    if isinstance(exc, BusinessRuleError):
        return Response({"error": {"status": 400, "message": str(exc), "details": None}}, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, Http404):
        return Response({"error": {"status": 404, "message": "Not found.", "details": None}}, status=404)
    if isinstance(exc, PermissionDenied):
        return Response({"error": {"status": 403, "message": "You do not have permission to perform this action.", "details": None}}, status=403)
    response = exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data
    message = detail.get("detail") if isinstance(detail, dict) and "detail" in detail else "Request failed."
    if response.status_code == 400:
        message = "Validation failed."
    response.data = {"error": {"status": response.status_code, "message": str(message), "details": None if message != "Validation failed." else detail}}
    return response
