# Cross-Section v6.2.2

**2026-10-24**

- 修复比分显示 bug：没设 SteamID 时比分显示成 `0:总回合数`
- 补齐地图雷达参数（此前新环境缺 `de_vertigo.txt` 等文件，回放地图加载失败）

已有数据需要重算一次：Demo 页「⟲ 全部重新解析」，或跑 `python cs2tool/repair_me.py --data data`。
