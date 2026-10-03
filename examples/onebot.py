"""仅注册 OneBot V11 Wind 扩展的 NoneBot 启动入口。"""

import nonebot
from nonebot.adapters.wind.onebot_v11 import register

def main() -> None:
    nonebot.init(_env_file=".env.dev", driver="~fastapi+~httpx+~websockets")
    register(nonebot.get_driver())
    nonebot.load_plugin("examples._echo_plugin")
    nonebot.run()


if __name__ == "__main__":
    main()
