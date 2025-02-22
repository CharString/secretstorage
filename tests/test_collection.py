# Tests for SecretStorage
# Author: Dmitry Shachnev, 2013-2018
# License: 3-clause BSD, see LICENSE file

# This file tests the secretstorage.Collection class.

import unittest
from secretstorage import Collection, Item
from secretstorage import dbus_init, get_any_collection, get_all_collections
from secretstorage import create_collection, get_default_collection
from secretstorage.util import BUS_NAME
from secretstorage.exceptions import ItemNotFoundException

class CollectionTest(unittest.TestCase):
	"""A test case that tests that all common methods of Collection
	class work and do not crash."""

	def setUp(self) -> None:
		self.connection = dbus_init()
		self.collection = get_any_collection(self.connection)

	def tearDown(self) -> None:
		self.connection.sock.close()

	def test_all_collections(self) -> None:
		labels = map(Collection.get_label, get_all_collections(self.connection))
		self.assertIn(self.collection.get_label(), labels)

	def test_all_items(self) -> None:
		for item in self.collection.get_all_items():
			item.get_label()

	def test_create_empty_item(self) -> None:
		item = self.collection.create_item('', {}, b'')
		item.delete()

	def test_label(self) -> None:
		old_label = self.collection.get_label()
		self.collection.set_label('Hello!')
		self.assertEqual(self.collection.get_label(), 'Hello!')
		self.collection.set_label(old_label)
		self.assertEqual(self.collection.get_label(), old_label)

	def test_opens_default_collection_by_default(self) -> None:
		collection = Collection()
		self.assertEqual(collection.get_label(), 'Login')
		collection.close()

	def test_closes_connction_as_context_manager(self) -> None:
		with Collection() as collection:
			self.assertEqual(collection.get_label(), 'Login')
		with self.assertRaises(OSError):
			collection.get_label()



@unittest.skipIf(BUS_NAME == "org.freedesktop.secrets",
                "This test should only be run with the mocked server.")
class MockCollectionTest(unittest.TestCase):
	def setUp(self) -> None:
		self.connection = dbus_init()

	def tearDown(self) -> None:
		self.connection.sock.close()

	def test_default_collection(self) -> None:
		collection = get_default_collection(self.connection)
		self.assertEqual(collection.get_label(), "Collection One")

	def test_deleting(self) -> None:
		collection_path = "/org/freedesktop/secrets/collection/spanish"
		collection = Collection(self.connection, collection_path)
		collection.unlock()
		collection.delete()

	def test_deleting_prompt(self) -> None:
		collection_path = "/org/freedesktop/secrets/collection/lockprompt"
		try:
			collection = Collection(self.connection, collection_path)
		except ItemNotFoundException:
			self.skipTest("This test should only be run with mock-service-lock.")
		collection.unlock()
		collection.delete()

	def test_deleting_item_prompt(self) -> None:
		item_path = "/org/freedesktop/secrets/collection/lockone/confirm"
		try:
			item = Item(self.connection, item_path)
		except ItemNotFoundException:
			self.skipTest("This test should only be run with mock-service-lock.")
		item.delete()

	def test_create_collection(self) -> None:
		collection = create_collection(self.connection, "My Label")
		self.assertEqual(collection.get_label(), "My Label")
