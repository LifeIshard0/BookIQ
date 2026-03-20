"""Permission class unit tests for BookIQ."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from books.permissions import IsAdminRole, IsCuratorOrAbove, IsOwnerOrAdminRole, IsReaderOrAbove


class PermissionTests(SimpleTestCase):
	def test_admin_role_requires_authenticated_admin(self):
		permission = IsAdminRole()
		self.assertTrue(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=True, role='admin')), None))
		self.assertFalse(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=True, role='curator')), None))
		self.assertFalse(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=False, role='admin')), None))

	def test_curator_or_above_allows_curator_and_admin_only(self):
		permission = IsCuratorOrAbove()
		self.assertTrue(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=True, role='curator')), None))
		self.assertTrue(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=True, role='admin')), None))
		self.assertFalse(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=True, role='reader')), None))

	def test_reader_or_above_requires_authenticated_user(self):
		permission = IsReaderOrAbove()
		self.assertTrue(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=True)), None))
		self.assertFalse(permission.has_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=False)), None))

	def test_owner_or_admin_role_allows_owner_or_admin(self):
		permission = IsOwnerOrAdminRole()
		owner = SimpleNamespace(username='owner', role='reader', is_authenticated=True)
		admin = SimpleNamespace(username='admin', role='admin', is_authenticated=True)
		other_user = SimpleNamespace(username='other', role='reader', is_authenticated=True)
		obj = SimpleNamespace(created_by=owner)

		self.assertTrue(permission.has_object_permission(SimpleNamespace(user=owner), None, obj))
		self.assertTrue(permission.has_object_permission(SimpleNamespace(user=admin), None, obj))
		self.assertFalse(permission.has_object_permission(SimpleNamespace(user=other_user), None, obj))
		self.assertFalse(permission.has_object_permission(SimpleNamespace(user=SimpleNamespace(is_authenticated=False)), None, obj))