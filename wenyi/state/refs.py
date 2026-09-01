"""State 中使用的跨章节 Segment 引用类型。"""

from __future__ import annotations

from typing import NamedTuple


class GlobalSegmentIndex(NamedTuple):
    """通过章节编号和章节内 Segment 编号定位一个全局文本位置。

    这是 State 层的引用类型，不是 ``Document`` 数据模型。继承
    ``NamedTuple`` 是为了兼容当前 State/consistency 使用的二元 tuple。
    """

    chapter: int
    segment: int

