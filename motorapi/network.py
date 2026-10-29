"""High-level multi-motor API with one physical channel and receive thread."""
import threading
import math

from .motor import MotorApi, MotorApiError, MotorConfig
from .transport import HCanbus, MODE_NORMAL


class MotorNetwork:
    def __init__(self, channel=0, *, transport=None):
        self.channel = channel
        self.bus = transport if transport is not None else HCanbus()
        self.motors = {}
        self.connected = False
        self.error = None
        self._stop = threading.Event()
        self._rx = None
        self._timing = None

    def motor(self, config: MotorConfig) -> MotorApi:
        """Register before connecting. Each returned API uses output-end units."""
        if self.connected:
            raise MotorApiError('register motors before connecting')
        if config.channel != self.channel or not 1 <= config.node <= 60:
            raise ValueError('motor channel must match network and node must be 1..60')
        if config.node in self.motors:
            raise ValueError('duplicate motor node')
        if not math.isfinite(config.gear_ratio) or config.gear_ratio <= 0:
            raise ValueError('gear ratio must be positive')
        if (config.nom_baud, config.dat_baud, config.sample_point) != (1_000_000, 4_000_000, 0.8):
            raise ValueError('shared network requires ISO CAN FD 1M/4M @80%')
        api = MotorApi(config, network=self)
        self.motors[config.node] = api
        return api

    def connect(self):
        if self.connected:
            return self._timing
        if not self.motors:
            raise MotorApiError('register at least one motor')
        try:
            self.bus.open(self.channel)
            self._timing = self.bus.canfd_init(1_000_000, 4_000_000, 0.8, MODE_NORMAL)
            self.error = None
            self._stop.clear()
            for api in self.motors.values():
                api._connected = True
                api._receive_error = None
                api._latest_status = None
                api._last_calib = None
            self.connected = True
            self._rx = threading.Thread(target=self._receive, name='motorapi-network-rx', daemon=True)
            self._rx.start()
            return self._timing
        except Exception:
            self.connected = False
            for api in self.motors.values():
                api._connected = False
            self.bus.close()
            raise

    def _receive(self):
        routes = {ident: api for node, api in self.motors.items()
                  for ident in (0x701 + 4 * node, 0x702 + 4 * node, 0x703 + 4 * node)}
        try:
            while not self._stop.is_set():
                for frame in self.bus.recv_fd(max_items=200, timeout_ms=1):
                    api = routes.get(frame.id)
                    if api is not None and api.connected:
                        api._handle_frame(frame)
                # Give transmitters a chance to acquire the shared SDK lock.
                self._stop.wait(0.001)
        except Exception as exc:
            self.error = str(exc)
            for api in self.motors.values():
                api._receive_error = self.error

    def disconnect(self, *, stop_motors=True):
        if not self.connected and self._rx is None:
            return
        # Stop every registered motor even if another stop command fails.
        failures = []
        for api in self.motors.values():
            api.abort_trajectory(stop_motor=False)
            api.stop_mit_streaming(stop_motor=False)
            if api.connected and stop_motors:
                try:
                    # Receive failures must not prevent a best-effort stop.
                    api.stop_motor()
                except Exception as exc:
                    failures.append(str(exc))
            api._connected = False
        self._stop.set()
        if self._rx:
            self._rx.join(timeout=2)
            if self._rx.is_alive():
                raise MotorApiError('receive thread did not stop; channel left open')
            self._rx = None
        self.bus.close()
        self.connected = False
        if failures:
            raise MotorApiError('stop errors: ' + '; '.join(failures))

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
