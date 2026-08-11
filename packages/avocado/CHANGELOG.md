# CHANGELOG

<!-- version list -->

## v1.0.4 (2026-08-11)

### Bug Fixes

- **plugin,url**: Guard plugin stdout + validate node-id format
  ([`6804b7f`](https://github.com/evanfang0054/avocado-d2c/commit/6804b7f536e225287adedd848f9d63f0796551b7))


## v1.0.3 (2026-08-11)

### Bug Fixes

- **cli**: Batch CLI usability and envelope accuracy fixes
  ([`014aa5b`](https://github.com/evanfang0054/avocado-d2c/commit/014aa5b0a70f16755b8cdf37a2d5df5f8fdff637))


## v1.0.2 (2026-08-11)

### Bug Fixes

- **envelope**: Report plugin presets + correct format_raw under preset
  ([`49012d0`](https://github.com/evanfang0054/avocado-d2c/commit/49012d065b06430a13a74fa00ceb44b754e046d8))


## v1.0.1 (2026-08-11)

### Chores

- Allow zero versions in semantic-release config
  ([`c7cb9b2`](https://github.com/evanfang0054/avocado-d2c/commit/c7cb9b2f7b163e579734e928247e81d1e3bf2bf6))

- Support manual force release via workflow_dispatch
  ([`5627a24`](https://github.com/evanfang0054/avocado-d2c/commit/5627a24275165362e978093d74c970784f2fb41e))

### Documentation

- Switch license to Apache-2.0
  ([`da192ca`](https://github.com/evanfang0054/avocado-d2c/commit/da192ca7a9c043a47abc14b45e513ee697767cf8))

- Update changelog and version badge to v1.0.0
  ([`d92a015`](https://github.com/evanfang0054/avocado-d2c/commit/d92a015da453ec27d9da16947ae379dcfa25f7ac))


## v1.0.0 (2026-08-11)

- 首个开源发布（PyPI 包名 `avocado-d2c`）
- Figma D2C：节点 URL → React JSX / HTML + CSS（tailwind / inline / class 样式）
- agent-native JSON envelope CLI（`schema` / `init` / `paths` 子命令，统一错误码与退出码契约）
- 组件库 preset 映射（bundled antd.yaml 中立示例 + 用户插件 extractor 注册）
- 离线缓存模式（`--cache-dir` + `--offline`）
- CI（ruff + pytest）与全自动发布流水线（python-semantic-release + Trusted Publishing）
## v0.3.0 (2026-08-11)

- Initial Release
