"""Exceptions raised by the flexible arm SDK."""


class ArmError(Exception):
    """Base exception for all SDK errors."""


class ConnectionError(ArmError):
    """The servo bus could not be connected or is disconnected."""


class DriverError(ArmError):
    """The underlying servo driver failed."""


class JointNotFoundError(ArmError):
    """A requested joint is not configured."""


class JointLimitError(ArmError):
    """A target joint angle is outside its configured limits."""


class TrajectoryError(ArmError):
    """A trajectory is invalid or cannot be executed."""
