from loguru import logger
import sys
import os

# 初始化日志目录
log_dir = './logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 配置全局logger
logger.remove()

# 调试日志写入文件
logger.add(
    os.path.join(log_dir, 'debug.log'),
    level="DEBUG",
    rotation="5 MB",
    retention="1 day",
    enqueue=True,
    backtrace=True,
    diagnose=True,
    filter=lambda record: record["level"].name in ["DEBUG", "ERROR"]
)

# 信息日志输出到控制台
logger.add(
    sys.stdout,
    level="INFO",
    filter=lambda record: record["level"].name == "INFO"
)

# 导出可直接使用的logger实例
__all__ = ['logger']

