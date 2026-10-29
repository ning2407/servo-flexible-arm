"""Control timing checks without connecting to hardware."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motorapi import MotorApi


class TimingTest(unittest.TestCase):
    def test_send_cost_does_not_accumulate_into_period(self):
        deadline = 0.0
        for slot in range(100):
            # Each transmit costs 3 ms; cadence must remain 10 ms.
            deadline = MotorApi._next_send_deadline(deadline, 0.01, deadline + 0.003)
            self.assertAlmostEqual(deadline, (slot + 1) * 0.01)

    def test_overrun_skips_slots_without_burst(self):
        deadline = MotorApi._next_send_deadline(0.0, 0.01, 0.035)
        self.assertAlmostEqual(deadline, 0.04)
        self.assertAlmostEqual(MotorApi._next_send_deadline(deadline, 0.01, 0.043), 0.05)

    def test_single_motor_rx_yields_outside_receive(self):
        api = MotorApi()
        api.bus = Mock()
        api.bus.recv_fd.return_value = []
        api._rx_stop = Mock()
        api._rx_stop.is_set.side_effect = [False, True]
        api._rx_loop()
        api.bus.recv_fd.assert_called_once_with(max_items=200, timeout_ms=1)
        api._rx_stop.wait.assert_called_once_with(0.001)


if __name__ == '__main__':
    unittest.main()
