# Paper Empirical Interface
#
# 独立模块，为论文 "Anchor-Mismatch Dynamics" 提供经验接口
#
# 隔离原则：
# - 只读取 Harvester 和 Deformation 的输出，不修改它们
# - 所有计算在本模块内完成
# - 输出论文需要的图表和数据

__version__ = "0.1.0"

from paper_interface.case_analyzer import CaseAnalyzer
from paper_interface.figure_generator import FigureGenerator
from paper_interface.proxy_computer import ProxyComputer
from paper_interface.signature_quantities import SignatureQuantities

__all__ = [
    "ProxyComputer",
    "SignatureQuantities",
    "CaseAnalyzer",
    "FigureGenerator",
]
