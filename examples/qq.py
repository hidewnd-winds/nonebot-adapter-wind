"""仅注册 QQ Wind 扩展的 NoneBot 启动入口。"""

import nonebot
from nonebot.adapters.wind.qq import register

def main() -> None:
    nonebot.init(_env_file=".env.dev", driver="~fastapi+~httpx+~websockets")
    register(nonebot.get_driver())
    nonebot.load_plugin("examples._echo_plugin")
    nonebot.run()


if __name__ == "__main__":
    main()
