"""独立适配器日志，不连接宿主日志数据库。"""
from nonebot.utils import logger_wrapper

log = logger_wrapper("Wind")
