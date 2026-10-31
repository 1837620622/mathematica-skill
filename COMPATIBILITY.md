# 兼容性矩阵 / Compatibility matrix

本文件只记录**真实跑过**的环境。没有跑过的写「未验证」，不写「应该可以」。

| 平台 | 架构 | Python | Wolfram | 内核计算 | 前端 Notebook | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| macOS | Apple Silicon (arm64) | 3.10 – 3.13 | Mathematica 13.2+ / 14.x | 设计目标 | 设计目标 | 待仓库所有者在实机填写 |
| macOS | Intel (x86_64) | 3.10 – 3.13 | Mathematica 13.2+ | 同上 | 同上 | 未验证 |
| Windows | x86_64 | 3.10 – 3.13 | Mathematica 13.2+ | 路径/进程已适配 | 未验证 | 未验证 |
| Linux | x86_64 / aarch64 | 3.12 | Wolfram Engine（无前端） | 代码路径可用 | 不支持 | 未验证 |

## 说明

- 「设计目标」= 代码和文档按该平台实现，但本仓库尚未在实机完成端到端验收。
- 「未验证」= 没有任何该平台的真实运行记录。
- Linux 上的 Wolfram Engine 没有 Notebook 前端，因此只能做 `.wl` 计算和 PNG 导出；
  `run` 会在 review 阶段因为 `FRONTEND_UNAVAILABLE` 而 `blocked`，这是正确行为。

## 需要什么证据才算「已验证」

1. `mathematica-skill doctor --frontend --json` 输出，含 `engine_usable: true`、`frontend_available: true`。
2. `mathematica-skill run examples/01-sine.json` 的 `state.json`，`status: "verified"`。
3. `_validation/validation.json` 里 `findings` 没有 error，`reproduction.all_reproduced: true`。
4. 交付目录里 `.nb` 能在该平台 Mathematica 里手动打开并「全部计算」成功。

把这三份摘要贴进本文件的对应行，才算该平台已验证。
