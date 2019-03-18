# Tests for SecretStorage
# Author: Dmitry Shachnev, 2019
# License: 3-clause BSD, see LICENSE file

# This file tests the secretstorage.create_connection() context manager.

import unittest
from secretstorage import dbus_init, get_any_collection


class ContextManagerTest(unittest.TestCase):
	"""A test case that tests the :class:`secretstorage.create_connection`
	context manager."""

	def test_dbus_init_works_as_a_context_manager(self) -> None:
		with dbus_init() as connection:
			collection = get_any_collection(connection)
			self.assertIsNotNone(collection)
			label = collection.get_label()
			self.assertIsNotNone(label)
