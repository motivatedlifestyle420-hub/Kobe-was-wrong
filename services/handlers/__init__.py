from ..router import register
from .demo import handle as _demo_handle

register("demo", _demo_handle)
