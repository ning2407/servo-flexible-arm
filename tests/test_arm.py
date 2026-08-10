import time

import pytest

from flexible_arm import (
    FlexibleArm,
    JointConfig,
    JointLimitError,
    TrajectoryPoint,
    VirtualServoDriver,
)


@pytest.fixture
def arm():
    driver = VirtualServoDriver([1, 2])
    result = FlexibleArm(
        [
            JointConfig(
                "shoulder",
                1,
                zero_offset_deg=10,
                direction=-1,
                min_deg=-90,
                max_deg=90,
            ),
            JointConfig(
                "elbow",
                2,
                zero_offset_deg=-5,
                min_deg=-120,
                max_deg=120,
            ),
        ],
        driver=driver,
    )
    result.connect("virtual")
    yield result
    result.disconnect()


def test_joint_angle_is_mapped_to_servo_angle(arm):
    arm.move_joint("shoulder", 30)
    assert arm.driver.read_state(1).angle_deg == pytest.approx(-20)
    assert arm.get_state(["shoulder"]).joints[0].position_deg == pytest.approx(30)


def test_synchronized_joint_move(arm):
    arm.move_joints({"shoulder": -20, 2: 45}, duration=0.1)
    assert arm.driver.read_state(1).angle_deg == pytest.approx(30)
    assert arm.driver.read_state(2).angle_deg == pytest.approx(40)


def test_joint_limit_is_checked_before_motion(arm):
    initial = arm.driver.read_state(1).angle_deg
    with pytest.raises(JointLimitError):
        arm.move_joint("shoulder", 91)
    assert arm.driver.read_state(1).angle_deg == initial


def test_entire_sync_move_is_validated_before_motion(arm):
    with pytest.raises(JointLimitError):
        arm.move_joints({"shoulder": 20, "elbow": 121})
    assert arm.driver.read_state(1).angle_deg == 0


def test_scan_can_configure_discovered_servos():
    driver = VirtualServoDriver([3, 7])
    arm = FlexibleArm(driver=driver)
    arm.connect("virtual")
    try:
        assert arm.scan(0, 8) == [3, 7]
        arm.move_joint(3, 25)
        assert driver.read_state(3).angle_deg == 25
    finally:
        arm.disconnect()


def test_trajectory_executes_all_points(arm):
    arm.execute_trajectory(
        [
            TrajectoryPoint({"shoulder": 10, "elbow": 20}, duration=0.01),
            TrajectoryPoint({"shoulder": 30, "elbow": 40}, duration=0.01),
        ],
        blocking=True,
    )
    state = arm.get_state()
    assert [joint.position_deg for joint in state.joints] == pytest.approx([30, 40])


def test_trajectory_can_pause_resume_and_stop(arm):
    arm.execute_trajectory(
        [TrajectoryPoint({"shoulder": 15}, duration=0.2)],
        loop=True,
    )
    time.sleep(0.02)
    arm.pause_trajectory()
    assert arm.trajectory_paused
    arm.resume_trajectory()
    assert not arm.trajectory_paused
    arm.stop()
    assert not arm.trajectory_running
    assert arm.driver.stopped
