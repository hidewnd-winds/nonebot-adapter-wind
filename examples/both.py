"""注册 QQ 与 OneBot Wind 扩展并共享统一消息处理器。"""

import nonebot
from nonebot.adapters.wind.onebot_v11 import register as register_onebot
from nonebot.adapters.wind.qq import register as register_qq

def main() -> None:
    nonebot.init(_env_file=".env.dev", driver="~fastapi+~httpx+~websockets")
    driver = nonebot.get_driver()
    register_qq(driver)
    register_onebot(driver)
    nonebot.load_plugin("examples._echo_plugin")
    nonebot.run()


if __name__ == "__main__":
    main()
