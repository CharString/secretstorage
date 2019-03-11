# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2013-2018
# License: 3-clause BSD, see LICENSE file

"""This file provides quick access to all SecretStorage API. Please
refer to documentation of individual modules for API details.
"""

from jeepney.integrate.blocking import DBusConnection, connect_and_authenticate
from secretstorage.collection import Collection, create_collection, \
 get_all_collections, get_default_collection, get_any_collection, \
 get_collection_by_alias, search_items
from secretstorage.item import Item
from secretstorage.exceptions import SecretStorageException, \
 SecretServiceNotAvailableException, LockedException, \
 ItemNotFoundException, PromptDismissedException
from secretstorage.util import add_match_rules

__version_tuple__ = (3, 1, 0)
__version__ = '.'.join(map(str, __version_tuple__))

def dbus_init() -> DBusConnection:
	"""Returns a new connection to the session bus, instance of
	jeepney's :class:`DBusConnection` class. This connection can
	then be passed to various SecretStorage functions, such as
	:func:`~secretstorage.collection.get_default_collection`.

	.. warning::
	   If you use this function directly, it may result in resource
	   leak as the D-Bus socket will not be closed automatically.
	   We recommend to use :class:`create_connection` context manager
	   instead, which will close the socket on exit.

	.. versionchanged:: 3.0
	   Before the port to Jeepney, this function returned an
	   instance of :class:`dbus.SessionBus` class.

	.. versionchanged:: 3.1
	   This function no longer accepts any arguments.
	"""
	try:
		connection = connect_and_authenticate()
		add_match_rules(connection)
		return connection
	except KeyError as ex:
		# os.environ['DBUS_SESSION_BUS_ADDRESS'] may raise it
		reason = "Environment variable {} is unset".format(ex.args[0])
		raise SecretServiceNotAvailableException(reason) from ex
	except (ConnectionError, ValueError) as ex:
		raise SecretServiceNotAvailableException(str(ex)) from ex


class create_connection:
	"""A context manager that returns a new connection to the session bus,
	that will be an instance of jeepney's :class:`DBusConnection` class.

	The D-Bus socket will be automatically closed on exit.

	Example of usage:

	.. code-block:: python

	   with secretstorage.create_connection() as conn:
	       collection = secretstorage.get_default_collection(conn)
	       items = collection.search_items({'application': 'myapp'})
	"""
	def __enter__(self) -> DBusConnection:
		self.connection = dbus_init()
		return self.connection

	def __exit__(self, exc_type, exc_value, traceback):  # type: ignore
		self.connection.sock.close()
