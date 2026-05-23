"""统一异常层级"""


class MiMoDocError(Exception):
    """MiMoDoc 所有异常的基类"""


class ConfigError(MiMoDocError):
    """配置相关错误"""


class ParseError(MiMoDocError):
    """代码解析失败"""


class GenerateError(MiMoDocError):
    """文档生成失败"""


class ValidateError(MiMoDocError):
    """文档校验失败"""


class NetworkError(MiMoDocError):
    """网络请求错误"""
