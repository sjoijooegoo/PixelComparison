# PixelComparison

PixelComparison 管理场景视觉批次及其烘培数据，用于追踪图像差异和资源规模变化。

## Language

**主分块**:
场景烘培 Registry 树的根节点，代表不归属于任一下级分块的根 BuildData。
_Avoid_: 总场景、根 Registry

**自身数据**:
直接归属于当前选中节点的烘培数据，不包含任何下级节点。
_Avoid_: 节点总数据

**含子级汇总**:
当前节点自身数据与其全部后代节点数据的合计。
_Avoid_: 子块总数据、子级合计

**反射分块**:
主分块下路径以 `_BlockRefl` 结尾的直属 Registry 节点。它没有数字 `blockIndex` 和子分块网格，但作为独立节点展示、查看细则并按 Registry 路径查询趋势。
_Avoid_: 分块 4、主分块自身数据
