"""Native HID failure and ownership contracts, without opening OS devices."""
import ctypes as ct
from types import SimpleNamespace
import unittest

import joystick


class HIDDouble:
    def __init__(self):
        self.open_status = self.close_status = self.read_status = 0
        self.null_value = False
        self.enumeration_error = False
        self.element_ids = [21, 22]
        self.low, self.high = 0, 255
        self.active = set()
        self.closed = []
        self.released = []
        self.refs = {1: 1, 2: 1, 4: 1, 10: 0, 3: 0}
        self.values = {21: 255, 22: 1}

    def retain(self, resource):
        self.refs[resource] += 1
        return resource

    def release(self, resource):
        if self.refs[resource] <= 0:
            raise AssertionError(f'double release: {resource}')
        self.refs[resource] -= 1
        self.released.append(resource)

    def open(self, device, options):
        if options != 0:
            raise AssertionError('The joystick must open non-exclusively')
        if not self.open_status:
            self.active.add(device)
        return self.open_status

    def close(self, device, options):
        self.closed.append(device)
        self.active.discard(device)
        return self.close_status

    def copy_elements(self, *args):
        if self.element_ids is None:
            return None
        self.refs[3] += 1
        return 3

    def element_type(self, element):
        if self.enumeration_error:
            raise RuntimeError('element enumeration failed')
        return 2

    def get_value(self, device, element, result):
        if device not in self.active or self.refs[3] != 1:
            raise AssertionError('Device and element array must remain owned during reads')
        if not self.null_value:
            ct.cast(result, ct.POINTER(ct.c_void_p))[0] = element
        return self.read_status

    def joystick(self):
        j = joystick.MacHIDJoystick.__new__(joystick.MacHIDJoystick)
        j.handle = j.elements = None
        j.manager, j.device_set = 1, 2
        j.keys = {'Product': 4}
        j.records = [{'device': 10, 'name': 'Controller'}]
        j.io = SimpleNamespace(
            IOHIDDeviceOpen=self.open, IOHIDDeviceClose=self.close,
            IOHIDDeviceCopyMatchingElements=self.copy_elements,
            IOHIDElementGetType=self.element_type,
            IOHIDElementGetUsagePage=lambda e: 1 if e == 21 else 9,
            IOHIDElementGetUsage=lambda e: 0x30 if e == 21 else 1,
            IOHIDElementGetCookie=lambda e: e,
            IOHIDElementGetLogicalMin=lambda e: self.low,
            IOHIDElementGetLogicalMax=lambda e: self.high,
            IOHIDDeviceGetValue=self.get_value,
            IOHIDValueGetIntegerValue=lambda value: self.values[value.value],
        )
        j.cf = SimpleNamespace(
            CFRetain=self.retain, CFRelease=self.release,
            CFArrayGetCount=lambda array: len(self.element_ids),
            CFArrayGetValueAtIndex=lambda array, i: self.element_ids[i],
        )
        return j


class NativeHIDTests(unittest.TestCase):
    def setUp(self):
        self.api = HIDDouble()
        self.j = self.api.joystick()
        self.addCleanup(self.j.shutdown)

    def assert_open_resources_released(self):
        self.assertIsNone(self.j.handle)
        self.assertIsNone(self.j.elements)
        self.assertEqual(self.api.refs[10], 0)
        self.assertEqual(self.api.refs[3], 0)
        self.assertEqual(self.api.active, set())

    def test_denied_open_reports_access_without_retaining_or_closing_device(self):
        self.api.open_status = -536870174  # kIOReturnNotPermitted, 0xe00002e2
        with self.assertRaisesRegex(ConnectionError, 'denied input access'):
            self.j.open(0)
        self.assert_open_resources_released()
        self.assertEqual(self.api.closed, [])

    def test_other_open_failure_reports_hid_status(self):
        self.api.open_status = -536870212  # 0xe00002bc
        with self.assertRaisesRegex(ConnectionError, '0xe00002bc'):
            self.j.open(0)
        self.assert_open_resources_released()
        self.assertEqual(self.api.closed, [])

    def test_no_usable_axes_releases_device_and_elements(self):
        for element_ids, low, high in ((None, 0, 255), ([], 0, 255), ([21], 0, 0), ([21], 2, 1), ([22], 0, 255)):
            with self.subTest(elements=element_ids, low=low, high=high):
                self.api.element_ids = element_ids
                self.api.low, self.api.high = low, high
                with self.assertRaisesRegex(ConnectionError, 'no usable joystick axes'):
                    self.j.open(0)
                self.assert_open_resources_released()

    def test_element_enumeration_exception_releases_all_open_resources(self):
        self.api.enumeration_error = True
        with self.assertRaisesRegex(RuntimeError, 'element enumeration failed'):
            self.j.open(0)
        self.assert_open_resources_released()
        self.assertEqual(self.api.closed, [10])

    def test_failed_or_null_value_is_a_connection_error(self):
        self.j.open(0)
        for status, null in ((-536870212, False), (0, True)):
            with self.subTest(status=status, null=null):
                self.api.read_status, self.api.null_value = status, null
                with self.assertRaisesRegex(ConnectionError, 'read failed or disconnected'):
                    self.j.read()

    def test_device_and_array_stay_owned_until_close_then_cleanup_is_idempotent(self):
        self.j.open(0)
        self.assertEqual(self.j.read(), ([1.0], [True]))
        self.j.close()
        self.j.close()
        self.assert_open_resources_released()
        self.assertEqual(self.api.closed, [10])
        self.j.shutdown()
        self.j.shutdown()
        self.assertEqual(self.api.refs, {1: 0, 2: 0, 4: 0, 10: 0, 3: 0})

    def test_close_status_failure_still_releases_owned_resources(self):
        self.j.open(0)
        self.api.close_status = -536870212
        self.j.close()
        self.assert_open_resources_released()
        self.j.shutdown()
        self.assertEqual(self.api.refs, {1: 0, 2: 0, 4: 0, 10: 0, 3: 0})


if __name__ == '__main__':
    unittest.main()
