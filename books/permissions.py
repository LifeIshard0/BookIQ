from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """Only users with role='admin' can access."""
    message = 'Admin role required.'

    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'admin'
        )


class IsCuratorOrAbove(BasePermission):
    """Users with role='curator' or role='admin' can access."""
    message = 'Curator or Admin role required.'

    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role in ['curator', 'admin']
        )


class IsReaderOrAbove(BasePermission):
    """Any authenticated user can access."""
    message = 'Authentication required.'

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsOwnerOrAdminRole(BasePermission):
    """Object-level: only the creator or an admin can modify."""
    message = 'You do not have permission to modify this resource.'

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == 'admin':
            return True
        return getattr(obj, 'created_by', None) == request.user
