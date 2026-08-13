# Prompt Assets

仅保留三个生产提示词：

- `generation/runninghub/merchandise_generation_cn.txt`：SN-7 六类三视图与 SN-6 PVC 正视图共用模板。占位符由 `prompt_renderer.py` 严格渲染。
- `supervision/atomic_rules_cn.txt`：SN-7 可见身份特征抽取。
- `supervision/paired_front_view_review_cn.txt`：SN-6 生成图对 paired gold 的逐元素监修。

生成模板包含 `{{MERCHANDISE_CATEGORY}}`、`{{VIEW_REQUIREMENTS}}` 和 `{{CATEGORY_REQUIREMENTS}}`。不要在脚本外手工替换，也不要为单个商品复制新的提示词文件；商品差异统一维护在 `vlm/scripts/generate/prompt_renderer.py`。
