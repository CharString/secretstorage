# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2013-2018
# License: 3-clause BSD, see LICENSE file

"""This module provides some utility functions, but these shouldn't
normally be used by external applications."""

import os
from typing import Any, List, Tuple

from jeepney import DBusAddress
from jeepney.bus_messages import MatchRule
from jeepney.integrate.blocking import DBusConnection, connect_and_authenticate
from jeepney.low_level import Message
from jeepney.wrappers import new_method_call, Properties, DBusErrorResponse
from secretstorage.defines import DBUS_UNKNOWN_METHOD, DBUS_NO_SUCH_OBJECT, \
 DBUS_SERVICE_UNKNOWN, DBUS_NO_REPLY, DBUS_NOT_SUPPORTED, DBUS_EXEC_FAILED, \
 SS_PATH, SS_PREFIX, ALGORITHM_DH, ALGORITHM_PLAIN
from secretstorage.dhcrypto import Session, int_to_bytes
from secretstorage.exceptions import ItemNotFoundException, \
 SecretServiceNotAvailableException
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.utils import int_from_bytes

BUS_NAME = 'org.freedesktop.secrets'
SERVICE_IFACE = SS_PREFIX + 'Service'
PROMPT_IFACE = SS_PREFIX + 'Prompt'


class DBusAddressWrapper(DBusAddress):  # type: ignore
	"""A wrapper class around :class:`jeepney.wrappers.DBusAddress`
	that adds some additional methods for calling and working with
	properties, and converts error responses to SecretStorage
	exceptions.

	.. versionadded:: 3.0
	"""
	def __init__(self, path: str, interface: str,
	             connection: DBusConnection) -> None:
		DBusAddress.__init__(self, path, BUS_NAME, interface)
		self._connection = connection

	def send_and_get_reply(self, msg: Message) -> Any:
		try:
			return self._connection.send_and_get_reply(msg)
		except DBusErrorResponse as resp:
			if resp.name in (DBUS_UNKNOWN_METHOD, DBUS_NO_SUCH_OBJECT):
				raise ItemNotFoundException('Item does not exist!') from resp
			elif resp.name in (DBUS_SERVICE_UNKNOWN, DBUS_EXEC_FAILED,
			                   DBUS_NO_REPLY):
				data = resp.data
				if isinstance(data, tuple):
					data = data[0]
				raise SecretServiceNotAvailableException(data) from resp
			raise

	def call(self, method: str, signature: str, *body: Any) -> Any:
		msg = new_method_call(self, method, signature, body)
		return self.send_and_get_reply(msg)

	def get_property(self, name: str) -> Any:
		msg = Properties(self).get(name)
		(signature, value), = self.send_and_get_reply(msg)
		return value

	def set_property(self, name: str, signature: str, value: Any) -> None:
		msg = Properties(self).set(name, signature, value)
		self.send_and_get_reply(msg)


def open_session(connection: DBusConnection) -> Session:
	"""Returns a new Secret Service session."""
	service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
	session = Session()
	try:
		output, result = service.call('OpenSession', 'sv',
			ALGORITHM_DH,
			('ay', int_to_bytes(session.my_public_key)))
	except DBusErrorResponse as resp:
		if resp.name != DBUS_NOT_SUPPORTED:
			raise
		output, result = service.call('OpenSession', 'sv',
			ALGORITHM_PLAIN,
			('s', ''))
		session.encrypted = False
	else:
		signature, value = output
		assert signature == 'ay'
		key = int_from_bytes(value, 'big')
		session.set_server_public_key(key)
	session.object_path = result
	return session

def format_secret(session: Session, secret: bytes,
                  content_type: str) -> Tuple[str, bytes, bytes, str]:
	"""Formats `secret` to make possible to pass it to the
	Secret Service API."""
	if not isinstance(secret, bytes):
		secret = secret.encode('utf-8')
	assert session.object_path is not None
	if not session.encrypted:
		return (session.object_path, b'', secret, content_type)
	# PKCS-7 style padding
	padding = 0x10 - (len(secret) & 0xf)
	secret += bytes((padding,) * padding)
	aes_iv = os.urandom(0x10)
	aes = algorithms.AES(session.aes_key)
	encryptor = Cipher(aes, modes.CBC(aes_iv), default_backend()).encryptor()
	encrypted_secret = encryptor.update(secret) + encryptor.finalize()
	return (
		session.object_path,
		aes_iv,
		encrypted_secret,
		content_type
	)


