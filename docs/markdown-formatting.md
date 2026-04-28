# Markdown 格式化

本项目集成了 `markdownlint-cli2` 来自动修复 Markdown 文件的格式问题。

## 问题背景

在生成 Markdown 总结时，LLM 可能会生成格式不规范的 Markdown，导致表格无法正确渲染。最常见的问题是：

### 表格前缺少空行

**错误示例：**

```markdown
这是一段文字：
| 列1 | 列2 |
|-----|-----|
| A   | B   |
```

在这种情况下，Pandoc 会将表格当作普通文本段落处理，导致 PDF/PNG 中无法显示表格。

**正确格式：**

```markdown
这是一段文字：

| 列1 | 列2 |
|-----|-----|
| A   | B   |
```

表格前必须有空行。

## 自动格式化

项目会在生成 Markdown 文件后自动调用 `markdownlint-cli2 --fix` 来修复格式问题。

### 在代码中使用

```python
from pathlib import Path
from b2t.converter.markdown_formatter import format_markdown_with_markdownlint

# 格式化单个文件
md_path = Path("summary.md")
format_markdown_with_markdownlint(md_path)
```

### 批量格式化

```python
from pathlib import Path
from b2t.converter.markdown_formatter import batch_format_markdown

# 批量格式化目录中的所有 .md 文件
directory = Path("./transcriptions")
count = batch_format_markdown(directory, pattern="*.md")
print(f"共格式化 {count} 个文件")
```

## CLI 工具

项目提供了一个命令行工具来手动格式化 Markdown 文件：

### 格式化单个文件

```bash
.venv/bin/python scripts/format_markdown.py file.md
```

### 格式化多个文件

```bash
.venv/bin/python scripts/format_markdown.py file1.md file2.md file3.md
```

### 批量格式化目录

```bash
# 格式化目录中所有 .md 文件
.venv/bin/python scripts/format_markdown.py --directory ./transcriptions

# 只格式化特定模式的文件
.venv/bin/python scripts/format_markdown.py --directory ./transcriptions --pattern "*_summary.md"
```

## 自动集成位置

`markdownlint-cli2` 自动格式化已集成到以下位置：

1. **总结生成** (`b2t/summarize/llm.py`)
   - `summarize()` 函数：生成总结后自动格式化
   - `export_summary_table_markdown()` 函数：导出表格后自动格式化

2. **Pipeline 处理** (如果有)
   - 在生成 Markdown 文件后自动调用格式化

## 安装 markdownlint-cli2

如果尚未安装 `markdownlint-cli2`，可以使用以下命令安装：

```bash
# 使用 npm
npm install -g markdownlint-cli2

# 使用 Homebrew (macOS)
brew install markdownlint-cli2
```

如果未安装，格式化功能会被静默跳过，不会影响正常流程。

## 配置

`markdownlint-cli2` 会读取项目根目录下的配置文件（如果存在）：

- `.markdownlint.json`
- `.markdownlint.yaml`
- `.markdownlintrc`

可以通过配置文件来自定义规则。例如，禁用某些规则：

```json
{
  "MD013": false,  // 禁用行长度限制
  "MD033": false   // 允许内联 HTML
}
```

## 错误处理

- 使用 `|| true` 来忽略 `markdownlint-cli2` 的错误退出码
- 某些规则的报错（如 MD013 行长度限制）会被忽略
- 如果 `markdownlint-cli2` 未安装，会静默跳过格式化
- 格式化失败不会影响主流程

## 测试

运行测试以验证格式化功能：

```bash
.venv/bin/python test_markdownlint_integration.py
```

## 修复的常见问题

`markdownlint-cli2` 会自动修复以下问题：

1. **MD022**: 表格前后缺少空行
2. **MD047**: 文件末尾缺少换行符
3. **MD060**: 表格列对齐问题
4. **MD009**: 行尾空格
5. **MD010**: 使用空格代替 Tab
6. **MD012**: 连续多个空行

更多规则请参考：https://github.com/DavidAnson/markdownlint/blob/main/doc/Rules.md
