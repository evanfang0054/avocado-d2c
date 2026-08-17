# CHANGELOG

<!-- version list -->

## v1.5.0 (2026-08-17)

### Features

- **skills**: Add avocado-visual-diff for webpage vs design comparison
  ([`7abe916`](https://github.com/evanfang0054/avocado-d2c/commit/7abe916d7abd42a9b63abaedc21ab92fe05884ce))


## v1.4.3 (2026-08-13)

### Bug Fixes

- **style**: Emit 4-value border-radius for non-uniform corners
  ([`e7df3e4`](https://github.com/evanfang0054/avocado-d2c/commit/e7df3e4166285f87a0939c0aea399377c1ca1579))


## v1.4.2 (2026-08-13)

### Bug Fixes

- **version**: Query distribution name avocado-d2c for --version
  ([`073f499`](https://github.com/evanfang0054/avocado-d2c/commit/073f499df6dd08a065d228d416a22bf56c252a59))

### Documentation

- Add npx skills install guide + skill usage table
  ([`433c959`](https://github.com/evanfang0054/avocado-d2c/commit/433c959b46e812948ab0160f208e7c4828a0abc8))


## v1.4.1 (2026-08-13)

### Bug Fixes

- **skills**: Quote frontmatter description to fix YAML parse
  ([`131562e`](https://github.com/evanfang0054/avocado-d2c/commit/131562e183857eef52eac7faa8556a9c7d473ac8))


## v1.4.0 (2026-08-13)

### Features

- **trace**: Icon hint in suggestion + recommendation for variant misses
  ([`cff2f49`](https://github.com/evanfang0054/avocado-d2c/commit/cff2f49c0a879bcbd81ea120ed6ad9bbe14c00de))

### Refactoring

- **trace**: Drop icon-name heuristic from suggestion
  ([`8be3034`](https://github.com/evanfang0054/avocado-d2c/commit/8be3034d4638306b95a0a20fc71fd9a5c196461b))


## v1.3.0 (2026-08-13)

### Code Style

- **cli**: 消除 main 程序化调用的 pylint 误报
  ([`8a8b18b`](https://github.com/evanfang0054/avocado-d2c/commit/8a8b18b31301ac0ae30e28ffc5983beae1c7ea07))

### Documentation

- **skills**: Sync flag-decision-tree + router with trace-adapter
  ([`403164b`](https://github.com/evanfang0054/avocado-d2c/commit/403164bfc1f8853eb8347162c83bc9ef29ec1eea))

### Features

- **trace**: --trace-adapter 调试能力增强
  ([`db3e515`](https://github.com/evanfang0054/avocado-d2c/commit/db3e5157f39909b43fea236d0156f0e4065c1d22))


## Unreleased

### Features

- **trace**: --trace-adapter 增强——preset_matches 加 path/suggestion 与 applied_details（variant/leaf 应用侧）、extractor_outputs 加 error 枚举 + error_detail、插件识别节点补 matched_by=plugin、派生 issues 聚合块

## v1.2.4 (2026-08-13)

### Bug Fixes

- **layout**: Express negative itemSpacing as child overlap margin
  ([`b8e23f8`](https://github.com/evanfang0054/avocado-d2c/commit/b8e23f86844ae7d45a9ab5429a46a5663721effc))

### Chores

- Switch license to GPL-3.0
  ([`1d015be`](https://github.com/evanfang0054/avocado-d2c/commit/1d015be85d9dd67f69282e2774e9568bfb4b4d0e))

### Continuous Integration

- **release**: Full clone in checkout to fix concurrent-merge race
  ([`39c0f94`](https://github.com/evanfang0054/avocado-d2c/commit/39c0f9421518e37ec9d772b2def78d78e720f168))

### Refactoring

- **font**: De-brand font-family comments & test data to be font-agnostic
  ([`2dac4e5`](https://github.com/evanfang0054/avocado-d2c/commit/2dac4e54e5a36931302b289952a35f4b193db46e))


## v1.2.3 (2026-08-12)

### Bug Fixes

- **codegen**: Merge preset props.style into computed style
  ([`f16e5a5`](https://github.com/evanfang0054/avocado-d2c/commit/f16e5a58d6d59ca46ea9d122512405193e649a09))

- **tailwind**: Convert pseudo-component style to className
  ([`277eead`](https://github.com/evanfang0054/avocado-d2c/commit/277eeadd3eb6eb22ae15491dee68704902f92d8a))


## v1.2.2 (2026-08-12)

### Bug Fixes

- **tailwind**: Keep component style inline to avoid className stacking
  ([`b26a29f`](https://github.com/evanfang0054/avocado-d2c/commit/b26a29f447f67945923e1dfe85a84b4a615107bf))


## v1.2.1 (2026-08-12)

### Bug Fixes

- **tests**: Make trace reset test token-independent for CI
  ([`0a1233b`](https://github.com/evanfang0054/avocado-d2c/commit/0a1233b48e59a1def17b1118dc2a1d37a7b3b643))


## v1.2.0 (2026-08-12)

### Chores

- **skills**: De-brand component-adapter examples (atom → my_lib)
  ([`8512165`](https://github.com/evanfang0054/avocado-d2c/commit/8512165dd04491855f558c92776db27d6530b322))

### Documentation

- **skills**: Sync d2c skills with recent iteration
  ([`932a221`](https://github.com/evanfang0054/avocado-d2c/commit/932a22195ca7067c573ea4bd8fc77dcd1bc059c2))

### Features

- **trace**: Add --trace-adapter debug tracing for adapter authoring
  ([`b43a29e`](https://github.com/evanfang0054/avocado-d2c/commit/b43a29e70bca2c82bcb2d595ac81ba2f5e50ce59))

### Refactoring

- **skills**: Rename avocado-component-preset to avocado-component-adapter
  ([`eebcff5`](https://github.com/evanfang0054/avocado-d2c/commit/eebcff5b2c68fbe9f96aaa728cbfdb09d8795d44))


## v1.1.0 (2026-08-12)

### Bug Fixes

- **beautify**: Correct Fragment shorthand reprint (React white-screen)
  ([`71938cb`](https://github.com/evanfang0054/avocado-d2c/commit/71938cb9598b72e1e73da41c847198a3577e9957))

- **quality**: Split semanticization by CSS form, drop injected reset
  ([`fd118c2`](https://github.com/evanfang0054/avocado-d2c/commit/fd118c292870f7c803b9dc4539d586b3202c9407))

### Features

- **quality**: Semantic HTML tags + zero-length CSS cleanup
  ([`f8b3ff9`](https://github.com/evanfang0054/avocado-d2c/commit/f8b3ff9de032c668d44171cacc1042eb190834e9))


## v1.0.7 (2026-08-12)

### Bug Fixes

- **cli**: Run name-recognition plugin before unwrap to protect components
  ([`917706e`](https://github.com/evanfang0054/avocado-d2c/commit/917706e261638939b0178fea4a0481e757ae2fa2))

- **optimize**: Unwrap static single-child wrappers with absolute subtrees
  ([`0daf78a`](https://github.com/evanfang0054/avocado-d2c/commit/0daf78afbd2cf7626ba9a8374ae4bb98d4f9e8a9))


## v1.0.6 (2026-08-11)

### Bug Fixes

- **image**: Graceful fallback for unrenderable nested-instance nodes
  ([`d05422d`](https://github.com/evanfang0054/avocado-d2c/commit/d05422dcc6e97e6d056eabf028c9394cf855bbfb))


## v1.0.5 (2026-08-11)

### Bug Fixes

- **beautify**: Boolean JSX attrs crash (list index out of range) [#22]
  ([`e9615e1`](https://github.com/evanfang0054/avocado-d2c/commit/e9615e18ab06489dc92d0d4f5b3b03f7d8a7b22c))

- **issues**: Batch fix open issues #17-#22
  ([`e9615e1`](https://github.com/evanfang0054/avocado-d2c/commit/e9615e18ab06489dc92d0d4f5b3b03f7d8a7b22c))


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

- Switch license to GPL-3.0
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
