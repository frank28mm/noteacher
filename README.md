# 作业检查大师 - 使用说明（上传策略）

- 推荐上传：原始高清文件（JPG/PNG/HEIF/PDF），单文件不超过 20 MB。
- URL 优先：客户端上传到云存储后，将公网可达的 HTTP/HTTPS URL 传给 `/grade`。禁止使用 127/localhost/内网 URL。
- Base64 兜底：仅在小图/调试场景使用，去掉 `data:image/...;base64,` 前缀；超过 20 MB 直接拒绝，建议改用 URL。
- Provider 约束：
  - Qwen3（Silicon）为主力，支持 URL（推荐）或 base64（兜底）。
  - Doubao（Ark）仅接受公网 URL，base64 会被拒绝。
- 提示：APP 端不要压缩/降采样，直接上传原图再传 URL 以保证识别精度。
