from motorapi import MotorApi, MotorConfig

api = MotorApi(MotorConfig(channel=0, node=3, gear_ratio=50))
try:
    api.connect()
    state = api.wait_status()
    print("电机端角度：", state.position_deg)
    print("输出端角度：", state.position_out_deg)
finally:
    api.disconnect()