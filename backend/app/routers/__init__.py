"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import endpoint as router_endpoint
from app.routers import chain as router_chain
from app.routers import freq as router_freq
from app.routers import mapper as router_mapper
from app.routers import validator as router_validator
from app.routers import retry as router_retry
from app.routers import aggregator as router_aggregator
from app.routers import auth as router_auth
from app.routers import cache as router_cache
from app.routers import dump as router_dump
from app.routers import schedule as router_schedule
from app.routers import monitor as router_monitor
from app.routers import transform as router_transform
from app.routers import cleanse as router_cleanse
from app.routers import ratelimit as router_ratelimit
from app.routers import log as router_log
from app.routers import delta as router_delta
from app.routers import export as router_export
from app.routers import audit as router_audit

ROUTERS = [router_endpoint, router_chain, router_freq, router_mapper, router_validator, router_retry, router_aggregator, router_auth, router_cache, router_dump, router_schedule, router_monitor, router_transform, router_cleanse, router_ratelimit, router_log, router_delta, router_export, router_audit]
