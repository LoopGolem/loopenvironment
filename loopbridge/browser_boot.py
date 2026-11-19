# SPDX-License-Identifier: Apache-2.0
"""Publish only the accessibility locator on Firefox's private session bus."""
import subprocess
import sys

from gi.repository import Gio, GLib

import browser_native

INTERFACES = """<node>
  <interface name="org.a11y.Bus">
    <method name="GetAddress"><arg type="s" direction="out"/></method>
  </interface>
  <interface name="org.a11y.Status">
    <property name="IsEnabled" type="b" access="read"/>
    <property name="ScreenReaderEnabled" type="b" access="read"/>
  </interface>
</node>"""


def main():
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    node = Gio.DBusNodeInfo.new_for_xml(INTERFACES)
    path = '/org/a11y/bus'

    def get_address(conn, sender, obj, interface, method, params, invocation):
        invocation.return_value(GLib.Variant('(s)', ('unix:path=/run/browser/atspi',)))

    def status(*_):
        return GLib.Variant('b', True)

    connection.register_object(path, node.interfaces[0], get_address, None, None)
    connection.register_object(path, node.interfaces[1], None, status, None)
    connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                         'RequestName', GLib.Variant('(su)', ('org.a11y.Bus', 4)),
                         GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 2000, None)
    browser = subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL, close_fds=True)
    browser_native.start()
    loop = GLib.MainLoop()

    def poll():
        if browser.poll() is None:
            return True
        loop.quit()
        return False

    GLib.timeout_add(100, poll)
    loop.run()
    return browser.returncode


if __name__ == '__main__':
    raise SystemExit(main())
