import queue
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motorapi import MotorApi, MotorConfig, MotorNetwork, MotorApiError, codec


class FakeBus:
    def __init__(self):
        self.frames = []
        self.incoming = queue.Queue()
        self.opens = self.closes = self.inits = 0
        self.fail_id = None
        self.receive_error = False

    def status(self, node, pos=90, fault=0, running=4, mode=0, echo=None):
        payload = codec.encode_mit_frame(pos_code=codec.deg_to_pos_code(pos))
        ident = codec.can_ids(node)['mit_send'] if echo is None else echo
        data = (ident.to_bytes(2, 'little') + payload[:6] + payload[10:12]
                + bytes(2) + fault.to_bytes(4, 'little') + bytes([running, 0, mode, 2]))
        self.incoming.put(SimpleNamespace(id=0x702 + 4 * node, data=data,
                                          timestamp_us=0, frame_type=0))

    def open(self, channel):
        self.opens += 1
        for node in (1, 2, 3):
            self.status(node)

    def canfd_init(self, *args):
        self.inits += 1
        return {'ok': True}

    def send_fd(self, ident, data):
        self.frames.append((ident, data))
        return 0 if ident == self.fail_id else 1

    def recv_fd(self, max_items=200, timeout_ms=5):
        if self.receive_error:
            raise RuntimeError('USB removed')
        try:
            return [self.incoming.get(timeout=timeout_ms / 1000)]
        except queue.Empty:
            return []

    def close(self):
        self.closes += 1


class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.net = MotorNetwork(transport=self.bus)
        self.motors = [self.net.motor(MotorConfig(node=n, gear_ratio=50)) for n in (1, 2, 3)]
        self.net.connect()
        for motor in self.motors:
            motor.wait_status(timeout=1)

    def tearDown(self):
        self.bus.fail_id = None
        self.net.disconnect()

    def test_one_connection_routes_all_nodes_and_converts(self):
        self.assertEqual((self.bus.opens, self.bus.inits), (1, 1))
        self.assertTrue(all(m._rx_thread is None for m in self.motors))
        self.assertTrue(self.net._rx.is_alive())
        for m in self.motors:
            self.assertAlmostEqual(m.get_status(timeout=0).position_out_deg, 1.8, places=5)
            m.send_mit(position_out_deg=10, velocity_out_rpm=30)
        self.assertEqual([f[0] for f in self.bus.frames], [0x505, 0x509, 0x50D])
        d = codec.decode_mit_frame(self.bus.frames[0][1])
        self.assertAlmostEqual(d['position_deg'], 500, places=3)
        self.assertAlmostEqual(d['velocity_rpm'], 1500)

    def test_bad_identity_ignored_and_callback_error_isolated(self):
        self.motors[0].on_status(lambda st: (_ for _ in ()).throw(RuntimeError('callback')))
        self.bus.status(1, pos=100)
        self.bus.status(2, pos=200)
        self.bus.status(3, pos=999, echo=0)
        time.sleep(0.04)
        self.assertAlmostEqual(self.motors[0].get_status(timeout=0).position_deg, 100, places=3)
        self.assertAlmostEqual(self.motors[1].get_status(timeout=0).position_deg, 200, places=3)
        self.assertAlmostEqual(self.motors[2].get_status(timeout=0).position_deg, 90, places=3)
        self.assertIsNone(self.net.error)

    def test_transmit_zero_is_error(self):
        self.bus.fail_id = 0x505
        with self.assertRaisesRegex(MotorApiError, 'transmit'):
            self.motors[0].send_mit(position_out_deg=0)

    def test_rx_error_reported_but_stop_still_transmits(self):
        self.bus.receive_error = True
        time.sleep(0.04)
        with self.assertRaisesRegex(MotorApiError, 'USB removed'):
            self.motors[0].get_status(timeout=0)
        self.motors[0].stop_motor()
        self.assertEqual(self.bus.frames[-1][0], 0x506)

    def test_node_changes_and_broadcast_blocked(self):
        with self.assertRaises(MotorApiError):
            self.motors[0].set_node(2)
        with self.assertRaises(MotorApiError):
            self.motors[0].set_node_id(2)

    def test_motor_disconnect_does_not_close_other_motors(self):
        self.motors[0].disconnect()
        self.assertEqual(self.bus.closes, 0)
        self.assertFalse(self.motors[0].connected)
        self.motors[1].send_mit(position_out_deg=0)

    def test_single_motor_legacy_constructor_and_receive(self):
        bus = FakeBus()
        with patch('motorapi.motor.HCanbus', return_value=bus):
            motor = MotorApi(MotorConfig(node=1, gear_ratio=50))
        try:
            motor.connect()
            st = motor.wait_status(timeout=1)
            self.assertAlmostEqual(st.position_out_deg, 1.8, places=5)
            motor.send_mit(position_out_deg=10)
            self.assertEqual(bus.frames[-1][0], 0x505)
        finally:
            motor.disconnect()
        self.assertEqual(bus.closes, 1)

    def test_registration_validation(self):
        net = MotorNetwork(transport=FakeBus())
        net.motor(MotorConfig(node=1))
        for cfg in (MotorConfig(node=1), MotorConfig(node=0), MotorConfig(node=2, channel=1),
                    MotorConfig(node=2, gear_ratio=0)):
            with self.assertRaises(ValueError):
                net.motor(cfg)

    def test_individual_reconnect_reuses_channel(self):
        self.motors[0].disconnect()
        self.motors[0].connect()
        self.assertTrue(self.motors[0].connected)
        self.assertEqual(self.bus.opens, 1)
        self.bus.status(1, pos=250)
        self.assertAlmostEqual(self.motors[0].wait_status(timeout=1).position_deg, 250, places=3)

    def test_disconnect_failure_stops_all_and_closes(self):
        self.bus.fail_id = 0x506
        with self.assertRaisesRegex(MotorApiError, 'stop errors'):
            self.net.disconnect()
        self.assertFalse(self.net.connected)
        self.assertTrue(all(not m.connected for m in self.motors))
        self.assertEqual([f[0] for f in self.bus.frames], [0x506, 0x50A, 0x50E])
        self.assertEqual(self.bus.closes, 1)

    def test_stale_wait_status_raises(self):
        self.motors[0].get_status(timeout=0).timestamp = 0
        with self.assertRaisesRegex(MotorApiError, 'timeout'):
            self.motors[0].wait_status(timeout=0)

    def test_read_only_disconnect_sends_no_commands(self):
        self.net.disconnect(stop_motors=False)
        self.assertEqual(self.bus.frames, [])
        self.assertEqual(self.bus.closes, 1)


if __name__ == '__main__':
    unittest.main()