def exec_prompt(connection: DBusConnection,
	        prompt_path: str) -> Tuple[bool, List[str]]:
	"""Executes the prompt in a blocking mode.

	:returns: a tuple; the first element is a boolean value showing
	          whether the operation was dismissed, the second element
	          is a list of unlocked object paths
	"""
	prompt = DBusAddressWrapper(prompt_path, PROMPT_IFACE, connection)
	dismissed = result = None
	def callback(msg_body: Tuple[bool, List[str]]) -> None:
		_dismissed, _result = msg_body
		nonlocal dismissed, result
		dismissed, result = bool(_dismissed), _result
	connection.router.subscribe_signal(callback, prompt_path, PROMPT_IFACE, 'Completed')
	prompt.call('Prompt', 's', '')
	if result is None:
		connection.recv_messages()
	assert dismissed is not None
	assert result is not None
	return dismissed, result


def unlock_objects(connection: DBusConnection, paths: List[str]) -> bool:
	"""Requests unlocking objects specified in `paths`.
	Returns a boolean representing whether the operation was dismissed.

	.. versionadded:: 2.1.2"""
	service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
	unlocked_paths, prompt = service.call('Unlock', 'ao', paths)
	if len(prompt) > 1:
		dismissed, (signature, unlocked) = exec_prompt(connection, prompt)
		assert signature == 'ao'
		return dismissed
	return False


def add_match_rules(connection: DBusConnection) -> None:
	"""Adds match rules for the given connection.

	Currently it matches all messages from the Prompt interface, as the
	mock service (unlike GNOME Keyring) does not specify the signal
	destination.

	.. versionadded:: 3.1
	"""
	rule = MatchRule(sender=BUS_NAME, interface=PROMPT_IFACE)
	dbus = DBusAddressWrapper(path='/org/freedesktop/DBus',
	                          interface='org.freedesktop.DBus',
	                          connection=connection)
	dbus.bus_name = 'org.freedesktop.DBus'
	dbus.call('AddMatch', 's', rule.serialise())


def dbus_init() -> DBusConnection:
	"""Returns a new connection to the session bus, instance of
	jeepney's :class:`DBusConnection` class. This connection can
	then be passed to various SecretStorage functions, such as
	:func:`~secretstorage.collection.get_default_collection`.

	It can be used as conext manager that closes the D-Bus socket
	automatically on exit.

	Example of usage:

	.. code-block:: python

	   with secretstorage.dbus_init() as conn:
		   collection = secretstorage.get_default_collection(conn)
		   items = collection.search_items({'application': 'myapp'})

	.. versionchanged:: 3.0
	   Before the port to Jeepney, this function returned an
	   instance of :class:`dbus.SessionBus` class.

	.. versionchanged:: 3.1
	   This function no longer accepts any arguments.
	"""
	try:
		connection = connect_and_authenticate()
		add_match_rules(connection)
		return ClosingDBusConnectionWrapper(connection)
	except KeyError as ex:
		# os.environ['DBUS_SESSION_BUS_ADDRESS'] may raise it
		reason = "Environment variable {} is unset".format(ex.args[0])
		raise SecretServiceNotAvailableException(reason) from ex
	except (ConnectionError, ValueError) as ex:
		raise SecretServiceNotAvailableException(str(ex)) from ex


class ClosingDBusConnectionWrapper:
	"Ideally jeepney.integrate.blocking.DBusConnection has this functionality"
	def __init__(self, connection: DBusConnection):
		self._wrapped_connection = connection

	def __getattribute__(self, name):
		if name in ('_wrapped_connection', 'close'):
			return object.__getattribute__(self, name)
		return getattr(self._wrapped_connection, name)

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):  # type: ignore
		self.close()

	def close(self):
		return self._wrapped_connection.sock.close()
